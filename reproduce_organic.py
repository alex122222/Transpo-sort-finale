import json
import os
from shapely.geometry import shape, Polygon
from synthetic_neighborhood import generate_synthetic_neighborhood

def reproduce_organic():
    print("Reproducing Organic Layout Issue...")
    
    custom_geo = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-73.98, 40.76],
                [-73.98, 40.78],
                [-73.96, 40.78],
                [-73.96, 40.76],
                [-73.98, 40.76]
            ]]
        }
    }
    
    try:
        polygon = shape(custom_geo["geometry"])
        print("\n--- Generating Neighborhood (Organic) ---")
        synth = generate_synthetic_neighborhood(polygon, layout='organic')
        print("Success!")
    except Exception as e:
        print(f"\nCRASHED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce_organic()
