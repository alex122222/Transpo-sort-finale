import json
from shapely.geometry import shape
from synthetic_neighborhood import generate_synthetic_neighborhood
from optimizer import place_new_stops
from map_output import build_map

# ---- Load example polygon ----
with open("data/example_neighborhood.geojson") as f:
    geo = json.load(f)

polygon = shape(geo["features"][0]["geometry"])

# ---- Generate synthetic neighborhood ----
synth = generate_synthetic_neighborhood(polygon)

# ---- Optimize stops ----
new_stops_m = place_new_stops(synth["graph"], synth["demand_m"], k=6)

# ---- Convert & Build map ----
inv = synth["transformer"]
new_stops = []
for y, x in new_stops_m:
    lon, lat = inv.transform(x, y)
    new_stops.append((lat, lon))
    
print(f"Final stops count: {len(new_stops)}")
print(f"Final stops sample lat/lon: {new_stops[:5]}")

center = polygon.centroid.y, polygon.centroid.x

build_map(
    center=center,
    city_polygon=None,
    neighborhood_polygon=polygon,
    streets=synth["streets"],
    buildings=synth["buildings"],
    demand=synth["demand"],
    new_stops=new_stops,
)

print("✅ Done. Open outputs/result.html")
