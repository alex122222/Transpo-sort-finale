import random
import math
import numpy as np
import networkx as nx
import osmnx as ox
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union, transform
from pyproj import Transformer
from scipy.spatial import Voronoi

def generate_synthetic_neighborhood(
    polygon_wgs84: Polygon,
    spacing_m: int = 120,
    seed: int = 42,
    layout: str = "grid",
    G_city = None
):
    """
    Main entry point for generating synthetic neighborhoods.
    Dispatches to the fast grid generator or organic generator based on layout.
    """
    random.seed(seed)
    np.random.seed(seed)
    
    def make_curved_line_wgs84(x1, y1, x2, y2, segments=3, max_offset=7.0, is_straight=False):
        # x, y are in meters
        lon1, lat1 = inv.transform(x1, y1)
        lon2, lat2 = inv.transform(x2, y2)
        
        if is_straight or max_offset == 0:
            return LineString([(lon1, lat1), (lon2, lat2)])

        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < 15:
            # too short to curve nicely
            return LineString([(lon1, lat1), (lon2, lat2)])
        
        nx_v = -dy / length
        ny_v = dx / length
        
        pts = [(lon1, lat1)]
        # Pick one fixed curve magnitude for a clean arc
        arc_max = random.uniform(-max_offset, max_offset)
        
        for i in range(1, segments):
            t = i / segments
            # Smooth sine wave arc to prevent jittery/jagged roads
            offset = math.sin(t * math.pi) * arc_max
                
            mx = x1 + dx * t + nx_v * offset
            my = y1 + dy * t + ny_v * offset
            mlon, mlat = inv.transform(mx, my)
            pts.append((mlon, mlat))
            
        pts.append((lon2, lat2))
        return LineString(pts)
    
    # We still need a city graph to align grid-like to reality
    # But since the original signature didn't take G_city, we might have to use default bearings
    # Or we can just use the fast grid graph inside polygon generator directly
    
    # Define Manhattan Land Boundary (Approximation)
    MANHATTAN_LAND = Polygon([
        (-74.020, 40.700), (-74.018, 40.710), (-74.010, 40.750), 
        (-73.990, 40.800), (-73.960, 40.850), (-73.930, 40.870), 
        (-73.910, 40.870), (-73.920, 40.850), (-73.940, 40.800), 
        (-73.950, 40.770), (-73.970, 40.740), (-73.975, 40.710), 
        (-74.020, 40.700)
    ])
    
    if not polygon_wgs84.intersects(MANHATTAN_LAND):
        valid_land = polygon_wgs84
    else:
        valid_land = polygon_wgs84.intersection(MANHATTAN_LAND)
    
    if valid_land.geom_type == 'MultiPolygon':
        valid_land = max(valid_land.geoms, key=lambda a: a.area)
    elif valid_land.geom_type not in ['Polygon', 'MultiPolygon']:
        return {"graph": nx.Graph(), "streets": [], "buildings": [], "demand": [], "demand_m": [], "transformer": None}

    # ---- Project to meters ----
    lon, lat = valid_land.centroid.x, valid_land.centroid.y
    zone = int((lon + 180) // 6) + 1
    epsg = 32600 + zone
    fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)

    def to_wgs84(geom):
        return transform(lambda x, y: inv.transform(x, y), geom)

    poly_m = Polygon([fwd.transform(x, y) for x, y in valid_land.exterior.coords])
    
    if layout in ["grid", "grid-like", "gridlike"]:
        # Use fast analytic grid generator
        b1, b2 = 30.0, 120.0 
        
        # Orient using logical city flow if available
        if G_city is not None:
            try:
                import osmnx as ox
                import pandas as pd
                print("Calculating dominant logistical street bearing from surrounding city...")
                # Calculate bearings of edges
                G_city_bearings = ox.bearing.add_edge_bearings(G_city.copy())
                bearings = pd.Series([d.get('bearing', 0) for u, v, k, d in G_city_bearings.edges(keys=True, data=True)])
                if not bearings.empty:
                    bins = np.arange(0, 370, 10)
                    hist, bin_edges = np.histogram(bearings, bins=bins)
                    b1 = float(bin_edges[np.argmax(hist)])
                    b2 = b1 + 90.0
                    print(f"Success! Aligned synthetic grid to standard orientation {b1} / {b2}")
            except Exception as e:
                print(f"Using default orientation (calculation failed): {e}")
        G_syn_m = build_cross_roundabout_graph_inside_polygon(
            poly_m=poly_m,
            b1_deg=b1,
            b2_deg=b2,
            r_radius_m=45.0,  # Make the roundabout large enough to match the visual reference
            snap_decimals=1,
            highway="primary"
        )
        
        # Build WGS84 streets
        streets_wgs84 = []
        for u, v, d in G_syn_m.edges(data=True):
            x1, y1 = G_syn_m.nodes[u]["x"], G_syn_m.nodes[u]["y"]
            x2, y2 = G_syn_m.nodes[v]["x"], G_syn_m.nodes[v]["y"]
            is_roundabout = d.get("junction") == "roundabout"
            curved_ls = make_curved_line_wgs84(x1, y1, x2, y2, segments=6, max_offset=0.0 if is_roundabout else 3.0, is_straight=is_roundabout)
            streets_wgs84.append(curved_ls)
            
        # Build meter-scale lines for intersection testing
        all_streets_m = []
        for u, v, d in G_syn_m.edges(data=True):
            s_ls_m = LineString([(G_syn_m.nodes[u]["x"], G_syn_m.nodes[u]["y"]), 
                                 (G_syn_m.nodes[v]["x"], G_syn_m.nodes[v]["y"])])
            all_streets_m.append(s_ls_m)

        buildings_wgs84, demand_wgs84, demand_m = generate_buildings_and_demand_fast(
            poly_m=poly_m,
            inv_transformer=inv,
            all_streets_m=all_streets_m,
            n_buildings=35, # Drastically reduced to make the inside clean
            seed=seed,
            shrink_m=spacing_m * 0.15
        )
        
        return {
            "graph": G_syn_m,
            "streets": streets_wgs84,
            "buildings": buildings_wgs84,
            "demand": demand_wgs84,
            "demand_m": demand_m,
            "transformer": inv,
        }
    
    else:
        # Fallback to orginal spatial approach for "organic"
        minx, miny, maxx, maxy = poly_m.bounds
        streets = []
        area_sqm = poly_m.area
        num_points_request = int(area_sqm / (spacing_m * spacing_m)) * 2
        num_points = min(num_points_request, 1000)
        num_points = max(num_points, 15)

        points = []
        for _ in range(num_points):
            px = random.uniform(minx - 100, maxx + 100)
            py = random.uniform(miny - 100, maxy + 100)
            points.append([px, py])
            
        vor = Voronoi(points)
        vertices = vor.vertices
        poly_bounds = poly_m.bounds 
        
        for ridge in vor.ridge_vertices:
            if -1 in ridge: continue 
            p1 = vertices[ridge[0]]
            p2 = vertices[ridge[1]]
            
            line_minx = min(p1[0], p2[0])
            line_maxx = max(p1[0], p2[0])
            line_miny = min(p1[1], p2[1])
            line_maxy = max(p1[1], p2[1])
            
            if (line_maxx < poly_bounds[0] or line_minx > poly_bounds[2] or
                line_maxy < poly_bounds[1] or line_miny > poly_bounds[3]):
                continue

            ls = LineString([p1, p2])
            if ls.intersects(poly_m):
                clipped = ls.intersection(poly_m)
                if not clipped.is_empty:
                    if isinstance(clipped, LineString):
                        streets.append(clipped)
                    elif hasattr(clipped, 'geoms'):
                        for geom in clipped.geoms:
                            if isinstance(geom, LineString):
                                streets.append(geom)

        # Apply curvature to organic streets too (which are in meters here, wait, we do wgs84 conversion at the end)
        # So we just wait till the legacy interface compatibility step.
        all_streets = unary_union(streets)
        
        if isinstance(all_streets, LineString):
            all_streets = [all_streets]
        elif hasattr(all_streets, 'geoms'):
            all_streets = list(all_streets.geoms)
        else:
            all_streets = []
            
        G = nx.Graph()
        node_map = {} 
        
        def get_node_id(x, y):
            k = (round(x, 2), round(y, 2))
            if k not in node_map:
                node_map[k] = len(node_map)
                G.add_node(node_map[k], x=x, y=y)
            return node_map[k]

        for line in all_streets:
            if not hasattr(line, 'coords'):
                continue
            coords = list(line.coords)
            for i in range(len(coords)-1):
                u = get_node_id(*coords[i])
                v = get_node_id(*coords[i+1])
                d = math.hypot(coords[i][0]-coords[i+1][0], coords[i][1]-coords[i+1][1])
                G.add_edge(u, v, length=d, weight=d)

        buildings = []
        demand = []
        developable = poly_m.buffer(-20)

        if developable.is_empty:
            developable = poly_m

        for _ in range(80): # Reduced from 150 to make it less busy
            cx = random.uniform(minx, maxx)
            cy = random.uniform(miny, maxy)
            b = box(cx - 10, cy - 10, cx + 10, cy + 10)
            
            # Ensure building does not overlap our valid generated streets
            if developable.contains(b):
                overlap = False
                for st in all_streets:
                    if b.intersects(st):
                        overlap = True
                        break
                if overlap:
                    continue
                    
                buildings.append(b)
                lon, lat = inv.transform(b.centroid.x, b.centroid.y)
                demand.append((lat, lon, 100.0))
        
        # For legacy interface compatibility
        streets_wgs84 = []
        for s in streets:
            coords = list(s.coords)
            if len(coords) >= 2:
                # We curve each segment
                for i in range(len(coords) - 1):
                    x1, y1 = coords[i]
                    x2, y2 = coords[i+1]
                    curved = make_curved_line_wgs84(x1, y1, x2, y2, segments=6, max_offset=3.0)
                    streets_wgs84.append(curved)

        buildings_wgs84 = [to_wgs84(b) for b in buildings]

        return {
            "graph": G,
            "streets": streets_wgs84,
            "buildings": buildings_wgs84,
            "demand": demand,
            "demand_m": [(b.centroid.y, b.centroid.x, b.area) for b in buildings], 
            "transformer": inv,
        }

