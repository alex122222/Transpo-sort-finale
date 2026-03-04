import json
import re
with open('templates/generated/Plovdiv_Bulgaria_coverage.html', 'r', encoding='utf-8') as f:
    text = f.read()
matches = re.findall(r'L.circleMarker\(\s*\[(.*?),\s*(.*?)\]', text)
print(f"First 3 coords: {matches[:3]}")
