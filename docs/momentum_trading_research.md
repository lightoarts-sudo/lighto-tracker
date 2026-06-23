# 動能交易策略與因子研究筆記

日期：2026-06-23
狀態：研究階段；不部署、不重啟 cron、不下 OKX 實盤。

## 1. 研究來源

透過 Crossref / arXiv metadata 查到的核心文獻與實務主題：

1. Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency*, DOI: `10.1111/j.1540-6261.1993.tb04702.x`
   - 經典橫截面動能：買近期贏家、賣近期輸家。
2. Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, DOI: `10.1016/j.jfineco.2011.11.003`
   - 經典時間序列動能 / trend following：資產自己的過去報酬預測未來方向。
3. Daniel & Moskowitz (2016), *Momentum Crashes*, DOI: `10.1016/j.jfineco.2015.12.002`
   - 動能策略在市場劇烈反彈/狀態轉換時容易 crash，需要 regime 與風險控管。
4. Trend following / futures momentum 類研究，例如 *Trend following, risk parity and momentum in commodity futures*, DOI: `10.1016/j.irfa.2013.10.001`
   - 風險平價、波動縮放、趨勢跟隨對多市場有效，但需要風控與交易成本處理。
5. Crypto momentum 近年研究方向：volume-weighted time-series momentum、crypto return volatility / volume factors。
   - Crypto 市場較受流動性、交易所微結構、暴漲暴跌與 funding/槓桿清算影響，不能只套股票月頻動能。

## 2. 動能策略主要類型

### A. Cross-sectional momentum（橫截面動能）
同一時間比較多個資產，買排名最強者。

可用因子：
- `rank_1h`：1H 漲幅排名。
- `change_1h_pct`：1H 報酬。
- TopN 進榜/留榜時間。
- 相對強度：標的 1H 報酬 - 全市場/TopN 中位數報酬。

適合本專案：OKX SWAP 1H Top20 universe。

風險：
- 容易追高，特別是剛急拉進榜。
- Top1/Top3 可能已過熱。
- 如果沒有 volume / wick / pullback filter，容易買在尖峰。

### B. Time-series momentum（時間序列動能）
不只看排名，也要求該標的自身趨勢健康。

可用因子：
- 5m / 15m / 1H return stack。
- EMA9 > EMA21 > EMA60。
- 價格在 VWAP / MA60 上方。
- 最近 N 根 K 高低點結構：higher high / higher low。
- Breakout 後 retest / reclaim。

適合：降低單純 TopN 追高問題。

### C. Breakout momentum（突破動能）
買突破區間高點、VWAP、前高、盤整區。

可用因子：
- 近 12/24 根 5m high breakout。
- 突破後不立刻回落。
- 成交量放大但不要異常爆量。
- close location value：收盤接近高點。

風險：
- 假突破。
- 上影線過長。
- Spread / 滑價。

### D. Pullback / continuation momentum（回調延續）
不是買第一根暴拉，而是等強勢幣回踩後再續漲。

可用因子：
- 前面 1H/2H 強勢。
- 最近 15m 回調但不跌破 VWAP/EMA21。
- 回踩後重新收上 EMA9/VWAP。
- 量縮回調、放量續漲。

這類可能比「剛進榜追買」更適合 crypto micro 5m。

### E. Volume-weighted momentum（量能加權動能）
動能信號需由成交量確認。

可用因子：
- `vol_ratio_5m`。
- 目前 K volume / 過去 12 根 median volume。
- quote volume 24h 流動性門檻。
- volume spike 後的延續性。

注意：過高 volume spike 可能是尾端清算/出貨，不一定正面。

## 3. 建議因子庫

### 價格/報酬因子
- `ret_5m`, `ret_15m`, `ret_30m`, `ret_1h`, `ret_2h`, `ret_4h`
- `rank_1h`, `rank_change`：排名改善速度
- `relative_strength`：標的報酬 - universe 中位數報酬
- `acceleration`：ret_15m / ret_1h 或 ret_5m 變化

### 趨勢結構因子
- `ema9 > ema21 > ema60`
- `close > vwap`
- `slope_ema21`, `slope_ema60`
- `higher_low_count`
- `breakout_above_high12/high24`
- `reclaim_after_pullback`

### K 線品質因子
- `green_candle`：close > open
- `upper_wick_pct`
- `close_location_value = (close-low)/(high-low)`
- `range_pct`
- `body_pct`

### 量能/流動性因子
- `volume_ratio_5m`
- `volume_ratio_15m`
- `quote_volume_24h`
- `spread_pct`
- `slippage_estimate`
- `volume_spike_too_high`：避免尾端爆量追高

### 風險/過熱因子
- `distance_from_ma60_pct`
- `atr_pct_5m`
- `chase_risk`：短時間漲幅過大 + 上影線 + 遠離均線
- `drawdown_from_recent_high`
- `funding_rate`（未來可接 OKX）
- `open_interest_change`（未來可接 OKX）