# ------------------------------------------------------------
# FAST Grid Helpers
# ------------------------------------------------------------
def _unit_vec_from_bearing(bearing_deg: float):
    th = math.radians(bearing_deg)
    return math.sin(th), math.cos(th)

def _perp_vec(dx, dy):
    return -dy, dx

def _dot(ax, ay, bx, by):
    return ax * bx + ay * by

def build_cross_roundabout_graph_inside_polygon(
    poly_m: Polygon,
    b1_deg: float,
    b2_deg: float,
    r_radius_m: float = 30.0,
    snap_decimals: int = 1,
    highway: str = "primary",
):
    cx, cy = float(poly_m.centroid.x), float(poly_m.centroid.y)
    
    # 4 rays from the center forming a cross
    rays = [b1_deg, b1_deg + 180.0, b2_deg, b2_deg + 180.0]
    
    G = nx.Graph()
    node_id = {}
    
    def get_nid(x, y):
        k = (round(x, snap_decimals), round(y, snap_decimals))
        if k not in node_id:
            nid = len(node_id)
            node_id[k] = nid
            G.add_node(nid, x=float(k[0]), y=float(k[1]))
        return node_id[k]
        
    line_len = max(poly_m.bounds[2] - poly_m.bounds[0], poly_m.bounds[3] - poly_m.bounds[1]) * 2.0
    
    ring_nodes = []
    
    for angle_deg in rays:
        dx, dy = _unit_vec_from_bearing(angle_deg)
        
        # Roundabout connection point for this ray
        rx = cx + dx * r_radius_m
        ry = cy + dy * r_radius_m
        r_nid = get_nid(rx, ry)
        ring_nodes.append((angle_deg % 360, r_nid))
        
        # Ray end point far outside
        ex = cx + dx * line_len
        ey = cy + dy * line_len
        
        # Intersect line (rx, ry) to (ex, ey) with polygon
        ray_line = LineString([(rx, ry), (ex, ey)])
        if ray_line.intersects(poly_m):
            clipped = ray_line.intersection(poly_m)
            
            if isinstance(clipped, LineString):
                coords = list(clipped.coords)
            elif hasattr(clipped, 'geoms'):
                longest = max(clipped.geoms, key=lambda g: g.length)
                coords = list(longest.coords)
            else:
                continue
                
            if len(coords) >= 2:
                # Find the farthest point from the center along this line
                coords = sorted(coords, key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
                px, py = coords[-1]
                
                # Edge from roundabout ring to the boundary
                p_nid = get_nid(px, py)
                d = math.hypot(px - rx, py - ry)
                if d > 1.0:
                    G.add_edge(r_nid, p_nid, length=float(d), weight=float(d), highway=highway)
                
    # Connect ring nodes into a circular roundabout
    ring_nodes.sort(key=lambda x: x[0])
    for i in range(len(ring_nodes)):
        n1 = ring_nodes[i][1]
        n2 = ring_nodes[(i + 1) % len(ring_nodes)][1]
        
        x1, y1 = G.nodes[n1]["x"], G.nodes[n1]["y"]
        x2, y2 = G.nodes[n2]["x"], G.nodes[n2]["y"]
        d = math.hypot(x2 - x1, y2 - y1)
        G.add_edge(n1, n2, length=float(d), weight=float(d), highway="primary", junction="roundabout")
        
    return G

def generate_buildings_and_demand_fast(
    poly_m: Polygon,
    inv_transformer,
    all_streets_m: list = None,
    n_buildings: int = 35,
    seed: int = 42,
    building_halfsize_m: float = 10.0,
    pop_range=(100, 100),
    shrink_m: float = 20.0,
):
    rng = random.Random(seed)
    developable = poly_m.buffer(-shrink_m)
    if developable.is_empty:
        developable = poly_m

    minx, miny, maxx, maxy = developable.bounds

    buildings_m = []
    demand_wgs84 = []
    demand_m = []
    
    # Pre-buffer streets slightly so buildings don't touch the very edge of the road
    buffered_streets = []
    if all_streets_m:
        for st in all_streets_m:
            buffered_streets.append(st.buffer(8.0))

    tries = 0
    while len(buildings_m) < n_buildings and tries < n_buildings * 80:
        tries += 1
        cx = rng.uniform(minx, maxx)
        cy = rng.uniform(miny, maxy)
        b = box(cx - building_halfsize_m, cy - building_halfsize_m,
                cx + building_halfsize_m, cy + building_halfsize_m)
        if developable.contains(b):
            # Check overlap against generated streets
            overlap = False
            for b_st in buffered_streets:
                if b.intersects(b_st):
                    overlap = True
                    break
            if overlap:
                continue
                
            pop = float(rng.randint(pop_range[0], pop_range[1]))
            buildings_m.append(b)

            x_m, y_m = float(b.centroid.x), float(b.centroid.y)
            lon, lat = inv_transformer.transform(x_m, y_m)
            demand_wgs84.append((float(lat), float(lon), pop))
            demand_m.append((float(y_m), float(x_m), pop))

    buildings_wgs84 = [transform(lambda x, y: inv_transformer.transform(x, y), b) for b in buildings_m]
    return buildings_wgs84, demand_wgs84, demand_m

# --------------------------
# City Merge Support Methods
# --------------------------
def _boundary_points_even(poly_wgs84, k: int):
    ring = poly_wgs84.exterior
    L = float(ring.length)
    if L <= 0 or k <= 0:
        return []
    ds = np.linspace(0.0, L, num=int(k), endpoint=False)
    return [ring.interpolate(float(d)) for d in ds]

def merge_synthetic_neighborhood_into_osmnx_city(
    G_city,                 
    G_syn_m,                
    poly_wgs84,             
    inv_transformer,        
    connector_k: int = 8,  
    max_attach_m: float = 600.0,  
    syn_prefix: str = "syn",       
    conn_prefix: str = "conn",     
    add_bidirectional: bool = True 
):
    G_out = G_city.copy()
    syn_nodes = []
    for n, d in G_syn_m.nodes(data=True):
        x_m = float(d["x"])
        y_m = float(d["y"])
        lon, lat = inv_transformer.transform(x_m, y_m)  
        new_n = (syn_prefix, n)
        G_out.add_node(new_n, x=float(lon), y=float(lat), _src="synthetic")
        syn_nodes.append(new_n)

    for u, v, ed in G_syn_m.edges(data=True):
        uu = (syn_prefix, u)
        vv = (syn_prefix, v)
        length_m = float(ed.get("length", ed.get("weight", 0.0)) or 0.0)

        if isinstance(G_out, nx.MultiDiGraph) or isinstance(G_out, nx.MultiGraph):
            G_out.add_edge(uu, vv, length=length_m, _src="synthetic")
            if add_bidirectional:
                G_out.add_edge(vv, uu, length=length_m, _src="synthetic")
        else:
            G_out.add_edge(uu, vv, length=length_m, _src="synthetic")

    if not syn_nodes:
        return G_out

    syn_xy = np.array([(G_out.nodes[n]["x"], G_out.nodes[n]["y"]) for n in syn_nodes], dtype=float)

    def nearest_syn_node(lon, lat):
        dx = syn_xy[:, 0] - lon
        dy = syn_xy[:, 1] - lat
        idx = int(np.argmin(dx * dx + dy * dy))
        return syn_nodes[idx]

    # Instead of random wrapper boundary points, use the actual endpoints of the synthetic streets
    # Endpoint nodes will have a degree of 1. If none are found, gracefully fallback.
    endpoint_nodes = [n for n, deg in G_syn_m.degree() if deg == 1]
    if not endpoint_nodes:
        endpoint_nodes = list(G_syn_m.nodes())[:connector_k]
    
    # We only take up to connector_k endpoints to prevent spam in large grids
    if len(endpoint_nodes) > connector_k:
        random.shuffle(endpoint_nodes)
        endpoint_nodes = endpoint_nodes[:connector_k]

    # Filter city graph to strictly nodes OUTSIDE the polygon
    outside_nodes = [n for n, d in G_city.nodes(data=True) if not poly_wgs84.contains(Point(d['x'], d['y']))]
    G_outside = G_city.subgraph(outside_nodes) if outside_nodes else G_city

    for i, syn_n in enumerate(endpoint_nodes):
        # The coordinate of the synthetic node IN WGS84
        syn_x_m = G_syn_m.nodes[syn_n]["x"]
        syn_y_m = G_syn_m.nodes[syn_n]["y"]
        lon_wgs, lat_wgs = inv_transformer.transform(syn_x_m, syn_y_m)
        lon, lat = float(lon_wgs), float(lat_wgs)

        try:
            city_n = ox.distance.nearest_nodes(G_outside, X=lon, Y=lat)
        except Exception:
            continue

        city_lon = float(G_city.nodes[city_n]["x"])
        city_lat = float(G_city.nodes[city_n]["y"])

        if hasattr(ox.distance, 'great_circle_vec'):
            dist_to_city_m = float(ox.distance.great_circle_vec(lat, lon, city_lat, city_lon))
        elif hasattr(ox.distance, 'great_circle'):
            dist_to_city_m = float(ox.distance.great_circle(lat, lon, city_lat, city_lon))
        else:
            # Fallback haversine approximation
            dist_to_city_m = math.hypot(lon - city_lon, lat - city_lat) * 111000.0

        if dist_to_city_m > float(max_attach_m):
            continue

        # Make the connection feel more like a real street by adding jitter
        jittered_lon = lon + random.uniform(-0.0005, 0.0005)
        jittered_lat = lat + random.uniform(-0.0005, 0.0005)
        
        # Calculate distance to jittered coordinates
        if hasattr(ox.distance, 'great_circle_vec'):
            dist_to_city_m = float(ox.distance.great_circle_vec(jittered_lat, jittered_lon, city_lat, city_lon))
        elif hasattr(ox.distance, 'great_circle'):
            dist_to_city_m = float(ox.distance.great_circle(jittered_lat, jittered_lon, city_lat, city_lon))
        else:
            dist_to_city_m = math.hypot(jittered_lon - city_lon, jittered_lat - city_lat) * 111000.0
            
        conn_n = (conn_prefix, i)
        # Add the connection node using WGS84 coordinates since G_out is a WGS84 graph
        G_out.add_node(conn_n, x=jittered_lon, y=jittered_lat, _src="connector")

        gate_len = float(min(10.0, max(1.0, dist_to_city_m * 0.1)))
        
        syn_node_key = (syn_prefix, syn_n)

        if isinstance(G_out, nx.MultiDiGraph) or isinstance(G_out, nx.MultiGraph):
            G_out.add_edge(conn_n, syn_node_key, length=gate_len, _src="connector")
            if add_bidirectional:
                G_out.add_edge(syn_node_key, conn_n, length=gate_len, _src="connector")

            G_out.add_edge(conn_n, city_n, length=dist_to_city_m, _src="connector")
            if add_bidirectional:
                G_out.add_edge(city_n, conn_n, length=dist_to_city_m, _src="connector")
        else:
            G_out.add_edge(conn_n, syn_node_key, length=gate_len, _src="connector")
            G_out.add_edge(conn_n, city_n, length=dist_to_city_m, _src="connector")

    return G_out
