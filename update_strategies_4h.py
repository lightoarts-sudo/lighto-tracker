#!/usr/bin/env python3
"""Update crypto_bot.py with new 4H optimizer strategies."""

import re

# Read the optimizer results
import json
with open('data/top10_1h_optimizer_latest.json', 'r') as f:
    results = json.load(f)

top3 = results['top'][:3]

# Build new strategy dicts
new_strategies = {}
for i, r in enumerate(top3, 1):
    entry = r['entry']
    exit_ = r['exit']
    
    # Build naming from params
    entry_name = entry['name']
    exit_name = exit_['name']
    
    # Parse entry name for version
    # e.g., delay3_rank3_chg3-10_green_vol_reclaim_dur10-40
    # -> auto_top1_4h_d3_r3_chg3-10_green_uw1.2_vol10_reclaim_dur1040
    
    # Extract key params for naming
    delay = entry['delay_bars']
    max_rank = entry['max_entry_rank']
    min_chg = entry['min_entry_change']
    max_chg = entry['max_entry_change']
    green = 'green' if entry['require_green_confirm'] else 'nogreen'
    wick = entry['max_upper_wick_pct'] if entry['max_upper_wick_pct'] else 0
    vol = entry['min_vol_ratio'] if entry['min_vol_ratio'] else 0
    reclaim = 'reclaim' if entry['reclaim_entry_price'] else 'noreclaim'
    dur_min = entry['min_session_bars'] if entry['min_session_bars'] else 0
    dur_max = entry['max_session_bars'] if entry['max_session_bars'] else 0
    
    sl = exit_['sl_pct']
    be = exit_['breakeven_after_pct'] if exit_['breakeven_after_pct'] else 0
    trail_start = exit_['trail_start_pct'] if exit_['trail_start_pct'] else 0
    trail_giveback = exit_['trail_giveback_pct'] if exit_['trail_giveback_pct'] else 0
    t_stop = exit_['time_stop_bars']
    
    # Build strategy key (matching existing naming convention)
    if dur_min > 0:
        dur_part = f"dur{dur_min}{dur_max}"
    else:
        dur_part = ""
    
    strat_key = f"auto_top{i}_4h_d{delay}_r{max_rank}_chg{min_chg}-{max_chg}_{green}_uw{wick}_vol{int(vol*10 if vol<10 else vol)}{dur_part}_sl{sl}_be{be}_tr{trail_start}x{trail_giveback}_t{t_stop}"
    
    new_strategies[strat_key] = {
        "version": f"auto_top{i}_4h",
        "entry_delay_bars": entry['delay_bars'],
        "max_rank": entry['max_entry_rank'],
        "min_change_1h_pct": entry['min_entry_change'],
        "max_change_1h_pct": entry['max_entry_change'],
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": entry['require_green_confirm'],
        "max_upper_wick_pct": entry['max_upper_wick_pct'] if entry['max_upper_wick_pct'] else 0.0,
        "min_volume_ratio": entry['min_vol_ratio'] if entry['min_vol_ratio'] else 0.0,
        "reclaim_entry_price": entry['reclaim_entry_price'],
        "shadow_only": False,
        "stop_loss_pct": exit_['sl_pct'],
        "breakeven_after_pct": exit_['breakeven_after_pct'] if exit_['breakeven_after_pct'] else 0.0,
        "trailing_start_pct": exit_['trail_start_pct'] if exit_['trail_start_pct'] else 0.0,
        "trailing_giveback_pct": exit_['trail_giveback_pct'] if exit_['trail_giveback_pct'] else 0.0,
        "time_stop_bars": exit_['time_stop_bars'],
    }

# Read crypto_bot.py
with open('crypto_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the MICRO_TOP10_OPTIMIZED_STRATEGIES dict and insert before MICRO_EXCLUDED_BASES
# We'll insert after the last strategy entry (before the closing brace before MICRO_EXCLUDED_BASES)

# Find the position of MICRO_EXCLUDED_BASES
match = re.search(r'\nMICRO_EXCLUDED_BASES\s*=', content)
if not match:
    print("ERROR: Could not find MICRO_EXCLUDED_BASES")
    exit(1)

insert_pos = match.start()

# Find the closing brace of MICRO_TOP10_OPTIMIZED_STRATEGIES (should be just before MICRO_EXCLUDED_BASES)
# Look backwards from MICRO_EXCLUDED_BASES for the closing }
brace_pos = content.rfind('}', 0, insert_pos)
if brace_pos == -1:
    print("ERROR: Could not find closing brace of MICRO_TOP10_OPTIMIZED_STRATEGIES")
    exit(1)

# Insert new strategies before that closing brace
new_entries = []
for k, v in new_strategies.items():
    lines = [f'    "{k}": {{\n']
    for pk, pv in v.items():
        if isinstance(pv, bool):
            pv_str = 'True' if pv else 'False'
        elif isinstance(pv, float):
            pv_str = f'{pv}'
        elif isinstance(pv, int):
            pv_str = f'{pv}'
        else:
            pv_str = f'"{pv}"'
        lines.append(f'        "{pk}": {pv_str},\n')
    lines.append('    },\n')
    new_entries.append(''.join(lines))

new_content = content[:brace_pos] + '\n' + ''.join(new_entries) + content[brace_pos:]

# Update _DEFAULT_MICRO_ACTIVE - replace the 3 auto_top entries
# Current format has trailing commas
old_active = '''_DEFAULT_MICRO_ACTIVE = (
    "auto_top1_4h_d3_r3_chg3-10_green_uw0.8_vol20_reclaim_dur1040_sl1.0_be0.6_tr0.9x0.4_t8,",
    "auto_top2_4h_d3_r3_chg3-10_green_uw0.8_vol20_reclaim_dur1040_sl1.0_be0.6_tr0.9x0.4_t12,",
    "auto_top3_4h_d3_r3_chg3-10_green_uw0.8_vol20_reclaim_dur1040_sl1.0_be0.6_tr0.9x0.4_t18,",
    "strategy4_1_breakout_confirmation,",
    "strategy20_6h12h_cool_vwap_reclaim,",
)'''

# Build new active tuple with new strategy names (need to add trailing comma like existing)
new_auto_names = [f'"{k},"' for k in new_strategies.keys()]
new_active = f'''_DEFAULT_MICRO_ACTIVE = (
    {new_auto_names[0]},
    {new_auto_names[1]},
    {new_auto_names[2]},
    "strategy4_1_breakout_confirmation,",
    "strategy20_6h12h_cool_vwap_reclaim,",
)'''

new_content = new_content.replace(old_active, new_active)

# Write back
with open('crypto_bot.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Updated crypto_bot.py with 3 new strategies:")
for k in new_strategies.keys():
    print(f"  {k}")
print("\nUpdated _DEFAULT_MICRO_ACTIVE tuple")