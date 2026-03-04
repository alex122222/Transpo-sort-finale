import math
import random
import numpy as np
import networkx as nx
import osmnx as ox
from shapely.geometry import Polygon, Point, box
from shapely.ops import transform as shp_transform
from pyproj import Transformer


# ------------------------------------------------------------
# 0) CRS: pick UTM for polygon (meters) without geopandas
# ------------------------------------------------------------
def utm_epsg_from_lonlat(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    # north/south hemisphere
    return (32600 + zone) if lat >= 0 else (32700 + zone)


def project_polygon_to_utm(poly_wgs84: Polygon):
    lon0, lat0 = float(poly_wgs84.centroid.x), float(poly_wgs84.centroid.y)
    epsg = utm_epsg_from_lonlat(lon0, lat0)
    utm_crs = f"EPSG:{epsg}"

    fwd = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    inv = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    poly_m = shp_transform(lambda x, y: fwd.transform(x, y), poly_wgs84)
    return poly_m, fwd, inv, utm_crs


# ------------------------------------------------------------
# 1) Learn dominant bearings FAST from city graph (no gdfs)
# ------------------------------------------------------------
def _bearing_0_180_from_xy(x1, y1, x2, y2):
    # bearing from north, folded to [0,180)
    dx = x2 - x1
    dy = y2 - y1
    ang = math.degrees(math.atan2(dx, dy)) % 180.0
    return ang


def dominant_bearings_near_polygon_fast(
    G_city_wgs84,
    poly_wgs84: Polygon,
    sample_buffer_m: float = 800.0,
    bin_deg: float = 10.0,
    max_bearings: int = 6,
):
    """
    FAST:
    - project city graph to UTM
    - iterate edges and keep only those with an endpoint near polygon bbox(+buffer)
    - compute bearing from endpoint coords (no geometry)
    """
    poly_m, _, _, utm_crs = project_polygon_to_utm(poly_wgs84)
    Gm = ox.project_graph(G_city_wgs84, to_crs=utm_crs)

    minx, miny, maxx, maxy = poly_m.bounds
    minx -= sample_buffer_m
    miny -= sample_buffer_m
    maxx += sample_buffer_m
    maxy += sample_buffer_m

    hist = {}  # bin -> weight
    # OSMnx is MultiDiGraph: edges(u,v,key,data)
    for u, v, k, d in Gm.edges(keys=True, data=True):
        xu, yu = float(Gm.nodes[u]["x"]), float(Gm.nodes[u]["y"])
        xv, yv = float(Gm.nodes[v]["x"]), float(Gm.nodes[v]["y"])

        # quick bbox filter on endpoints
        in_u = (minx <= xu <= maxx) and (miny <= yu <= maxy)
        in_v = (minx <= xv <= maxx) and (miny <= yv <= maxy)
        if not (in_u or in_v):
            continue

        b = _bearing_0_180_from_xy(xu, yu, xv, yv)
        bbin = round(b / bin_deg) * bin_deg
        w = float(d.get("length", 1.0))
        hist[bbin] = hist.get(bbin, 0.0) + w

    if not hist:
        return [0.0, 90.0], utm_crs  # fallback

    ordered = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)
    bearings = [float(k) for k, _ in ordered[:max_bearings]]
    if len(bearings) == 1:
        bearings.append((bearings[0] + 90.0) % 180.0)

    return bearings, utm_crs


# ------------------------------------------------------------
# 2) Generate a city-aligned grid inside polygon FAST (analytic)
# ------------------------------------------------------------
def _unit_vec_from_bearing(bearing_deg: float):
    # bearing from north -> direction vector (dx,dy)
    th = math.radians(bearing_deg)
    return math.sin(th), math.cos(th)

def _perp_vec(dx, dy):
    return -dy, dx

def _dot(ax, ay, bx, by):
    return ax * bx + ay * by

