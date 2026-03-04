with open('templates/generated/Plovdiv_Bulgaria_coverage.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
with open('tail.txt', 'w', encoding='utf-8') as f:
    f.write(''.join(lines[-40:]))
