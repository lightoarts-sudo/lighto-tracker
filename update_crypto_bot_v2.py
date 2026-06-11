import json
import re

# Load qualified strategies
import pickle
with open('data/qualified_strategies.pkl', 'rb') as f:
    qualified = pickle.load(f)

# Read crypto_bot.py
with open('crypto_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# 1. Update MICRO_TOP10_OPTIMIZED_STRATEGIES (fix naming)
# ============================================================

# Find the start and end of MICRO_TOP10_OPTIMIZED_STRATEGIES dict
start_marker = "MICRO_TOP10_OPTIMIZED_STRATEGIES = {"
start_idx = content.find(start_marker)
if start_idx == -1:
    raise ValueError("Could not find MICRO_TOP10_OPTIMIZED_STRATEGIES")

# Find the closing brace by counting braces
brace_count = 0
end_idx = start_idx
for i, ch in enumerate(content[start_idx:], start_idx):
    if ch == '{':
        brace_count += 1
    elif ch == '}':
        brace_count -= 1
        if brace_count == 0:
            end_idx = i + 1
            break

# Build new auto strategies with correct naming convention
new_strategies = []
new_auto_names = []
for i, (rank, r) in enumerate(qualified, 1):
    entry = r['entry']
    exit = r['exit']
    
    # Entry params
    delay_bars = entry['delay_bars']
    max_rank = entry['max_entry_rank']
    min_change = entry['min_entry_change']
    max_change = entry['max_entry_change']
    require_green = entry['require_green_confirm']
    max_upper_wick = entry['max_upper_wick_pct']
    reclaim = entry['reclaim_entry_price']
    
    # Exit params
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
    
    strategy = f'''    "{name}": {{
        "version": "{version}",
        "entry_delay_bars": {delay_bars},
        "max_rank": {max_rank},
        "min_change_1h_pct": {float(min_change)},
        "max_change_1h_pct": {float(max_change)},
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": {str(reclaim).lower()},
        "require_green_confirm": {str(require_green).lower()},
        "max_upper_wick_pct": {max_upper_wick},
        "min_volume_ratio": 0.0,
        "shadow_only": False,
        "stop_loss_pct": {sl_pct},
        "breakeven_after_pct": {be_after},
        "trailing_start_pct": {trail_start},
        "trailing_giveback_pct": {trail_giveback},
        "time_stop_bars": {time_stop},
    }},'''
    new_strategies.append(strategy)

new_strategies_text = "\n".join(new_strategies)

# Find the comment marker for auto strategies
comment_marker = "# === Auto-optimized strategies from 4H scheduler"
comment_idx = content.find(comment_marker, start_idx)
if comment_idx == -1:
    raise ValueError("Could not find auto strategies comment")

# Get everything before the auto strategies comment (from dict start)
dict_content_start = content.find("{", start_idx) + 1
before_auto = content[dict_content_start:comment_idx].rstrip(",\n ")

# Build new dict content
new_dict_content = before_auto + ",\n\n" + new_strategies_text + "\n}"
new_dict = "MICRO_TOP10_OPTIMIZED_STRATEGIES = " + new_dict_content

# Replace
content = content[:start_idx] + new_dict + content[end_idx:]

# ============================================================
# 2. Update microActiveStrategies in CONFIG (fix naming)
# ============================================================

pattern = r'("microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*")([^"]+)("\))'
match = re.search(pattern, content)
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

new_config_line = prefix + new_strategies_str + suffix
content = content[:match.start()] + new_config_line + content[match.end():]

# ============================================================
# Write back
# ============================================================
with open('crypto_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated crypto_bot.py successfully")
print(f"Added {len(new_auto_names)} new auto strategies:")
for name in new_auto_names:
    print(f"  {name}")