def build_grid_graph_inside_polygon_fast(
    poly_m: Polygon,
    b1_deg: float,
    b2_deg: float,
    spacing_m: float,
    snap_decimals: int = 1,
    highway: str = "residential",
):
    """
    Build a grid graph by intersecting two families of parallel lines:
      Family A direction = b1
      Family B direction = b2 (prefer ~orthogonal)

    We avoid unary_union and heavy shapely ops by:
    - working in coordinates (t,u) along the two perpendicular axes
    - generating candidate intersection points
    - keeping only points inside polygon
    - connecting adjacent points in grid order (A- and B-neighbors)
    """
    dx1, dy1 = _unit_vec_from_bearing(b1_deg)
    px1, py1 = _perp_vec(dx1, dy1)  # spacing axis for family A lines

    dx2, dy2 = _unit_vec_from_bearing(b2_deg)
    px2, py2 = _perp_vec(dx2, dy2)

    # Use polygon bbox corners to estimate offset ranges
    minx, miny, maxx, maxy = poly_m.bounds
    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    cx, cy = float(poly_m.centroid.x), float(poly_m.centroid.y)

    # For each family, compute offset coordinate along its perpendicular axis
    offs1 = [_dot(x - cx, y - cy, px1, py1) for x, y in corners]
    offs2 = [_dot(x - cx, y - cy, px2, py2) for x, y in corners]
    o1_min, o1_max = min(offs1), max(offs1)
    o2_min, o2_max = min(offs2), max(offs2)

    # add margin so we cover fully
    margin = spacing_m * 3
    o1_min -= margin; o1_max += margin
    o2_min -= margin; o2_max += margin

    # build offset lists
    i1_min = int(math.floor(o1_min / spacing_m))
    i1_max = int(math.ceil(o1_max / spacing_m))
    i2_min = int(math.floor(o2_min / spacing_m))
    i2_max = int(math.ceil(o2_max / spacing_m))

    offs1_list = [i * spacing_m for i in range(i1_min, i1_max + 1)]
    offs2_list = [i * spacing_m for i in range(i2_min, i2_max + 1)]

    # Solve intersection of two lines:
    # Line A: (x,y) = (cx,cy) + (px1,py1)*o1 + (dx1,dy1)*t
    # Line B: (x,y) = (cx,cy) + (px2,py2)*o2 + (dx2,dy2)*s
    #
    # We can solve in 2x2 for (t,s). Write:
    # (px1*o1 - px2*o2, py1*o1 - py2*o2) = (dx2*s - dx1*t, dy2*s - dy1*t)
    # => [ -dx1  dx2 ] [t] = [px1*o1 - px2*o2]
    #    [ -dy1  dy2 ] [s]   [py1*o1 - py2*o2]
    #
    # det = (-dx1)*dy2 - (-dy1)*dx2 = -dx1*dy2 + dy1*dx2 = cross(d1,d2)
    det = dx2 * dy1 - dy2 * dx1
    if abs(det) < 1e-6:
        raise ValueError("Bearings are too parallel; cannot build grid.")

    invA = 1.0 / det

    # generate nodes
    node_id = {}
    nodes_by_i1 = {}  # i1 index -> list of (i2_index, node_key)
    nodes_by_i2 = {}  # i2 index -> list of (i1_index, node_key)

    def key_xy(x, y):
        return (round(x, snap_decimals), round(y, snap_decimals))

    for a_idx, o1 in enumerate(offs1_list):
        for b_idx, o2 in enumerate(offs2_list):
            rx = px1 * o1 - px2 * o2
            ry = py1 * o1 - py2 * o2

            # Solve for t (we don't really need s)
            # t = ( rx*dy2 - ry*dx2 ) / det
            t = (rx * dy2 - ry * dx2) * invA

            x = cx + px1 * o1 + dx1 * t
            y = cy + py1 * o1 + dy1 * t

            if not poly_m.contains(Point(x, y)):
                continue

            k = key_xy(x, y)
            if k not in node_id:
                node_id[k] = len(node_id)

            nid = node_id[k]
            nodes_by_i1.setdefault(a_idx, []).append((b_idx, k))
            nodes_by_i2.setdefault(b_idx, []).append((a_idx, k))

    # build graph + edges between adjacent grid points along each family
    G = nx.Graph()
    for k, nid in node_id.items():
        G.add_node(nid, x=float(k[0]), y=float(k[1]))

    def add_edge(k1, k2):
        u = node_id[k1]
        v = node_id[k2]
        if u == v:
            return
        x1, y1 = k1
        x2, y2 = k2
        d = math.hypot(x2 - x1, y2 - y1)
        if d <= 0:
            return
        G.add_edge(u, v, length=float(d), weight=float(d), highway=highway)

    # connect neighbors along i1 (varying b_idx)
    for a_idx, lst in nodes_by_i1.items():
        lst.sort(key=lambda t: t[0])
        for (b0, k0), (b1, k1) in zip(lst, lst[1:]):
            add_edge(k0, k1)

    # connect neighbors along i2 (varying a_idx)
    for b_idx, lst in nodes_by_i2.items():
        lst.sort(key=lambda t: t[0])
        for (a0, k0), (a1, k1) in zip(lst, lst[1:]):
            add_edge(k0, k1)

    return G


