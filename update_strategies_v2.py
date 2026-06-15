#!/usr/bin/env python3
"""Update crypto_bot.py and render.yaml with new auto-optimized strategies from 4H optimizer."""

import re
import pickle

# Load qualified strategies
with open('data/qualified_strategies.pkl', 'rb') as f:
    qualified = pickle.load(f)

# Read crypto_bot.py
with open('crypto_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# Build new strategy entries
# ============================================================

new_default_entries = []
new_dict_entries = []
new_auto_names = []

for i, (rank, r) in enumerate(qualified, 1):
    entry = r['entry']
    exit = r['exit']
    
    delay_bars = entry['delay_bars']
    max_rank = entry['max_entry_rank']
    min_change = entry['min_entry_change']
    max_change = entry['max_entry_change']
    require_green = entry['require_green_confirm']
    max_upper_wick = entry['max_upper_wick_pct']
    reclaim = entry['reclaim_entry_price']
    min_vol_ratio = entry['min_vol_ratio']
    
    sl_pct = exit['sl_pct']
    be_after = exit['breakeven_after_pct']
    trail_start = exit['trail_start_pct']
    trail_giveback = exit['trail_giveback_pct']
    time_stop = exit['time_stop_bars']
    
    vol_str = f"_vol{int(min_vol_ratio*10):02d}" if min_vol_ratio else ""
    dur_str = "_dur55"
    
    name = f"auto_top{i}_4h_d{delay_bars}_r{max_rank}_chg{min_change}-{max_change}_greenuw{max_upper_wick:.1f}{vol_str}{dur_str}_sl{sl_pct}_be{be_after}_tr{trail_start}x{trail_giveback}_t{time_stop}"
    new_auto_names.append(name)
    
    # For _DEFAULT_MICRO_ACTIVE tuple (with trailing comma)
    new_default_entries.append(f'    "{name},"')
    
    # For MICRO_TOP10_OPTIMIZED_STRATEGIES dict
    dict_entry = f'''    "{name}": {{
        "version": "auto_top{i}_4h",
        "entry_delay_bars": {delay_bars},
        "max_rank": {max_rank},
        "min_change_1h_pct": {float(min_change)},
        "max_change_1h_pct": {float(max_change)},
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": {str(reclaim).lower()},
        "require_green_confirm": {str(require_green).lower()},
        "max_upper_wick_pct": {max_upper_wick},
        "min_volume_ratio": {float(min_vol_ratio or 0)},
        "reclaim_entry_price": {str(reclaim).lower()},
        "shadow_only": False,
        "stop_loss_pct": {sl_pct},
        "breakeven_after_pct": {be_after},
        "trailing_start_pct": {trail_start},
        "trailing_giveback_pct": {trail_giveback},
        "time_stop_bars": {time_stop},
    }},'''
    new_dict_entries.append(dict_entry)

new_default_text = "\n".join(new_default_entries)
new_dict_text = "\n".join(new_dict_entries)

# ============================================================
# 1. Update _DEFAULT_MICRO_ACTIVE tuple (lines 31-38)
# ============================================================

# Find the tuple start and end
tuple_start = content.find('_DEFAULT_MICRO_ACTIVE = (')
if tuple_start == -1:
    raise ValueError("Could not find _DEFAULT_MICRO_ACTIVE")

tuple_end = content.find(')', tuple_start) + 1
if tuple_end == 0:
    raise ValueError("Could not find end of _DEFAULT_MICRO_ACTIVE tuple")

# Replace the auto_top lines (3 of them) with new ones
# Keep the non-auto entries (strategy4_1, strategy20, top5dplus)
old_tuple = content[tuple_start:tuple_end]

# Find where the old auto_top entries end (after the 3rd one)
auto_end_marker = 'uw08_sl1.5_be0.6_tr0.9x0.4_t18,"'
auto_end_idx = content.find(auto_end_marker, tuple_start)
if auto_end_idx == -1:
    raise ValueError("Could not find end of old auto_top entries in _DEFAULT_MICRO_ACTIVE")

# The next line after that should be the first non-auto entry
# Find the newline after auto_end_marker
next_line_start = content.find('\n', auto_end_idx) + 1

# Build new tuple content: new auto entries + existing non-auto entries
non_auto_part = content[next_line_start:tuple_end].strip()
new_tuple = "_DEFAULT_MICRO_ACTIVE = (\n" + new_default_text + ",\n" + non_auto_part

content = content[:tuple_start] + new_tuple + content[tuple_end:]

# ============================================================
# 2. Update MICRO_TOP10_OPTIMIZED_STRATEGIES dict
# ============================================================

# Find the dict start
dict_start_marker = 'MICRO_TOP10_OPTIMIZED_STRATEGIES = {'
dict_start_idx = content.find(dict_start_marker)
if dict_start_idx == -1:
    raise ValueError("Could not find MICRO_TOP10_OPTIMIZED_STRATEGIES")

# Find the first old auto_top entry
first_auto_key = '"auto_top1_4h_d2_r3_chg3-10_green_reclaim_uw08_sl1.5_be0.6_tr0.9x0.4_t8": {'
first_auto_idx = content.find(first_auto_key, dict_start_idx)
if first_auto_idx == -1:
    raise ValueError("Could not find first auto_top entry in MICRO_TOP10_OPTIMIZED_STRATEGIES")

# Find the end of the third old auto_top entry (before strategy4_1 comment)
strategy41_marker = '# === Strategy 4.1 (production backtest positive) ==='
strategy41_idx = content.find(strategy41_marker, first_auto_idx)
if strategy41_idx == -1:
    raise ValueError("Could not find Strategy 4.1 marker")

# Find the last "    },\n" before strategy41_marker
last_auto_end = content.rfind('    },\n', first_auto_idx, strategy41_idx)
if last_auto_end == -1:
    raise ValueError("Could not find end of old auto_top entries in dict")

# Replace from first_auto_idx to last_auto_end
new_content = content[:first_auto_idx] + new_dict_text + "\n" + content[last_auto_end+6:]

# Now update the rest of the string references in new_content
content = new_content

# ============================================================
# 3. Update microActiveStrategies in CONFIG
# ============================================================

# Find the microActiveStrategies line
pattern = r'("microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*[^)]+\))'
match = re.search(pattern, content)
if not match:
    raise ValueError("Could not find microActiveStrategies in CONFIG")

line_start = match.start()
old_line = match.group(0)

# Build new strategies list: keep non-auto from deployed, add new auto
with open('render.yaml', 'r', encoding='utf-8') as f:
    render_content = f.read()

render_lines = render_content.split('\n')
deployed_strategies = ""
for line in render_lines:
    if 'CRYPTO_MICRO_ACTIVE_STRATEGIES' in line and 'value:' in line:
        value_start = line.index('value:') + len('value:')
        deployed_strategies = line[value_start:].strip()
        break

if not deployed_strategies:
    # Fallback: key on one line, value on next
    for i, line in enumerate(render_lines := render_content.split('\n')):
        if 'CRYPTO_MICRO_ACTIVE_STRATEGIES' in line and i + 1 < len(render_lines):
            next_line = render_lines[i + 1]
            if 'value:' in next_line:
                value_start = next_line.index('value:') + len('value:')
                deployed_strategies = next_line[value_start:].strip()
                break

if not deployed_strategies:
    raise ValueError("Could not find CRYPTO_MICRO_ACTIVE_STRATEGIES in render.yaml")

existing = deployed_strategies.split(",")
filtered = [s for s in existing if not s.startswith("auto_top")]
new_strategies_list = filtered + new_auto_names
new_strategies_str = ",".join(new_strategies_list)

# Build new line
new_line = f'    "microActiveStrategies": _csv_env("CRYPTO_MICRO_ACTIVE_STRATEGIES", "{new_strategies_str}"),'
content = content[:line_start] + new_line + content[match.end():]

# ============================================================
# 4. Update render.yaml
# ============================================================

with open('render.yaml', 'r', encoding='utf-8') as f:
    render_content = f.read()

render_lines = render_content.split('\n')
for i, line in enumerate(render_lines):
    if 'CRYPTO_MICRO_ACTIVE_STRATEGIES' in line and i + 1 < len(render_lines):
        next_line = render_lines[i + 1]
        if 'value:' in next_line:
            indent = next_line[:next_line.index('value:')]
            render_lines[i + 1] = f"{indent}value: {new_strategies_str}"
            break

with open('render.yaml', 'w', encoding='utf-8') as f:
    f.write('\n'.join(render_lines))

# ============================================================
# 5. Write back crypto_bot.py
# ============================================================

with open('crypto_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated crypto_bot.py successfully")
print("Updated render.yaml successfully")
print(f"Added {len(new_auto_names)} new auto strategies:")
for name in new_auto_names:
    print(f"  {name}")
print(f"\nTotal active strategies: {len(new_strategies_list)}")
print(f"Non-auto (kept): {len(filtered)}")