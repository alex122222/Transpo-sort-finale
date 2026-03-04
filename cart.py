import os
import math
import numpy as np
import networkx as nx
import osmnx as ox
import folium
from folium.plugins import HeatMap
import rioxarray
from shapely.geometry import Point
from pyproj import Transformer
from tqdm import tqdm

from ortools.sat.python import cp_model



place_query = "Plovdiv, Bulgaria"
raster_path = "bgr_pop_2025_CN_100m_R2025A_v1 (1).tif"

num_points = 1200  # heatmap grid density (increase for smoother heatmap)

walk_distance_m = 600
min_stop_distance_m = 300
num_candidate_points = 180
coverage_target = 0.95
street_density_factor = 0.8

# OR-Tools
TIME_LIMIT_S = 240
WORKERS = 8



# Helper: choose correct polygon (avoid country/huge admin)

def geocode_best_city_polygon(query: str, max_try: int = 10):
    """
    Try multiple Nominatim results and pick a reasonable city-sized polygon
    to avoid country/municipality boundaries.
    """
    candidates = []

    for k in range(max_try):
        try:
            gdf = ox.geocode_to_gdf(query, which_result=k)
            area_km2 = float(gdf.to_crs(epsg=3857).geometry.area.iloc[0] / 1e6)

            display_name = (
                gdf["display_name"].iloc[0]
                if "display_name" in gdf.columns and len(gdf) > 0
                else f"result {k}"
            )
            candidates.append((k, area_km2, display_name, gdf))
        except Exception:
            continue

    if not candidates:
        raise RuntimeError("No geocoding results returned.")

    candidates.sort(key=lambda x: x[1])  # smallest first

    print("Geocode candidates (smallest area first):")
    for k, area, name, _ in candidates[:10]:
        print(f"  which_result={k}: area={area:.2f} km² | {name}")

    # Pick something that looks like a city/town footprint (tweak range if needed)
    for k, area, name, gdf in candidates:
        if 2 <= area <= 300:
            print(f"\n[OK] Using which_result={k} (area={area:.2f} km²)")
            return gdf

    # Fallback: smallest polygon
    k, area, name, gdf = candidates[0]
    print(f"\n[WARN] Fallback: using smallest which_result={k} (area={area:.2f} km²)")
    return gdf





def is_stop_street(edge_data):
    hw = edge_data.get("highway")
    if isinstance(hw, list):
        hw = hw[0]
    # You can broaden this to include residential if coverage is poor:
    return hw in ("primary", "secondary", "tertiary")



def build_reach_lists(T: np.ndarray, walk_distance_m: float):
    nd, ns = T.shape
    finite_js_by_i = []
    near_js_by_i = []
    for i in range(nd):
        finite_js = np.where(np.isfinite(T[i, :]))[0].tolist()
        near_js = np.where(np.isfinite(T[i, :]) & (T[i, :] <= walk_distance_m))[0].tolist()
        finite_js_by_i.append(finite_js)
        near_js_by_i.append(near_js)
    return finite_js_by_i, near_js_by_i


