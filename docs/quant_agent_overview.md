# LIGHTOARTS Quant Agent — 可运行与清理整理

> 状态：2026-06-29 版本
> 原则：主链优先，旧脚本统一归类，不要散发在根目录。

## 一、主流程图（Local-only）

```
数据层（每5分钟）
  okx_top10_1h_training_collector.py   -> data/okx_micro_5m_tracking.sqlite
  okx_top10_volume_5m_collector.py     -> data/okx_top10_volume_5m_tracking.sqlite
                    ↓
研发层
  scripts/strategy_rd_8h.py
  tmp_top10_training_optimizer.py
  local_strategy_scanner.py / local_backtest_topn.py
                    ↓
策略池
  data/strategy_pool.json
  data/active_strategies.json
                    ↓
自动化管理
  auto_manage_strategies.py
                    ↓
本地产出
  render.yaml / active_strategies.json  （等待 crypto_bot.py 修复后再回填）
```

## 二、当前可运行的主链

| 脚本 | 作用 | 当前状态 |
|---|---|---|
| `scripts/strategy_rd_8h.py` | 产出 candidate | ✅ 可跑 |
| `tmp_top10_training_optimizer.py` | 参数回测 | ✅ 可跑，注意计算量 |
| `local_strategy_scanner.py` | 策略扫描 | ✅ 可跑，`--min-trades 0` 不要设太高 |
| `local_backtest_topn.py` | 局部回测 | ✅ 可跑 |
| `auto_manage_strategies.py` | 调整 active/pool | ✅ 可跑 |

## 三、当前阻塞

- `crypto_bot.py`：目前脚本依赖链出现问题，先不盲目 import；一旦修好，再由 `auto_manage_strategies.py` 反向写回。
- `run_strategy_research_pipeline.py`：会串起前面多个脚本，但单独执行容易超时；优先级改为**按需单点调用**。

## 四、清理清单

建议统一放到 `archive/` 再一起删除，不要继续散落在根目录：

- `update_crypto_bot*.py`
- `update_strategies*.py`
- `backtest_3_candidates.py`
- `backtest_candidates.py`
- `check_*.py`
- `fix_indent.py`
- `replay_*.py`
- `run_lighto_sg_*.py`
- `autoevolve.py`
- `autopromote.py`
- `eval_pool_candidates.py`
- `param_sweep_session_tracking.py`

## 五、Cron（当前有效）

| Job | Schedule | 作用 |
|---|---|---|
| `1e774b4256b3` | `*/5 * * * *` | Top20 训练数据 |
| `3684b2261e6d` | `*/5 * * * *` | Top10 成交量数据 |
| `98ddceac2f2c` | `0 7,12,17,22 * * *` | 8h R&D + auto-manage |
