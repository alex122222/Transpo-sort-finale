import networkx as nx
import numpy as np
from shapely.geometry import Point, box, Polygon
import osmnx as ox

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
    connector_k: int = 12,
    max_attach_m: float = 1500.0, # Increased for test
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

    connector_pts = _boundary_points_even(poly_wgs84, connector_k)

    for i, p in enumerate(connector_pts):
        lon = float(p.x)
        lat = float(p.y)
        try:
            city_n = ox.distance.nearest_nodes(G_city, X=lon, Y=lat)
        except Exception:
            continue

        city_lon = float(G_city.nodes[city_n]["x"])
        city_lat = float(G_city.nodes[city_n]["y"])

        if hasattr(ox.distance, 'great_circle_vec'):
            dist_to_city_m = float(ox.distance.great_circle_vec(lat, lon, city_lat, city_lon))
        elif hasattr(ox.distance, 'great_circle'):
            dist_to_city_m = float(ox.distance.great_circle(lat, lon, city_lat, city_lon))
        else:
            dist_to_city_m = 0.0

        if dist_to_city_m > float(max_attach_m):
            continue

        syn_n = nearest_syn_node(lon, lat)

        conn_n = (conn_prefix, i)
        G_out.add_node(conn_n, x=lon, y=lat, _src="connector")

        gate_len = float(min(10.0, max(1.0, dist_to_city_m * 0.1)))

        if isinstance(G_out, nx.MultiDiGraph) or isinstance(G_out, nx.MultiGraph):
            G_out.add_edge(conn_n, syn_n, length=gate_len, _src="connector")
            if add_bidirectional:
                G_out.add_edge(syn_n, conn_n, length=gate_len, _src="connector")

            G_out.add_edge(conn_n, city_n, length=dist_to_city_m, _src="connector")
            if add_bidirectional:
                G_out.add_edge(city_n, conn_n, length=dist_to_city_m, _src="connector")
        else:
            G_out.add_edge(conn_n, syn_n, length=gate_len, _src="connector")
            G_out.add_edge(conn_n, city_n, length=dist_to_city_m, _src="connector")

    return G_out

class DummyTransformer:
    def transform(self, x, y):
        # convert meters back to roughly degrees (approx in NY)
        lon = -74.0 + (x / 85000.0)
        lat = 40.7 + (y / 111000.0)
        return lon, lat

if __name__ == "__main__":
    print("Setting up dummy test...")
    # 1) Dummy City Graph
    G_city = nx.MultiDiGraph()
    G_city.add_node(1, x=-74.0, y=40.7)
    G_city.add_node(2, x=-73.99, y=40.71)
    G_city.add_edge(1, 2, length=100.0)
    G_city.add_edge(2, 1, length=100.0)
    
    # 2) Dummy Synthetic Graph
    G_syn_m = nx.Graph()
    G_syn_m.add_node(10, x=500.0, y=500.0)
    G_syn_m.add_node(20, x=600.0, y=600.0)
    G_syn_m.add_edge(10, 20, length=141.0)
    
    # 3) Dummy Polygon
    poly = box(-74.005, 40.705, -73.995, 40.715)
    
    inv = DummyTransformer()
    
    print("Merging...")
    G_all = merge_synthetic_neighborhood_into_osmnx_city(
        G_city=G_city,
        G_syn_m=G_syn_m,
        poly_wgs84=poly,
        inv_transformer=inv,
        connector_k=4,
        max_attach_m=50000.0,
    )
    
    print("Merged nodes:", len(G_all.nodes))
    for n, d in G_all.nodes(data=True):
        print(" ", n, d)
        
    print("Merged edges:", len(G_all.edges))
    for u, v, k, d in G_all.edges(keys=True, data=True):
        print(" ", u, "->", v, d)
    
    print("SUCCESS!")
