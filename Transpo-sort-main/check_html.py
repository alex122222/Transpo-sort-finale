with open('templates/generated/Plovdiv_Bulgaria_coverage.html', 'r', encoding='utf-8') as f:
    text = f.read()
print(f"Occurrences of 'marker': {text.lower().count('marker')}")
print(f"Occurrences of 'circle': {text.lower().count('circle')}")
print(f"Occurrences of 'proposed stops': {text.lower().count('proposed stops')}")