def solve_mclp(T, pop, P, walk_distance_m, time_limit_s=240, workers=8):
    """
    MCLP: pick exactly P facilities to maximize covered population within walk_distance_m.
    """
    nd, ns = T.shape
    finite_js_by_i, near_js_by_i = build_reach_lists(T, walk_distance_m)

    bad = [i for i in range(nd) if len(finite_js_by_i[i]) == 0]
    if bad:
        raise RuntimeError(
            f"{len(bad)} demand nodes have no reachable candidates at all. "
            "Increase cutoff / broaden candidates / fix network."
        )

    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"x_{j}") for j in range(ns)]

    y = {}
    for i in range(nd):
        for j in finite_js_by_i[i]:
            y[(i, j)] = model.NewBoolVar(f"y_{i}_{j}")

    z = [model.NewBoolVar(f"z_{i}") for i in range(nd)]

    model.Add(sum(x) == int(P))

    for i in range(nd):
        model.Add(sum(y[(i, j)] for j in finite_js_by_i[i]) == 1)

    for (i, j), var in y.items():
        model.Add(var <= x[j])

    for i in range(nd):
        near = near_js_by_i[i]
        if len(near) == 0:
            model.Add(z[i] == 0)
            continue
        model.Add(z[i] <= sum(y[(i, j)] for j in near))
        for j in near:
            model.Add(z[i] >= y[(i, j)])

    pop_int = np.round(pop).astype(int)
    model.Maximize(sum(pop_int[i] * z[i] for i in range(nd)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(workers)

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("MCLP: No feasible solution found.")

    chosen_js = [j for j in range(ns) if solver.Value(x[j]) == 1]
    covered_pop_int = int(sum(pop_int[i] * solver.Value(z[i]) for i in range(nd)))

    return chosen_js, covered_pop_int


def solve_p_median_with_coverage_constraint(
    T,
    pop,
    P,
    walk_distance_m,
    C_star_int,
    time_limit_s=240,
    workers=8,
    distance_scale=10.0,
):
    """
    Pick exactly P stops, assign each demand to an open stop, minimize pop-weighted distance,
    subject to covered_pop >= C_star_int.
    """
    nd, ns = T.shape
    finite_js_by_i, near_js_by_i = build_reach_lists(T, walk_distance_m)

    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"x_{j}") for j in range(ns)]

    y = {}
    for i in range(nd):
        for j in finite_js_by_i[i]:
            y[(i, j)] = model.NewBoolVar(f"y_{i}_{j}")

    z = [model.NewBoolVar(f"z_{i}") for i in range(nd)]

    model.Add(sum(x) == int(P))

    for i in range(nd):
        model.Add(sum(y[(i, j)] for j in finite_js_by_i[i]) == 1)

    for (i, j), var in y.items():
        model.Add(var <= x[j])

    for i in range(nd):
        near = near_js_by_i[i]
        if len(near) == 0:
            model.Add(z[i] == 0)
            continue
        model.Add(z[i] <= sum(y[(i, j)] for j in near))
        for j in near:
            model.Add(z[i] >= y[(i, j)])

    pop_int = np.round(pop).astype(int)
    covered_pop_expr = sum(pop_int[i] * z[i] for i in range(nd))
    model.Add(covered_pop_expr >= int(C_star_int))

    obj_terms = []
    for (i, j), var in y.items():
        dij = T[i, j]
        if not np.isfinite(dij):
            continue
        coeff = int(round(pop_int[i] * dij * float(distance_scale)))
        obj_terms.append(coeff * var)

    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(workers)

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("P-median (coverage constrained): No feasible solution found.")

    chosen_js = [j for j in range(ns) if solver.Value(x[j]) == 1]

    # coverage report
    covered_pop_int = int(sum(pop_int[i] * solver.Value(z[i]) for i in range(nd)))
    total_pop_int = int(pop_int.sum())
    coverage_pct = 100.0 * covered_pop_int / max(1, total_pop_int)

    return chosen_js, covered_pop_int, coverage_pct



