import requests
import json
import sys

def test_optimize():
    url = "http://127.0.0.1:5000/optimize"
    
    # Manhattan central park ish polygon just for testing 
    # to avoid having to draw it
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-73.97, 40.78],
            [-73.98, 40.78],
            [-73.98, 40.79],
            [-73.97, 40.79],
            [-73.97, 40.78]
        ]]
    }
    
    payload = {
        "k": 3,
        "seed": 42,
        "layout": "grid",
        "polygon": polygon
    }
    
    try:
        r = requests.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        
        print(f"Status: {data.get('status')}")
        stops = data.get('stops', {})
        print(json.dumps(stops, indent=2))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_optimize()
