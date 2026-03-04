with open('cart.py', 'r', encoding='utf-8') as f:
    text = f.read()
text = text.replace('✅', '[OK]').replace('⚠️', '[WARN]')
with open('cart.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Stripped emojis successfully.')
