import json
import re

# Load qualified strategies
import pickle
with open('data/qualified_strategies.pkl', 'rb') as f:
    qualified = pickle.load(f)

# Read all lines
with open('crypto_bot.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# ============================================================
# 1. Build new auto strategy lines for MICRO_TOP10_OPTIMIZED_STRATEGIES
# ============================================================
new_auto_lines = []
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
    
    sl_pct = exit['sl_pct']
    be_after = exit['breakeven_after_pct']
    trail_start = exit['trail_start_pct']
    trail_giveback = exit['trail_giveback_pct']
    time_stop = exit['time_stop_bars']
    
    # Strategy name - use uw08 format (upper_wick * 10 as int)
    uw_str = f"{int(max_upper_wick * 10):02d}"
    version = f"auto_top{i}_4h"
    name = f"auto_top{i}_4h_d{delay_bars}_r{max_rank}_chg{min_change}-{max_change}_green_uw{uw_str}_reclaim_sl{sl_pct}_be{be_after}_tr{trail_start}x{trail_giveback}_t{time_stop}"
    new_auto_names.append(name)
    
    strategy_lines = [
        f'    "{name}": {{\n',
        f'        "version": "{version}",\n',
        f'        "entry_delay_bars": {delay_bars},\n',
        f'        "max_rank": {max_rank},\n',
        f'        "min_change_1h_pct": {float(min_change)},\n',
        f'        "max_change_1h_pct": {float(max_change)},\n',
        f'        "min_current_change_1h_pct": 0.0,\n',
        f'        "require_change_reclaim": {str(reclaim).lower()},\n',
        f'        "require_green_confirm": {str(require_green).lower()},\n',
        f'        "max_upper_wick_pct": {max_upper_wick},\n',
        f'        "min_volume_ratio": 0.0,\n',
        f'        "shadow_only": False,\n',
        f'        "stop_loss_pct": {sl_pct},\n',
        f'        "breakeven_after_pct": {be_after},\n',
        f'        "trailing_start_pct": {trail_start},\n',
        f'        "trailing_giveback_pct": {trail_giveback},\n',
        f'        "time_stop_bars": {time_stop},\n',
        f'    }},\n'
    ]
    new_auto_lines.extend(strategy_lines)

# Add comment header
comment_header = [
    '    # === Auto-optimized strategies from 4H scheduler (2026-06-10) ===\n',
    '    # Entry: delay=2, max_rank=3, chg=3-10%, green_confirm, max_upper_wick=0.8%, reclaim_entry\n',
    '    # Not shadow_only — intended for Render paper/shadow monitoring with live-ready potential.\n'
]

# Replace lines 650-703 (0-indexed: 649-702) with new strategies
# Line numbers are 1-indexed, so line 650 = index 649, line 703 = index 702
# The range is inclusive, so we replace lines[649:703] (649 to 702 inclusive)
new_auto_block = comment_header + new_auto_lines

# Verify the old auto strategies are at the expected location
print(f"Line 649 (should be comment): {lines[649].strip()}")
print(f"Line 650 (should be auto_top1): {lines[650].strip()}")
print(f"Line 702 (should be last auto): {lines[702].strip()}")
print(f"Line 703 (should be closing brace): {lines[703].strip()}")

# Replace
lines[649:703] = new_auto_block

# ============================================================
# 2. Update microActiveStrategies in CONFIG (line 90, 0-indexed: 89)
# ============================================================
# Line 90 is the microActiveStrategies line
target_line_idx = 89  # 0-indexed
line = lines[target_line_idx]
print(f"Original line 90: {line.strip()[:100]}...")

# Replace old auto strategies with new ones
pattern = r'("microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*")([^"]+)("\))'
match = re.search(pattern, line)
if not match:
    raise ValueError("Could not find microActiveStrategies in CONFIG")

prefix = match.group(1)
old_strategies_str = match.group(2)
suffix = match.group(3)

# Parse existing strategies
existing = old_strategies_str.split(",")

# Remove old auto_top strategies
filtered = [s for s in existing if not s.startswith("auto_top")]

# Add new auto strategies at the end
new_strategies_list = filtered + new_auto_names
new_strategies_str = ",".join(new_strategies_list)

new_line = prefix + new_strategies_str + suffix + "\n"
lines[target_line_idx] = new_line
print(f"Updated line 90: {new_line.strip()[:100]}...")

# ============================================================
# Write back
# ============================================================
with open('crypto_bot.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Updated crypto_bot.py successfully")
print(f"Added {len(new_auto_names)} new auto strategies:")
for name in new_auto_names:
    print(f"  {name}")
