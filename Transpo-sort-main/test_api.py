import urllib.request
import json
import sys

try:
    req = urllib.request.Request(
        'http://127.0.0.1:5000/optimize',
        data=b'{"k": 3, "seed": 42, "layout": "grid"}',
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())
        features = data['stops']['features']
        print(f"Number of stops: {len(features)}")
        if features:
            print("First stop:")
            print(json.dumps(features[0], indent=2))
except Exception as e:
    print(f"Error: {e}")