### Regime 因子
- BTC / ETH 1H/4H 趨勢
- 全市場 Top20 廣度：多少標的 > 0 / > 1%
- volatility regime：ATR 分位數
- risk-on/off：BTC 是否在 MA/VWAP 上方

## 4. 本機 DB 可用資料

目前 `data/okx_micro_5m_tracking.sqlite` 可用表：

- `candles_5m`：1,801,705 rows，5m OHLCV。
- `rankings`：9,960 rows，snapshot ranking + `rank_1h`, `change_1h_pct`, `vol_ratio_5m`, `atr_pct_5m`, `structure`。
- `top10_1h_training_runs`：5,516 rows，TopN 收集批次。
- `top10_1h_training_rankings`：27,595 rows，TopN ranking。
- `top10_1h_training_sessions`：6,236 rows，進榜 session。
- `top10_1h_training_candles`：23,598 rows，session 內 5m candles。

備註：目前歷史策略/績效表已清空，這是正確的 reset 後狀態。

## 5. 初步本機因子探索（警告：不可直接當績效）

用 `top10_1h_training_sessions + top10_1h_training_candles` 做粗略探索，取 session 第一根 candle 後 12 根 5m 的 close-to-close return。

樣本：236 個 session 有至少 13 根 candle。

觀察：
- ALL：avg r12 約 +5.14%，win 約 99%。
- rank <= 3：avg r12 約 +5.50%。
- change 1-3%：avg r12 約 +4.66%。
- vol >= 1.5：avg r12 約 +4.75%。

**重要警告：這個結果高度可疑，不能直接用於部署。**
可能原因：
- session/candle 建構有 survivorship bias，只留下仍在榜內且有足夠後續 K 的片段。
- 第一根 candle 不一定等於可交易入場點。
- 未納入 bid/ask spread、滑價、交易成本、延遲、停損觸發順序。
- 沒有處理同一標的/同一行情的重複樣本。

所以後續研究必須改用嚴格 walk-forward event dataset：每 5m snapshot 當下可見資料 -> 產生 signal -> 下一根或下一 N 根入場 -> 模擬 stop/take/trailing，不能用事後 session 結構。

## 6. 下一版策略研究方向

### 方向 1：Rank + Pullback Reclaim Momentum
目標：不要買第一根暴拉，等強勢標的回踩後續漲。

候選條件：
- `rank_1h <= 10`
- `ret_1h between 1% and 8%`
- `ret_15m not too hot`，例如 < 1.5%
- `close > vwap` 且 `close reclaim ema9/ema21`
- 上一段有 breakout，當前不是大上影線
- `volume_ratio between 1.2 and 4.0`

### 方向 2：Early Trend Continuation
目標：抓剛開始的健康趨勢，不追尖峰。

候選條件：
- `rank_1h <= 20`
- `ret_1h between 0.8% and 4%`
- `ema9 > ema21`，EMA21 斜率向上
- `distance_from_ma60 < 2.5%`
- `upper_wick < 1%`
- `close_location_value > 0.6`

### 方向 3：Volume-confirmed Breakout
目標：只買有量確認的突破，但排除爆量尾端。

候選條件：
- close breaks high12/high24
- `volume_ratio between 1.5 and 5`
- breakout candle close location > 0.7
- spread/slippage 合格
- 不在 BTC risk-off regime

### 方向 4：Cross-sectional Rotation
目標：不只看單幣，而是 Top20 排名持續改善。

候選條件：
- 連續 2-3 個 snapshot 排名改善
- 1H relative strength 高於 Top20 median
- volume confirmation
- 排除已經從低點漲超過 X ATR 的 chase risk

## 7. 風控與驗證規範

未來任何策略不能直接用 optimizer 最佳結果部署，必須通過：

1. Walk-forward split
   - train / validation / holdout 分離。
2. Event-level backtest
   - 嚴格只用當下資料。
3. 成本
   - 至少扣 OKX taker fee + spread + slippage。
4. 交易順序
   - 同一根 K 內如果同時碰 SL/TP，採保守假設：先 SL。
5. 樣本
   - closed trades >= 100 才能說有初步參考；>= 300 才能考慮自動化。
6. 穩定性
   - 不可只靠單日/單幣/單事件。
7. 風險
   - max loss、max daily loss、consecutive loss、exposure cap。

## 8. 建議下一步

先不要恢復 Render/cron。

下一步應建立乾淨研究 pipeline：

1. 從 `rankings` + `candles_5m` 建 event dataset。
2. 為每個 5m snapshot 計算因子。
3. 產生多個策略原型：pullback reclaim、early trend、volume breakout、rotation。
4. 做 walk-forward backtest。
5. 僅輸出研究報告，不部署。
6. 等策略在 holdout + paper 都穩定後，再考慮 Render 測試。
