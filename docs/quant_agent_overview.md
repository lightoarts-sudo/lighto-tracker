# LIGHTOARTS Quant Agent — 系統與研發邏輯總覽

> 用途：讓策略研發、自動管理、實盤部署三層一致，避免再出現"歷史只有 2 筆交易卻成策略"的假象。  
> 狀態：2026-06-29 重建版，以目前運行中的本地腳本為準。

## 1. 系統定位

這是 **本地量化研發 + Render 實盤部署** 的半自動系統：
- 資料庫與策略研發在本地跑
- 模型參數與策名寫入 `crypto_bot.py`，由 Render 對接 OKX
- 每 8 小時會進行一次 R&D + 策略池管理，中文摘要發回本端

## 2. 資料層：兩條並行采集線

| 采集器 | 頻率 | 寫入目標 | 用途 |
|---|---|---|---|
| `okx_top10_1h_training_collector.py` | 每 5 分鐘 | `data/okx_micro_5m_tracking.sqlite` | 提供 RD 訓練資料：Top20 1H 漲幅榜 session 的 5m K |
| `okx_top10_volume_5m_collector.py` | 每 5 分鐘 | `data/okx_top10_volume_5m_tracking.sqlite` | 提供實盤 universe 排名，按 `quote_vol_24h` 固定前十 |

## 3. 資料庫結構

### 3.1 `okx_micro_5m_tracking.sqlite`
- 來源：Top20 1H 漲幅榜流
- 作用：OD 策略研發用 main dataset
-  Coverage：242+ insts, ~70k candles（截至 2026-06-29）

### 3.2 `okx_top10_volume_5m_tracking.sqlite`
- 來源：Top10 24h 成交量榜
- 作用：監控高流動性 universe，不直接參與訓練

## 4. 策略研發流程（每 8 小時）

觸發時段：`07:00 / 12:00 / 17:00 / 22:00`（台北時間）  
觸發 job：`98ddceac2f2c`

步驟：
1. `python scripts/strategy_rd_8h.py`
2. `python run_strategy_research_pipeline.py`
3. `python auto_manage_strategies.py`
4. 輸出中文摘要：新增/下架/Active 數量/下一輪建議

### 4.1 研發腳本實際行為

- **全量讀取** training DB，不是只看最近一段
- `load_sessions()` 直接 `where is_active=0` 讀出所有 closed sessions
- 入場/出場規則由 EntryRule + ExitRule 組合網格搜索
- 每組合跑完全部 session，才彙整 metrics

### 4.2 當前已移除的交易次數限制

| 檔案 | 原設定 | 現在 |
|---|---|---|
| `scripts/strategy_rd_8h.py` | `MIN_TRADES = 2` | `0` |
| `run_strategy_research_pipeline.py` | `--min-trades 30` | `--min-trades 0` |
| `auto_manage_strategies.py` | `MIN_TRADES = 20` | `0` |

原則：**只要有淨正報酬的進出組合都要研發，不要因為交易次數少而丟棄。**

## 5. 策略池與自動管理

輸入：`data/strategy_pool.json`、`data/active_strategies.json`  
規則（`auto_manage_strategies.py`）：
- 已有 active 策略：只要 `win_rate >= 45%` 且 `realizedPnl >= 0`，就繼續保留
- 新策略晉升：從策略池撈 `win_rate >= 50%` 且 `profit_factor >= 1.0` 的候選放進 active
- 連續衰退策略：`DEMOTE_STREAK = 3` 次失敗就下架

## 6. 實盤部署

- 主程式：`crypto_bot.py`
- 部署位置：Render（URL 由 `render.yaml` → `RENDER_URL` 指定）
- 策略字典：`MICRO_TOP10_OPTIMIZED_STRATEGIES`
- 啟用清單：`CRYPTO_MICRO_ACTIVE_STRATEGIES`

## 7. 排程總覽

| job id | 名稱 | schedule | 功能 |
|---|---|---|---|
| `1e774b4256b3` | LIGHTOARTS OKX 1H Top20 5m training collector | `*/5 * * * *` | 持續補 training DB |
| `3684b2261e6d` | LIGHTOARTS OKX Top10 Volume 5m collector | `*/5 * * * *` | 持續補 volume DB |
| `98ddceac2f2c` | LIGHTOARTS 8h strategy R&D | `0 7,12,17,22 * * *` | RD + 自動管理 + 中文摘要 |

## 8. 關鍵問題（未關閉）

1. `crypto_bot.py` 目前存在 Python 不能正常 import 的損壞狀態，尚未修復
2. 本地 active pool 多數策略歷史回測僅 2~6 筆交易，真實有效性尚待歷史全量回測確認
3. 策略參數需要在 **全量歷史回測通過** 後才能做穩定的生產結論

## 9. 待繼續的下一步

- [ ] 以 clean 策略定義檔重建 crypto_bot.py 的 import 路徑
- [ ] 以全量歷史 session 跑 70 策略歷史回測
- [ ] 根據實際績效建立可信的策略准入標準
