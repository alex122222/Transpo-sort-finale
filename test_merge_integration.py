from shapely.geometry import box
from synthetic_neighborhood import generate_synthetic_neighborhood, merge_synthetic_neighborhood_into_osmnx_city

p = box(-74.005, 40.705, -73.995, 40.715)
synth = generate_synthetic_neighborhood(p, seed=42)
print("Synthetic nodes:", len(synth["graph"].nodes))

city_poly = p.buffer(0.008)
import osmnx as ox
G_city = ox.graph_from_polygon(city_poly, network_type='all')
print("City nodes:", len(G_city.nodes))

G_merged = merge_synthetic_neighborhood_into_osmnx_city(
    G_city=G_city,
    G_syn_m=synth["graph"],
    poly_wgs84=p,
    inv_transformer=synth["transformer"],
    connector_k=24,
    max_attach_m=600.0
)
print("Merged nodes:", len(G_merged.nodes))

conn_edges = [d for u, v, d in G_merged.edges(data=True) if d.get("_src") == "connector"]
print("Connector edges:", len(conn_edges))
