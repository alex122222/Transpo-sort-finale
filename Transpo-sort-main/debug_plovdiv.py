import requests
import json
from shapely.geometry import box

# Plovdiv box: 42.14, 24.74
poly = box(24.740, 42.140, 24.750, 42.150)
geo = poly.__geo_interface__

url = "http://127.0.0.1:5000/optimize"
payload = {
    "k": 5,
    "seed": 42,
    "layout": "grid",
    "stop_mode": "auto",
    "polygon": geo
}

res = requests.post(url, json=payload)
print(res.status_code)
print(res.text)