def run_cart_optimization(place_query: str, walk_distance_m: float, min_stop_distance_m: float, num_candidate_points: int):
    # 1) Get correct city polygon
    city_gdf = geocode_best_city_polygon(place_query)
    city_poly = city_gdf.geometry.iloc[0]

    # Use centroid for safe map center
    centroid = city_poly.centroid
    center_lat, center_lon = float(centroid.y), float(centroid.x)

    # 2) Load & clip raster to polygon
    print("\nClipping raster to selected polygon...")
    rds = rioxarray.open_rasterio(raster_path)

    city_gdf_proj = city_gdf.to_crs(rds.rio.crs)
    clipped = rds.rio.clip(city_gdf_proj.geometry.values, city_gdf_proj.crs)

    transformer = Transformer.from_crs("EPSG:4326", rds.rio.crs, always_xy=True)

    # 3) Generate grid points inside polygon
    minx, miny, maxx, maxy = city_gdf.total_bounds
    grid_n = int(np.sqrt(num_points))
    xs = np.linspace(minx, maxx, grid_n)
    ys = np.linspace(miny, maxy, grid_n)

    points = []
    for lat in ys:
        for lon in xs:
            if city_poly.covers(Point(lon, lat)):
                points.append((lat, lon))

    print(f"Grid points inside polygon: {len(points)}")

   
    heat = []
    for lat, lon in tqdm(points, desc="Sampling raster"):
        x, y = transformer.transform(lon, lat)
        try:
            val = clipped.sel(x=x, y=y, method="nearest").values
            w = float(np.asarray(val).item())
            if w > 0:
                heat.append([lat, lon, w])
        except Exception:
            pass

    print(f"Heatmap points used: {len(heat)}")
    if len(heat) == 0:
        raise RuntimeError(
            "Heat list is empty. Likely: polygon doesn't overlap raster, CRS mismatch, or raster values/nodata."
        )

    # 5) Optional: quick preview heatmap
    m_preview = folium.Map(location=[center_lat, center_lon], zoom_start=12)
    folium.GeoJson(city_gdf.__geo_interface__, name="Boundary").add_to(m_preview)
    HeatMap(heat, radius=15, blur=20).add_to(m_preview)

    # 6) Build walking graph inside polygon + add traffic-aware walking costs
    print("\nLoading walking graph inside city polygon...")
    G = ox.graph_from_polygon(city_poly, network_type="walk", simplify=True)

    traffic_penalty = {
        "residential": 1.0,
        "living_street": 1.0,
        "tertiary": 1.1,
        "secondary": 1.25,
        "primary": 1.4,
        "trunk": 1.6,
    }
    for _, _, _, d in G.edges(keys=True, data=True):
        highway = d.get("highway")
        if isinstance(highway, list):
            highway = highway[0]
        penalty = traffic_penalty.get(highway, 1.2)
        d["walk_cost"] = d.get("length", 0.0) * penalty

    print(f"Graph: {len(G.nodes)} nodes, {len(G.edges)} edges")

    # 7) Demand nodes: snap heat points to network + aggregate weights
    print("\nCreating demand nodes from heatmap points...")
    heat_arr = np.array(heat, dtype=float)  # columns: lat, lon, weight

    demand_nodes_raw = ox.distance.nearest_nodes(G, X=heat_arr[:, 1], Y=heat_arr[:, 0])

    pop_by_node = {}
    for node, w in zip(demand_nodes_raw, heat_arr[:, 2]):
        pop_by_node[node] = pop_by_node.get(node, 0.0) + float(w)

    demand_nodes = list(pop_by_node.keys())
    pop_per_dn = np.array([pop_by_node[n] for n in demand_nodes], dtype=float)

    print(f"Demand nodes after aggregation: {len(demand_nodes)}")

    # 8) Candidate stops: pick nodes on major streets + spacing constraint
    candidate_nodes_raw = list(
        set([u for u, v, d in G.edges(data=True) if is_stop_street(d)])
    )

    np.random.seed(42)
    if len(candidate_nodes_raw) > num_candidate_points:
        idx = np.random.choice(len(candidate_nodes_raw), num_candidate_points, replace=False)
        candidate_nodes_raw = [candidate_nodes_raw[i] for i in idx]

    candidate_nodes = []
    for n in candidate_nodes_raw:
        y, x = G.nodes[n]["y"], G.nodes[n]["x"]
        if all(
            ox.distance.great_circle(y, x, G.nodes[m]["y"], G.nodes[m]["x"]) >= min_stop_distance_m
            for m in candidate_nodes
        ):
            candidate_nodes.append(n)

    print(f"Candidate stops after spacing: {len(candidate_nodes)}")
    if len(candidate_nodes) == 0:
        raise RuntimeError("No candidate stops left after filtering/spacing. Broaden street types or reduce spacing.")

    # 9) Estimate P
    city_area_km2 = float(city_gdf.to_crs(epsg=3857).geometry.area.iloc[0] / 1e6)
    P = max(
        1,
        int(round(
            (coverage_target * city_area_km2) /
            (math.pi * (walk_distance_m / 1000) ** 2 * street_density_factor)
        ))
    )
    P = min(P, len(candidate_nodes), len(demand_nodes))
    print(f"City area: {city_area_km2:.2f} km² | Using P={P} stops | Walk={walk_distance_m}m")

    # 10) Compute distance matrix T ONCE
    nd, ns = len(demand_nodes), len(candidate_nodes)
    T = np.full((nd, ns), np.inf, dtype=float)

    cutoff = max(walk_distance_m * 5, 5000)
    print("\nComputing distance matrix T (once)...")
    for j, c in enumerate(tqdm(candidate_nodes, desc="Matrix")):
        lengths = nx.single_source_dijkstra_path_length(G, c, weight="walk_cost", cutoff=cutoff)
        for i, dn in enumerate(demand_nodes):
            d = lengths.get(dn, np.inf)
            if np.isfinite(d):
                T[i, j] = float(d)

    # Remove demand nodes that are unreachable from ALL candidates (finite check)
    reachable_idx = [i for i in range(nd) if np.any(np.isfinite(T[i, :]))]
    if len(reachable_idx) == 0:
        raise RuntimeError(
            f"No demand nodes are reachable from any candidate. "
            "Broaden candidate selection or increase cutoff."
        )

    demand_nodes = [demand_nodes[i] for i in reachable_idx]
    pop_per_dn = pop_per_dn[reachable_idx]
    T = T[reachable_idx, :]
    nd = len(demand_nodes)

    P = min(P, ns, nd)
    print(f"Reachable demand nodes: {nd} | Candidates: {ns} | Final P={P}")

    # 11) Stage 1: MCLP
    print("\nStage 1/2: Solving MCLP (maximize covered population)...")
    chosen_mclp, C_star_int = solve_mclp(
        T=T,
        pop=pop_per_dn,
        P=P,
        walk_distance_m=walk_distance_m,
        time_limit_s=TIME_LIMIT_S,
        workers=WORKERS,
    )

    total_pop_int = int(np.round(pop_per_dn).astype(int).sum())
    print(f"MCLP C*: {C_star_int} / {total_pop_int} ({100.0*C_star_int/max(1,total_pop_int):.2f}%)")

    # 12) Stage 2: P-median with coverage constraint covered_pop >= C*
    print("\nStage 2/2: Solving P-median with coverage constraint (>= C*)...")
    chosen_pmed, covered_pop2_int, coverage_pct2 = solve_p_median_with_coverage_constraint(
        T=T,
        pop=pop_per_dn,
        P=P,
        walk_distance_m=walk_distance_m,
        C_star_int=C_star_int,
        time_limit_s=TIME_LIMIT_S,
        workers=WORKERS,
        distance_scale=10.0,
    )

    print(f"P-median covered pop: {covered_pop2_int} / {total_pop_int} ({coverage_pct2:.2f}%)")

    final_stops = [candidate_nodes[j] for j in chosen_pmed]
    print(f"[OK] Final stops selected: {len(final_stops)}")
    print("Final stops count:", len(final_stops))
    print("Final stops sample lat/lon:", [
        (float(G.nodes[n]["y"]), float(G.nodes[n]["x"])) for n in final_stops[:5]
    ])

    # Extra: “within walk distance” coverage using T and chosen set
    min_dist = np.min(T[:, chosen_pmed], axis=1)
    coverage_within_walk = float(np.mean(min_dist <= walk_distance_m) * 100.0)
    print(f"Coverage within {walk_distance_m}m (by demand nodes): {coverage_within_walk:.2f}%")

    # 13) Map final result
    m2 = folium.Map(location=[center_lat, center_lon], zoom_start=12)
    folium.GeoJson(city_gdf.__geo_interface__, name="Boundary").add_to(m2)
    folium.map.CustomPane("heat_pane", z_index=200).add_to(m2)
    HeatMap(heat, radius=15, blur=20, pane="heat_pane").add_to(m2)

    folium.map.CustomPane("stops_pane", z_index=999).add_to(m2)

    stops_fg = folium.FeatureGroup(name="Proposed Stops", overlay=True).add_to(m2)
    
    for node in final_stops:
        lat = float(G.nodes[node]["y"])
        lon = float(G.nodes[node]["x"])
        folium.CircleMarker(
            location=[lat, lon],
            radius=10,
            color="black",
            weight=3,
            fill=True,
            fill_color="cyan",
            fill_opacity=1.0,
            pane="stops_pane",
            tooltip=f"Stop node {node}",
            popup=f"Stop node {node}<br>{lat:.6f}, {lon:.6f}",
        ).add_to(stops_fg)
        
    folium.LayerControl(collapsed=False).add_to(m2)

    # Save to templates so flask can render it
    os.makedirs("templates/generated", exist_ok=True)
    import time, re
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", place_query).strip("_")
    stamp = int(time.time())
    out_html = f"templates/generated/{slug}_coverage_{stamp}.html"
    
    print("Saving to:", out_html)
    m2.save(out_html)
    print(f"[OK] Saved: {out_html}")
    
    # Return the route path that Flask can serve
    return f"/generated_map/{os.path.basename(out_html)}"

if __name__ == "__main__":
    run_cart_optimization("Plovdiv, Bulgaria", 600, 300, 180)