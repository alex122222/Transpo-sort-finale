import json
from shapely.geometry import shape
from synthetic_neighborhood import generate_synthetic_neighborhood
from optimizer import place_new_stops
import os

def test_optimization_flow():
    # Mock loading data
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, "data", "example_neighborhood.geojson")
    
    with open(data_path) as f:
        geo = json.load(f)
    
    polygon = shape(geo["features"][0]["geometry"])
    
    print("Generating neighborhood...")
    synth = generate_synthetic_neighborhood(polygon)
    
    print("Checking demand_m existence...")
    if "demand_m" not in synth:
        print("FAIL: demand_m not found in synth output")
        return
        
    print("Running optimizer with demand_m...")
    try:
        new_stops_m = place_new_stops(synth["graph"], synth["demand_m"], k=6)
        print(f"Optimizer returned {len(new_stops_m)} stops (meters).")
    except ValueError as e:
        print(f"FAIL: Optimizer crashed: {e}")
        return

    print("Transforming stops back to WGS84...")
    inv = synth["transformer"]
    new_stops_wgs84 = []
    for y, x in new_stops_m:
            lon, lat = inv.transform(x, y)
            new_stops_wgs84.append((lat, lon))
            
    print(f"Transformed stops: {new_stops_wgs84}")
    print("SUCCESS: Flow completed without errors.")

if __name__ == "__main__":
    test_optimization_flow()
