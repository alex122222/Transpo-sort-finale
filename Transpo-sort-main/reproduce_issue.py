import json
import os
from shapely.geometry import shape, Polygon
from synthetic_neighborhood import generate_synthetic_neighborhood
from optimizer import place_new_stops
from map_output import build_map

def reproduce_issue():
    print("Reproducing Invisible Map Issue...")
    
    # Simulate a user-drawn polygon (Large box in Central Park area)
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
        print("Parsing Polygon...")
        polygon = shape(custom_geo["geometry"])
        print(f"Polygon Bounds: {polygon.bounds}")
        
        # Generator
        print("\n--- Generating Neighborhood ---")
        synth = generate_synthetic_neighborhood(polygon, layout='grid')
        
        print(f"Streets: {len(synth['streets'])}")
        print(f"Buildings: {len(synth['buildings'])}")
        
        # Optimizer
        print("\n--- Optimizing Stops ---")
        new_stops_m = place_new_stops(synth["graph"], synth["demand_m"], k=5)
        
        # Transform
        inv = synth["transformer"]
        new_stops_wgs84 = []
        for y, x in new_stops_m:
             lon, lat = inv.transform(x, y)
             new_stops_wgs84.append((lat, lon))
        
        print(f"New Stops (WGS84): {new_stops_wgs84}")

        # Build Map
        print("\n--- Building Map ---")
        center = polygon.centroid.y, polygon.centroid.x
        print(f"Map Center: {center}")
        
        output_file = "reproduce_map.html"
        
        build_map(
            center=center,
            city_polygon=None,
            neighborhood_polygon=polygon,
            streets=synth["streets"],
            buildings=synth["buildings"],
            demand=synth["demand"],
            new_stops=new_stops_wgs84,
            filename=output_file
        )
        print(f"Map saved to {output_file}")
        
        # Check file content
        with open(output_file, 'r') as f:
            content = f.read()
            if "folium.Map" in content:
                print("folium.Map found in output.")
            if f"[{center[0]}, {center[1]}]" in content:
                print("Center coordinates found in output.")
            else:
                print("WARNING: Center coordinates NOT found in output exactly? encoding might vary.")
                
    except Exception as e:
        print(f"\nCRASHED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce_issue()
