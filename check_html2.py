with open('templates/generated/Plovdiv_Bulgaria_coverage.html', 'r', encoding='utf-8') as f: text = f.read()
res = f"m={text.lower().count('marker')}, c={text.lower().count('circle')}, ps={text.lower().count('proposed stops')}"
with open('check.txt', 'w') as f: f.write(res)
