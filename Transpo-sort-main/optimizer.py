import numpy as np
import networkx as nx
from shapely.geometry import Point
import osmnx as ox
import math
from pyproj import Transformer
from cart import solve_mclp, solve_p_median_with_coverage_constraint, build_reach_lists

def place_new_stops(G: nx.Graph, demand, k=5, weight_key="walk_cost"):
    """
    Demand: list of (lat, lon, w) in WGS84.
    Graph G: node attributes x,y are in meters (UTM) in your synthetic graph.
    This function assumes demand points were generated from the same synthetic neighborhood
    and are roughly aligned; we snap demand to nearest graph nodes using Euclidean distance
    in the graph's coordinate space.

    Returns: list of (lat, lon) stop coordinates in WGS84 *IF* your graph x/y are lon/lat.
    If your graph x/y are meters, return (y, x) in meters (for internal use) OR convert outside.
    """
    if len(G.nodes) == 0:
        return []

    nodes = list(G.nodes)

    # --- Build arrays of node coords (graph space) ---
    node_xy = np.array([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in nodes], dtype=float)

    # --- Snap demand points to nearest nodes ---
    # demand is (lat, lon, w) but graph is in meters; your synthetic demand was derived
    # from buildings in meters then converted to WGS84, so snapping in WGS84 would be wrong.
    # Instead, we snap by converting demand back to graph space if you saved a transformer.
    #
    # For now, we assume demand was generated from the same synthetic generator
    # and is close enough that nearest-node in WGS84 is acceptable ONLY if graph is WGS84.
    #
    # If your synthetic graph is in meters (recommended), then do snapping during generation
    # and store demand as node ids. (Next step below.)

    # If your graph coords look like WGS84, do a simple snap in lon/lat space:
    looks_like_wgs84 = (
        -180 <= node_xy[:, 0].min() <= 180 and -90 <= node_xy[:, 1].min() <= 90
        and -180 <= node_xy[:, 0].max() <= 180 and -90 <= node_xy[:, 1].max() <= 90
    )

    demand_arr = np.array([(lon, lat, w) for (lat, lon, w) in demand], dtype=float)

    # nearest node by Euclidean in lon/lat (ok for small test areas)
    snapped_nodes = []
    weights = []
    for lon, lat, w in demand_arr:
        d2 = (node_xy[:, 0] - lon) ** 2 + (node_xy[:, 1] - lat) ** 2
        idx = int(np.argmin(d2))
        snapped_nodes.append(nodes[idx])
        weights.append(float(w))

    # aggregate weights per snapped node
    pop_by_node = {}
    for n, w in zip(snapped_nodes, weights):
        pop_by_node[n] = pop_by_node.get(n, 0.0) + w

    demand_nodes = list(pop_by_node.keys())
    demand_weights = np.array([pop_by_node[n] for n in demand_nodes], dtype=float)

    # --- Precompute shortest paths from all candidate nodes to all demand nodes ---
    # optimization: only compute for relevant nodes if graph is huge, but here it's small.
    # We need dist(candidate, demand_node) for all pairs.
    # Repeated Dijkstra from strictly possible candidates is efficient enough.
    
    # Pre-calculate distances from all nodes to all demand nodes
    # scores[candidate][demand_node] = distance
    dist_matrix = {}
    
    # If graph is large, we might want to limit candidates, but for this grid size, all nodes are fine.
    
    print(f"Precomputing paths for {len(nodes)} candidates and {len(demand_nodes)} demand clusters...")
    
    # We can run Dijkstra from each demand node to all other nodes (reverse), 
    # but since graph is undirected, dist(a,b) == dist(b,a).
    # Since |demand_nodes| usually < |nodes|, let's run from demand nodes.
    
    for dn in demand_nodes:
        # dists from dn to all other nodes
        lengths = nx.single_source_dijkstra_path_length(G, dn, weight=weight_key)
        dist_matrix[dn] = lengths

    # --- Greedy Selection ---
    
    chosen_stops = []
    
    # distinct demand nodes coverage state
    # current_min_walk[dn] = current walking distance to nearest chosen stop
    current_min_walk = {dn: float('inf') for dn in demand_nodes}
    
    for i in range(k):
        best_candidate = None
        best_reduction = -1.0
        
        # Try every node as the next stop
        for candidate in nodes:
            reduction = 0.0
            for dn, w in zip(demand_nodes, demand_weights):
                # distance from this demand node to this candidate
                dist = dist_matrix[dn].get(candidate, float('inf'))
                
                # if this candidate is closer than what we have efficiently
                current_dist = current_min_walk[dn]
                
                if dist < current_dist:
                    # improvement term
                    improvement = (current_dist - dist) * w 
                    reduction += improvement
            
            if reduction > best_reduction:
                best_reduction = reduction
                best_candidate = candidate
        
        if best_candidate is None or best_reduction <= 0:
             print("No further improvement found.")
             break
             
        chosen_stops.append(best_candidate)
        
        # Update current best walks
        for dn in demand_nodes:
            dist = dist_matrix[dn].get(best_candidate, float('inf'))
            if dist < current_min_walk[dn]:
                current_min_walk[dn] = dist
                
    # Return stop coordinates in same CRS as graph
    stops = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in chosen_stops]
    return stops

