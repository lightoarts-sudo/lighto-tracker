# LIGHTOARTS Quant Trading Agent

## 使命
每 4 小時根據本機 `data/okx_micro_5m_tracking.sqlite` 的 1H TopN 訓練資料，找出目前最好的策略，部署到 Render paper/shadow 監控；每天 23:00 僅在通過嚴格安全門檻時，才允許推薦/推進 OKX 真錢。

## 三層工作

### 1. Data Collector（每 5 分鐘）
- Job: `aeac23f49154`
- Script: `lighto_top10_1h_training_collect.py`
- 寫入：`data/okx_micro_5m_tracking.sqlite`
- 目的：持續累積 point-in-time TopN 會話與 5m K 線。

### 2. Strategy Optimizer / Render Deployer（每 4 小時）
- Job: `7f1b0b2bc31c`
- 讀 DB，全量回測/優化。
- 只挑符合門檻的策略：
  - net expectancy after fees/slippage > 0
  - PF > 1.5
  - win rate > 40%
  - max loss > -2%
  - closed trades >= 30（若嚴格候選可在報告中標記 sample-low，不直接 live-ready）
- 寫入 `crypto_bot.py` + `render.yaml`，commit/push，並驗證 Render `/api/crypto/micro` config 已出現新策略。
- 不碰 OKX 實盤下單。

### 3. OKX Promotion Gate（每天 23:00）
- Job: `922baf4a155b`
- 從 Render paper/shadow 的有效樣本中挑選。
- 真錢前置條件：
  - Render 最新與歷史窗口皆正期望
  - PF > 1.5
  - max loss < 2%
  - 有足夠樣本且非單日依賴
  - OKX preflight：無其他 runner、無危險持倉/待處理 algo、每筆實倉有 exchange-native reduce-only hard stop
- 若不通過，維持暫停，只報告原因。

## 安全原則
- `shadow_only=True` 永遠不自動推 OKX 真錢。
- OKX 真錢 runner 必須立即放 exchange-native 1% reduce-only hard stop。
- 任何負期望或樣本不足策略只能留 Render paper/shadow。
- 不輸出 OKX API key/secret/passphrase/token。

## 使用者看板
- Render micro: https://lighto-tracker.onrender.com/micro
- Top10 overview: https://lighto-tracker.onrender.com/top10-strategies
- Micro API: https://lighto-tracker.onrender.com/api/crypto/micro
- Overview API: https://lighto-tracker.onrender.com/api/crypto/top10-strategies/overview