# ------------------------------------------------------------
# 3) Buildings / demand (fast)
# ------------------------------------------------------------
def generate_buildings_and_demand_fast(
    poly_m: Polygon,
    inv_transformer,
    n_buildings: int = 250,
    seed: int = 42,
    building_halfsize_m: float = 10.0,
    pop_range=(30, 180),
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

    tries = 0
    while len(buildings_m) < n_buildings and tries < n_buildings * 80:
        tries += 1
        cx = rng.uniform(minx, maxx)
        cy = rng.uniform(miny, maxy)
        b = box(cx - building_halfsize_m, cy - building_halfsize_m,
                cx + building_halfsize_m, cy + building_halfsize_m)
        if developable.contains(b):
            pop = float(rng.randint(pop_range[0], pop_range[1]))
            buildings_m.append(b)

            x_m, y_m = float(b.centroid.x), float(b.centroid.y)
            lon, lat = inv_transformer.transform(x_m, y_m)  # lon,lat
            demand_wgs84.append((float(lat), float(lon), pop))
            demand_m.append((float(y_m), float(x_m), pop))

    buildings_wgs84 = [shp_transform(lambda x, y: inv_transformer.transform(x, y), b) for b in buildings_m]
    return buildings_wgs84, demand_wgs84, demand_m


# ------------------------------------------------------------
# 4) Whole synthetic generator (FAST)
# ------------------------------------------------------------
def generate_synthetic_neighborhood_citylike_FAST(
    G_city_wgs84,
    polygon_wgs84: Polygon,
    spacing_m: float = 120.0,
    style: str = "grid-like",        # "grid-like" (fastest). ("organic" not included in this fast version)
    seed: int = 42,
    sample_buffer_m: float = 800.0,
    n_buildings: int = 250,
    pop_range=(30, 180),
):
    """
    FAST city-like synthetic neighborhood:
    - learns dominant bearings near polygon from real city edges (fast)
    - generates a bearing-aligned grid graph (fast)
    - creates demand/buildings
    """
    if style.lower() not in ("grid", "grid-like", "gridlike"):
        raise ValueError("This FAST version supports only 'grid-like'. (I can add organic, but it will be slower.)")

    # Learn bearings + get UTM CRS choice
    bearings, utm_crs = dominant_bearings_near_polygon_fast(
        G_city_wgs84, polygon_wgs84,
        sample_buffer_m=sample_buffer_m,
        bin_deg=10.0,
        max_bearings=6,
    )

    # Project polygon (same UTM as chosen by centroid)
    poly_m, fwd, inv, utm_crs2 = project_polygon_to_utm(polygon_wgs84)

    # Choose b1 = most common, b2 = most orthogonal among top bearings
    b1 = float(bearings[0])
    b2 = None
    best = -1.0
    for b in bearings[1:]:
        delta = abs(((b - b1 + 90) % 180) - 90)  # 0 => orthogonal
        score = 90 - delta
        if score > best:
            best = score
            b2 = float(b)
    if b2 is None:
        b2 = (b1 + 90.0) % 180.0

    # Build street graph analytically (very fast)
    G_syn_m = build_grid_graph_inside_polygon_fast(
        poly_m=poly_m,
        b1_deg=b1,
        b2_deg=b2,
        spacing_m=float(spacing_m),
        snap_decimals=1,
        highway="residential",
    )

    # (Optional) create WGS84 street segments for folium by converting graph edges to LineStrings
    streets_wgs84 = []
    for u, v, d in G_syn_m.edges(data=True):
        x1, y1 = float(G_syn_m.nodes[u]["x"]), float(G_syn_m.nodes[u]["y"])
        x2, y2 = float(G_syn_m.nodes[v]["x"]), float(G_syn_m.nodes[v]["y"])
        lon1, lat1 = inv.transform(x1, y1)
        lon2, lat2 = inv.transform(x2, y2)
        streets_wgs84.append(((lat1, lon1), (lat2, lon2)))  # simple segment tuple

    # Buildings + demand
    buildings_wgs84, demand_wgs84, demand_m = generate_buildings_and_demand_fast(
        poly_m=poly_m,
        inv_transformer=inv,
        n_buildings=n_buildings,
        seed=seed,
        building_halfsize_m=10.0,
        pop_range=pop_range,
        shrink_m=20.0,
    )

    return {
        "graph": G_syn_m,          # meters (UTM)
        "streets": streets_wgs84,  # WGS84 as list of ((lat,lon),(lat,lon)) segments (fast & folium-friendly)
        "buildings": buildings_wgs84,
        "demand": demand_wgs84,    # (lat,lon,pop)
        "demand_m": demand_m,      # (y_m,x_m,pop)
        "transformer": inv,        # UTM -> WGS84
        "utm_crs": utm_crs2,
        "dominant_bearings": bearings,
        "chosen_bearings": (b1, b2),
    }


# ------------------------------------------------------------
# Example usage
# ------------------------------------------------------------
if __name__ == "__main__":
    from shapely.geometry import Polygon

    place = "Plovdiv, Bulgaria"
    print(f"Loading city {place}...")
    G_city = ox.graph_from_place(place, network_type="walk", simplify=True)
    print("City loaded!")

    # Replace with user-drawn polygon
    poly = Polygon([
        (24.740, 42.155),
        (24.760, 42.155),
        (24.760, 42.170),
        (24.740, 42.170),
        (24.740, 42.155),
    ])

    print("Generating synthetic neighborhood FAST...")
    syn = generate_synthetic_neighborhood_citylike_FAST(
        G_city_wgs84=G_city,
        polygon_wgs84=poly,
        spacing_m=120,
        style="grid-like",
        seed=42,
        sample_buffer_m=800,
        n_buildings=250,
    )

    print("Dominant bearings:", syn["dominant_bearings"][:6])
    print("Chosen bearings:", syn["chosen_bearings"])
    print("Synthetic nodes/edges:", syn["graph"].number_of_nodes(), syn["graph"].number_of_edges())
    print("Demand points:", len(syn["demand"]))
