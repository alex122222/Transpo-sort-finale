lines = open('templates/generated/Plovdiv_Bulgaria_coverage.html', 'r', encoding='utf-8').readlines()
marker_lines = [i for i, l in enumerate(lines) if 'marker' in l.lower()]
res = []
if marker_lines:
    first = marker_lines[0]
    for i in range(max(0, first-5), min(len(lines), first+8)):
        res.append(f"{i}: {lines[i].strip()}")
with open('debug.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(res))
