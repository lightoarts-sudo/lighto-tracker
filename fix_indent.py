# Fix indentation on line 90
with open('crypto_bot.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Line 90 is index 89
if not lines[89].startswith('    '):
    lines[89] = '    ' + lines[89]
    print("Fixed indentation on line 90")
else:
    print("Line 90 already has correct indentation")

with open('crypto_bot.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