def place_stops_with_existing(
    G_merged: nx.Graph,
    poly_wgs84,
    synthetic_demand_wgs84: list,
    stop_mode: str = "auto",
    manual_k: int = 12,
    walk_distance_m: float = 600.0,
    coverage_target: float = 0.95,
    street_density_factor: float = 0.8,
    existing_stops_wgs84: list = None
):
    """
    Places new stops in the (synthetic + city) graph using generated synthetic demand and OR-Tools.
    
    synthetic_demand_wgs84: list of tuples (lat, lon, weight)
    existing_stops_wgs84: list of tuples (lat, lon)
    stop_mode: "auto" or "manual"
    """
    import geopandas as gpd
    
    if existing_stops_wgs84 is None:
        existing_stops_wgs84 = []
        
    print(f"Optimizer: Received {len(existing_stops_wgs84)} existing stops.")
        
    if not synthetic_demand_wgs84:
        print("Optimizer: No synthetic demand found. Falling back to greedy.")
        return []

    print(f"Optimizer: Received {len(synthetic_demand_wgs84)} synthetic demand points.")

    heat = synthetic_demand_wgs84

    # 4) Snapping demand strictly inside the polygon using G_merged edges
    # Filter G_merged to only nodes inside or near the polygon
    nodes_in_poly = [n for n, d in G_merged.nodes(data=True) if poly_wgs84.contains(Point(d['x'], d['y']))]
    if not nodes_in_poly:
        return []
        
    G_sub = G_merged.subgraph(nodes_in_poly).copy()
    
    # Add walking costs (in meters) to G_sub edges. G_merged coordinate space is WGS84 (lon=x, lat=y)
    for u, v, k_edge, d in G_sub.edges(keys=True, data=True) if G_sub.is_multigraph() else G_sub.edges(data=True):
        if "length" not in d:
            lon1, lat1 = G_sub.nodes[u]['x'], G_sub.nodes[u]['y']
            lon2, lat2 = G_sub.nodes[v]['x'], G_sub.nodes[v]['y']
            # Approximation
            dist = math.hypot(lon1 - lon2, lat1 - lat2) * 111000.0
            d["length"] = dist
            d["walk_cost"] = dist
        else:
            d["walk_cost"] = d["length"]

    heat_arr = np.array(heat, dtype=float)
    demand_nodes_raw = ox.distance.nearest_nodes(G_sub, X=heat_arr[:, 1], Y=heat_arr[:, 0])

    pop_by_node = {}
    for node, w in zip(demand_nodes_raw, heat_arr[:, 2]):
        pop_by_node[node] = pop_by_node.get(node, 0.0) + float(w)

    demand_nodes = list(pop_by_node.keys())
    pop_per_dn = np.array([pop_by_node[n] for n in demand_nodes], dtype=float)
    
    # 5) Identify ALL candidate nodes (we assume any node in G_sub can be a stop)
    candidate_nodes = list(G_sub.nodes())
    
    # 6) Identify exiting stops in candidate_nodes
    existing_js = []
    if existing_stops_wgs84:
        existing_lons = [lon for lat, lon in existing_stops_wgs84]
        existing_lats = [lat for lat, lon in existing_stops_wgs84]
        nearest_to_existing = ox.distance.nearest_nodes(G_sub, X=existing_lons, Y=existing_lats)
        
        # map back to candidate index `j`
        for n in nearest_to_existing:
            try:
                j = candidate_nodes.index(n)
                if j not in existing_js:
                    existing_js.append(j)
            except ValueError:
                pass

    print(f"Optimizer: Snapped to {len(existing_js)} valid existing stops inside graph.")

    # 7) Determine P (Total stops)
    if stop_mode == "auto":
        gdf = gpd.GeoDataFrame(geometry=[poly_wgs84], crs="EPSG:4326")
        gdf_3857 = gdf.to_crs(epsg=3857)
        area_km2 = float(gdf_3857.geometry.area.iloc[0] / 1e6)
        P = max(
            1,
            int(round(
                (coverage_target * area_km2) /
                (math.pi * (walk_distance_m / 1000) ** 2 * street_density_factor)
            ))
        )
        print(f"Optimizer: Auto-calculated P={P} for area {area_km2:.3f} km2")
    else:
        # Manual mode specifies EXACTLY how many NEW stops. 
        # But MCLP/P-median needs TOTAL stops (P).
        P = manual_k + len(existing_js)
        print(f"Optimizer: Manual mode. New={manual_k}, Existing={len(existing_js)} -> Total P={P}")
        
    P = min(P, len(candidate_nodes), len(demand_nodes))
    
    # If P is exactly the number of existing stops and we want 0 new ones, or network is totally saturated:
    if P <= len(existing_js) and stop_mode == "manual":
        # They asked for k new stops, so let's guarantee we add k if possible
        if len(candidate_nodes) >= manual_k + len(existing_js):
            P = manual_k + len(existing_js)

    # 8) Distance Matrix
    nd, ns = len(demand_nodes), len(candidate_nodes)
    T = np.full((nd, ns), np.inf, dtype=float)
    
    cutoff = walk_distance_m * 3.0
    for j, c in enumerate(candidate_nodes):
        lengths = nx.single_source_dijkstra_path_length(G_sub, c, weight="walk_cost", cutoff=cutoff)
        for i, dn in enumerate(demand_nodes):
            d = lengths.get(dn, np.inf)
            if np.isfinite(d):
                T[i, j] = float(d)
                
    reachable_idx = [i for i in range(nd) if np.any(np.isfinite(T[i, :]))]
    if len(reachable_idx) == 0:
        print("Optimizer: No reachable demand.")
        return []
        
    demand_nodes = [demand_nodes[i] for i in reachable_idx]
    pop_per_dn = pop_per_dn[reachable_idx]
    T = T[reachable_idx, :]
    nd = len(demand_nodes)
    P = min(P, ns)
    
    if P == 0:
        return []

    # 9) Solve MCLP & P-Median
    try:
        print("Optimizer: Running MCLP...")
        chosen_mclp, C_star_int = solve_mclp(
            T=T,
            pop=pop_per_dn,
            P=P,
            walk_distance_m=walk_distance_m,
            time_limit_s=60,
            workers=4,
            existing_js=existing_js
        )
        
        print(f"Optimizer: Running P-Median with C*={C_star_int}...")
        chosen_pmed, covered_pop2, coverage_pct2 = solve_p_median_with_coverage_constraint(
            T=T,
            pop=pop_per_dn,
            P=P,
            walk_distance_m=walk_distance_m,
            C_star_int=C_star_int,
            time_limit_s=60,
            workers=4,
            distance_scale=10.0,
            existing_js=existing_js
        )
        
        final_stops_js = chosen_pmed
        print(f"Optimizer: Successfully mapped {len(final_stops_js)} stops! Coverage: {coverage_pct2:.2f}%")
    except Exception as e:
        print(f"Optimizer: Math formulation failed: {e}. Falling back to greedy...")
        import traceback
        traceback.print_exc()
        return [] # We will catch this in web_app.py and fallback to greedy

    # 10) Return only the NEW stops
    new_stops = []
    for j in final_stops_js:
        if j not in existing_js:
            n = candidate_nodes[j]
            new_stops.append((G_sub.nodes[n]["y"], G_sub.nodes[n]["x"])) # (lat, lon)
            
    return new_stops


