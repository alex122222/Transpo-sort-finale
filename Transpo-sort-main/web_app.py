from flask import Flask, render_template, send_file, request
import json
import os
from shapely import affinity
from shapely.geometry import shape, LineString
from synthetic_neighborhood import generate_synthetic_neighborhood, merge_synthetic_neighborhood_into_osmnx_city
from optimizer import place_new_stops
from map_output import build_map
from cart import run_cart_optimization

app = Flask(__name__)

# Ensure outputs directory exists
os.makedirs("outputs", exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/neighborhood')
def neighborhood():
    return render_template('dashboard.html')

@app.route('/city_coverage')
def city_coverage():
    return render_template('city_coverage.html')

@app.route('/optimize', methods=['POST'])
def optimize():
    try:
        # Get parameters from JSON or form
        custom_polygon = None
        if request.is_json:
            data = request.get_json()
            k = int(data.get('k', 12))
            current_seed = int(data.get('seed', 42))
            layout = data.get('layout', 'grid')
            size_factor = float(data.get('size', 1.0))
            if 'polygon' in data:
                custom_polygon = shape(data['polygon'])
        else:
            k = int(request.form.get('k', 12))
            current_seed = 42
            layout = 'grid'
            size_factor = 1.0

        # ---- Load or use custom polygon ----
        if custom_polygon:
            polygon = custom_polygon
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_path = os.path.join(base_dir, "data", "example_neighborhood.geojson")
            with open(data_path) as f:
                geo = json.load(f)
            polygon = shape(geo["features"][0]["geometry"])
        
        # Scale polygon based on size input (center scaling - only for default)
        if not custom_polygon and size_factor != 1.0:
            polygon = affinity.scale(polygon, xfact=size_factor, yfact=size_factor, origin='center')
        
        print(f"Polygon Bounds: {polygon.bounds}")
        
        # ---- Safety Check: Limit area size to prevent server hang ----
        # Project center to calculate approximate area in meters if needed, 
        # but shapely area in degrees * 111^2 is a good proxy for Manhattan latitudes.
        # We'll use the projected area from synth_neighborhood or just check here.
        # Max area: 25 sq km (approx 0.0025 sq degrees)
        if polygon.area > 0.0025:
            return {"status": "error", "error": "Area too large! Please draw a smaller section (max ~25 sq km)."}, 400
        
        # ---- Fetch Surrounding City Graph ----
        import osmnx as ox
        G_city = None
        try:
            print("Fetching city graph for logical orientation...")
            city_poly = polygon.buffer(0.008) # About 800m WGS84 buffer
            G_city = ox.graph_from_polygon(city_poly, network_type='all')
        except Exception as e:
            print(f"Failed to fetch initial city graph: {e}")

        # ---- Generate synthetic neighborhood ----
        synth = generate_synthetic_neighborhood(
            polygon, 
            seed=current_seed,
            layout=layout,
            G_city=G_city
        )
        
        print(f"Generated {len(synth['streets'])} streets, {len(synth['buildings'])} buildings")
        
        if len(synth['streets']) == 0:
            return {"status": "error", "error": "The drawn area is too small to generate a neighborhood. Please draw a larger polygon."}, 400

        # ---- Optimize stops ----
        new_stops_m = place_new_stops(synth["graph"], synth["demand_m"], k=k)
        
        # ---- Calculate Stats ----
        # 1. Avg walk distance BEFORE (nearest existing stop? assume none or center)
        # For simplicity, let's just calculate Avg Walk Distance AFTER optimization
        import networkx as nx
        import numpy as np
        
        G = synth["graph"]
        demand_nodes = [n for n in G.nodes if G.nodes[n].get("demand", 0) > 0] # wait, demand is not in G nodes
        # demand is separate. let's map demand_m to nearest node
        
        # Actually, let's just use the Euclidean distance from demand_m to nearest stop_m
        # This is an approximation of walking distance but fast to compute for stats
        stops_arr = np.array(new_stops_m) # [[y, x]]
        demand_arr = np.array(synth["demand_m"]) # [[y, x, w]]
        
        total_w = np.sum(demand_arr[:, 2])
        total_weighted_dist = 0
        
        if len(stops_arr) > 0:
            for dy, dx, w in demand_arr:
                # dist to nearest stop
                dists = np.hypot(stops_arr[:, 0] - dy, stops_arr[:, 1] - dx)
                min_dist = np.min(dists)
                total_weighted_dist += min_dist * w
                
        avg_dist = round(total_weighted_dist / total_w, 1) if total_w > 0 else 0

        # ---- Convert & Build Map ----
        inv = synth["transformer"]
        new_stops_wgs84 = []
        for y, x in new_stops_m:
             # inv.transform with always_xy=True expects (x, y) and returns (lon, lat)
             lon, lat = inv.transform(x, y)
             new_stops_wgs84.append((lat, lon))
             
        print(f"Final stops count: {len(new_stops_wgs84)}")
        print(f"Final stops sample lat/lon: {new_stops_wgs84[:5]}")
        
        # ---- Fetch City Integration ----
        try:
            if G_city is None:
                print("Fetching city graph for integration...")
                city_poly = polygon.buffer(0.008) 
                G_city = ox.graph_from_polygon(city_poly, network_type='all')
                
            G_merged = merge_synthetic_neighborhood_into_osmnx_city(
                G_city=G_city,
                G_syn_m=synth["graph"],
                poly_wgs84=polygon,
                inv_transformer=synth["transformer"],
                connector_k=24,
                max_attach_m=600.0
            )
            
            # Extract connectors and city edges for visualization
            print("Appending connectors and city streets to output map...")
            for u, v, d in G_merged.edges(data=True):
                # We skip synthetic because it's already in synth["streets"]
                src = d.get("_src")
                if src == "connector":
                    lon1, lat1 = G_merged.nodes[u]["x"], G_merged.nodes[u]["y"]
                    lon2, lat2 = G_merged.nodes[v]["x"], G_merged.nodes[v]["y"]
                    synth["streets"].append(LineString([(lon1, lat1), (lon2, lat2)]))
                elif src != "synthetic" and src != "connector":
                    # It's an OSMnx city edge
                    if "geometry" in d:
                        synth["streets"].append(d["geometry"])
                    else:
                        lon1, lat1 = G_merged.nodes[u]["x"], G_merged.nodes[u]["y"]
                        lon2, lat2 = G_merged.nodes[v]["x"], G_merged.nodes[v]["y"]
                        synth["streets"].append(LineString([(lon1, lat1), (lon2, lat2)]))
                        
            print("City integration successful.")
        except Exception as e:
            print(f"City merge failed or skipped: {e}")
            import traceback
            traceback.print_exc()
        
        center = polygon.centroid.y, polygon.centroid.x
        
        # If AJAX request, return JSON data including GeoJSON features
        if request.is_json:
            # Prepare GeoJSON for frontend rendering
            streets_geojson = [s.__geo_interface__ for s in synth["streets"]]
            buildings_geojson = [b.__geo_interface__ for b in synth["buildings"]]
            stops_geojson = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [stop_lon, stop_lat]},
                        "properties": {"type": "bus_stop"}
                    } for stop_lat, stop_lon in new_stops_wgs84
                ]
            }
            print(f"Stops GeoJSON features: {len(stops_geojson['features'])}")
            if len(stops_geojson['features']) > 0:
                print(f"First stop coordinates: {stops_geojson['features'][0]['geometry']['coordinates']}")
            
            return {
                "status": "ok", 
                "avg_dist": avg_dist, 
                "streets": streets_geojson,
                "buildings": buildings_geojson,
                "stops": stops_geojson,
                "demand": synth["demand"],
                "center": [center[0], center[1]]
            }
            
        # Fallback for non-AJAX (mostly for debugging/legacy)
        build_map(
            center=center,
            city_polygon=None,
            neighborhood_polygon=polygon,
            streets=synth["streets"],
            buildings=synth["buildings"],
            demand=synth["demand"],
            new_stops=new_stops_wgs84,
            filename="templates/map.html"
        )
        return render_template('dashboard.html', avg_dist=avg_dist)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}, 500

@app.route('/map_view')
def map_view():
    return render_template('map.html')

@app.route('/generated_map/<path:filename>')
def serve_generated_map(filename):
    from flask import make_response, send_from_directory
    resp = make_response(send_from_directory("templates/generated", filename))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route('/run_city_coverage', methods=['POST'])
def run_city_coverage():
    try:
        data = request.get_json()
        place_query = data.get('place_query', "Plovdiv, Bulgaria")
        walk_distance_m = int(data.get('walk_distance_m', 600))
        min_stop_distance_m = int(data.get('min_stop_distance_m', 300))
        num_candidate_points = int(data.get('num_candidate_points', 180))
        
        # Run cart script integration
        map_url = run_cart_optimization(
            place_query=place_query, 
            walk_distance_m=walk_distance_m,
            min_stop_distance_m=min_stop_distance_m,
            num_candidate_points=num_candidate_points
        )
        
        return {"status": "ok", "map_url": map_url}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}, 500

if __name__ == '__main__':
    print("--- Transpo-Sort Web App v3.0 Loaded ---")
    app.run(debug=True)
