#!/usr/bin/env python3
"""Update crypto_bot.py with new auto-optimized strategies from 4H optimizer."""

import re
import pickle

# Load qualified strategies
with open('data/qualified_strategies.pkl', 'rb') as f:
    qualified = pickle.load(f)

# Read crypto_bot.py
with open('crypto_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# 1. Update MICRO_TOP10_OPTIMIZED_STRATEGIES
# ============================================================

# Find where old auto_top entries end (before Strategy 4.1 marker)
marker_41 = "# === Strategy 4.1 (production backtest positive) ==="
marker_41_idx = content.find(marker_41)
if marker_41_idx == -1:
    raise ValueError("Could not find Strategy 4.1 marker")

# Find the start of first auto_top entry
auto_start_idx = content.find('"auto_top1_4h"')
if auto_start_idx == -1:
    raise ValueError("Could not find auto_top1")

# Find the end of auto_top entries (last "    },\n" before marker_41)
last_auto_end = content.rfind("    },\n", 0, marker_41_idx)
if last_auto_end == -1:
    raise ValueError("Could not find end of auto_top entries")

# Build new auto strategies
new_auto_strategies = []
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
    min_atr = entry.get('min_atr_proxy')
    max_atr = entry.get('max_atr_proxy')
    atr_str = f"_atr{int(min_atr)}-{int(max_atr)}" if min_atr is not None and max_atr is not None else ""
    
    name = f"auto_top{i}_4h_d{delay_bars}_r{max_rank}_chg{min_change}-{max_change}_greenuw{max_upper_wick:.1f}{vol_str}{dur_str}{atr_str}_sl{sl_pct}_be{be_after}_tr{trail_start}x{trail_giveback}_t{time_stop}"
    
    strategy = f'''    "{name}": {{
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
        "min_atr_proxy": {min_atr},
        "max_atr_proxy": {max_atr},
        "stop_loss_pct": {sl_pct},
        "breakeven_after_pct": {be_after},
        "trailing_start_pct": {trail_start},
        "trailing_giveback_pct": {trail_giveback},
        "time_stop_bars": {time_stop},
    }},'''
    new_auto_strategies.append(strategy)

new_auto_text = "\n".join(new_auto_strategies)

# Replace from auto_top1 to just before Strategy 4.1
new_content = content[:auto_start_idx] + new_auto_text + "\n" + content[last_auto_end+6:]

# ============================================================
# 2. Update CRYPTO_MICRO_ACTIVE_STRATEGIES in CONFIG
# ============================================================

# Find the microActiveStrategies line - it may have _DEFAULT_MICRO_ACTIVE or a string default
# Line looks like: "microActiveStrategies": _csv_env("CRYPTO_MICRO_ACTIVE_STRATEGIES", _DEFAULT_MICRO_ACTIVE),
# Or: "microActiveStrategies": _csv_env("CRYPTO_MICRO_ACTIVE_STRATEGIES", "strategy1,strategy2,..."),
pattern = r'("microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*[^)]+\))'
match = re.search(pattern, new_content)
if not match:
    raise ValueError("Could not find microActiveStrategies in CONFIG")

# Get the full line
old_line = match.group(0)
line_start = match.start()

# Parse the existing strategies from render.yaml (source of truth for deployed)
with open('render.yaml', 'r', encoding='utf-8') as f:
    render_content = f.read()

render_lines = render_content.split('\n')
deployed_strategies = ""
for line in render_lines:
    if 'CRYPTO_MICRO_ACTIVE_STRATEGIES' in line and 'value:' in line:
        # Extract value after "value: " - value is NOT quoted in render.yaml
        value_start = line.index('value:') + len('value:')
        deployed_strategies = line[value_start:].strip()
        break

if not deployed_strategies:
    # Fallback: try to find in the line with key:
    for line in render_lines:
        if 'CRYPTO_MICRO_ACTIVE_STRATEGIES' in line:
            # Next line should have value:
            idx = render_lines.index(line)
            if idx + 1 < len(render_lines):
                next_line = render_lines[idx + 1]
                if 'value:' in next_line:
                    value_start = next_line.index('value:') + len('value:')
                    deployed_strategies = next_line[value_start:].strip()
                    break

if not deployed_strategies:
    raise ValueError("Could not find CRYPTO_MICRO_ACTIVE_STRATEGIES value in render.yaml")

# Parse existing strategies
existing = deployed_strategies.split(",")

# Remove old auto_top strategies
filtered = [s for s in existing if not s.startswith("auto_top")]

# Add new auto strategies at the end
new_auto_names = []
for i, (rank, r) in enumerate(qualified, 1):
    entry = r['entry']
    exit = r['exit']
    delay_bars = entry['delay_bars']
    max_rank = entry['max_entry_rank']
    min_change = entry['min_entry_change']
    max_change = entry['max_entry_change']
    max_upper_wick = entry['max_upper_wick_pct']
    min_vol_ratio = entry['min_vol_ratio']
    sl_pct = exit['sl_pct']
    be_after = exit['breakeven_after_pct']
    trail_start = exit['trail_start_pct']
    trail_giveback = exit['trail_giveback_pct']
    time_stop = exit['time_stop_bars']
    
    vol_str = f"_vol{int(min_vol_ratio*10):02d}" if min_vol_ratio else ""
    dur_str = "_dur55"
    min_atr = entry.get('min_atr_proxy')
    max_atr = entry.get('max_atr_proxy')
    atr_str = f"_atr{int(min_atr)}-{int(max_atr)}" if min_atr is not None and max_atr is not None else ""
    
    name = f"auto_top{i}_4h_d{delay_bars}_r{max_rank}_chg{min_change}-{max_change}_greenuw{max_upper_wick:.1f}{vol_str}{dur_str}{atr_str}_sl{sl_pct}_be{be_after}_tr{trail_start}x{trail_giveback}_t{time_stop}"
    new_auto_names.append(name)

new_strategies_list = filtered + new_auto_names
new_strategies_str = ",".join(new_strategies_list)

# Build new line for crypto_bot.py - use the new strategies as the default
# ============================================================
# 3. Update render.yaml
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
render_content = '\n'.join(render_lines)
with open('render.yaml', 'w', encoding='utf-8') as f:
    f.write(render_content)

print("Updated render.yaml successfully")
# ============================================================
# 4. Write back crypto_bot.py
# ============================================================
with open('crypto_bot.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Updated crypto_bot.py successfully")
print("Updated render.yaml successfully")
print(f"Added {len(new_auto_names)} new auto strategies:")
for name in new_auto_names:
    print(f"  {name}")
print(f"\nTotal active strategies: {len(new_strategies_list)}")
print(f"Non-auto (kept): {len(filtered)}")