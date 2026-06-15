# LIGHTOARTS OKX 1H Top10 策略邏輯總整理

> 更新時間：2026-06-15  
> 來源：`crypto_bot.py` → `micro_top10_optimized_signal()` + `_apply_micro_top10_optimized()` + `micro_top10_optimized_should_exit()`

---

## 🎯 核心概念

**只交易 1H 漲幅排行榜 Top N 的幣種**，捕捉「衝上排行榜後的延續動能」。

- **資料頻率**：5 分鐘 K 線（每 5 分鐘輪詢一次）
- **標的篩選**：OKX SPOT USDT，排除主流幣/稳定幣，依 1H 漲幅排名
- **策略類型**：動態優化策略（auto_top1/2/3）+ 固定策略（strategy4.1, strategy20, top5dplus）

---

## 📊 目前上線的 3 條動態策略參數

| 參數 | auto_top1 (t8) | auto_top2 (t12) | auto_top3 (t18) |
|------|----------------|-----------------|-----------------|
| `entry_delay_bars` | 3 | 3 | 3 |
| `max_rank` | 3 | 3 | 3 |
| `min_change_1h_pct` | 3.0% | 3.0% | 3.0% |
| `max_change_1h_pct` | 10.0% | 10.0% | 10.0% |
| `min_current_change_1h_pct` | 0.0% | 0.0% | 0.0% |
| `require_green_confirm` | ✅ | ✅ | ✅ |
| `max_upper_wick_pct` | 1.2% | 1.2% | 1.2% |
| `min_volume_ratio` | 1.0 | 1.0 | 1.0 |
| `reclaim_entry_price` | ❌ | ❌ | ❌ |
| `stop_loss_pct` | 1.0% | 1.0% | 1.0% |
| `breakeven_after_pct` | 0.6% | 0.6% | 0.6% |
| `trailing_start_pct` | 0.9% | 0.9% | 0.9% |
| `trailing_giveback_pct` | 0.4% | 0.4% | 0.4% |
| `time_stop_bars` | **8** | **12** | **18** |

> **唯一差異**：`time_stop_bars`（時間停利根數）= 40min / 60min / 90min

---

## ✅ 入場條件檢查清單（全部通過才進場）

代碼位置：`micro_top10_optimized_signal()` 第 4078 行

```python
if (rank_ok                    # 1️⃣ 在 Top 3 內
    and heat_ok                # 2️⃣ 進榜時 1H 漲幅 3% ~ 10%
    and current_change_ok      # 3️⃣ 當前 1H 漲幅 ≥ 0%
    and reclaim_ok             # 4️⃣ 不需回踩確認
    and volume_ok              # 5️⃣ 量比 ≥ 1.0x (當前5m量 / 過去20根平均)
    and delay_ok               # 6️⃣ 【關鍵】必須是進榜後第 3 根 5m K（15分鐘後）
    and upper_wick_ok          # 7️⃣ 上影線佔整根K線比例 ≤ 1.2%
    and green_confirm_ok       # 8️⃣ 當根 5m K 線是綠 K (close ≥ open)
    and spread_ok              # 9️⃣ 買賣價差不過濾 (動態三條無設定)
    and pct2h_ok               # 🔟 2h 漲幅門檻 (動態三條無設定)
    and pct3h_ok):             # 1️⃣1️⃣ 3h 漲幅門檻 (動態三條無設定)
    base["buy"] = True
```

### 詳細條件說明

| # | 條件 | 參數來源 | 實際邏輯 |
|---|------|----------|----------|
| 1 | **排名門檻** | `max_rank=3` | `rank_1h is not None and rank_1h <= 3` |
| 2 | **進榜熱度** | `min_change_1h_pct=3`, `max_change_1h_pct=10` | `3% <= entry_change_1h <= 10%` |
| 3 | **當前熱度** | `min_current_change_1h_pct=0` | `current_change_1h >= 0%` |
| 4 | **回踩確認** | `require_change_reclaim=False` | 永遠通過 |
| 5 | **量比門檻** | `min_volume_ratio=1.0` | `volumeRatio >= 1.0` |
| 6 | **延遲入場** ⭐ | `entry_delay_bars=3` | `session_age_bars == 3` **（只在第3根K線允許進場，不是之後）** |
| 7 | **上影線** | `max_upper_wick_pct=1.2` | `(high - max(close,open)) / (high-low) * 100 <= 1.2%` |
| 8 | **綠K確認** | `require_green_confirm=True` | `close >= open` |
| 9 | **價差過濾** | `max_spread_pct` 未設定 | 永遠通過 |
| 10 | 2h趨勢 | `min_pct2h_pct` 未設定 | 永遠通過 |
| 11 | 3h趨勢 | `min_pct3h_pct` 未設定 | 永遠通過 |

---

## 🚪 出場條件

代碼位置：`micro_top10_optimized_should_exit()` + OKX 原生止損單

| 條件 | 觸發邏輯 | 出場原因標籤 |
|------|----------|--------------|
| **硬停損 1%** | 開倉即送 OKX 交易所原生止損單 | `{version}_stop_loss_1pct` |
| **保本鎖定** | 獲利 ≥ 0.6% → 移動停損到進場價 | `{version}_breakeven_or_trailing_stop` |
| **移動停利** | 獲利 ≥ 0.9% → 啟動 trailing，回吐 0.4% 停利 | `{version}_breakeven_or_trailing_stop` |
| **時間停利** | 持倉達 `time_stop_bars` 根 K (8/12/18) → 市價平倉 | `{version}_time_stop` |
| **摔出排行榜** | `rank_1h is None` → 立即市價平倉 | `{version}_session_end` |

### 停損/停利價格計算

```python
entry = state["avgEntry"]
stop_price = entry * (1 - 1.0/100)  # 硬停損 1%

peak = max(state.get("peakPrice", price), price)
peak_gain = (peak - entry) / entry * 100

# 保本
if peak_gain >= 0.6%:
    active_stop = max(active_stop, entry)

# 移動停利
if peak_gain >= 0.9%:
    active_stop = max(active_stop, peak * (1 - 0.4/100))

# 觸發
if signal["lastLow"] <= active_stop:
    exit()
```

---

## 🔄 完整生命週期

```
每 5 分鐘輪詢
    ↓
抓取所有 SPOT USDT Ticker → 計算 1H 漲幅 → 排序取 Top N
    ↓
對每個在 Top N 內的幣種：
    ├─ 已有持倉 → 檢查出場條件 (硬停損/移動停利/時間停利/摔榜)
    ├─ 無持倉、進榜後第 3 根 K → 檢查 8 項入場條件 → 全通過則市價買入
    └─ 無持倉、非第 3 根 K → 只記錄 session_age_bars，等待第 3 根 K
    ↓
若幣種摔出 Top N (rank_1h is None)：
    → 強制平倉 (session_end)
    → 重置 session 狀態
```

---

## 📈 績效基準（2026-05-31 ~ 2026-06-15，2910 sessions）

| 指標 | 數值 | 門檻 |
|------|------|------|
| 交易數 | 77 | ≥ 10 ✅ |
| 勝率 | 57.1% | > 40% ✅ |
| 淨均值報酬 | 0.693% | > 0 ✅ |
| 獲利因子 (PF) | 2.84 | > 1.5 ✅ |
| 最大單筆虧損 | -1.16% | > -2% ✅ |

---

## 🗂️ 關鍵檔案對應

| 功能 | 檔案 | 關鍵函數/類 |
|------|------|-------------|
| 資料收集 (5m) | `okx_top10_1h_training_collector.py` | `init_db`, `fetch_universe`, session 管理 |
| 優化器 | `tmp_top10_training_optimizer.py` | 參數網格搜尋 + 硬門檻篩選 |
| 部署同步 | `update_strategies.py` | pkl → `crypto_bot.py` + `render.yaml` |
| 實盤主程式 | `crypto_bot.py` | `CryptoPaperBot._run_micro_once_locked` |
| 入場訊號計算 | `crypto_bot.py` | `micro_top10_optimized_signal()` |
| 出場判斷 | `crypto_bot.py` | `micro_top10_optimized_should_exit()` |
| 策略應用 | `crypto_bot.py` | `_apply_micro_top10_optimized()` |

---

## ⚠️ 易誤解的關鍵細節

1. **不是「進榜即進場」**：必須等 **第 3 根 5m K 線**（`entry_delay_bars=3`），代碼用 `delay_exact` 精確比對，不是 `>=`
2. **不是看 Top 5**：動態三條 `max_rank=3`，只看前 3 名
3. **不需要回踩**：`reclaim_entry_price=False`，突破確認即進
4. **硬停損是交易所原生單**：開倉即送 OKX 止損單，不是靠軟體監控
5. **摔榜即平倉**：不等時間停利，`session_end` 直接市價出場

---

## 🔧 參數調整位置

- **策略定義**：`crypto_bot.py` → `MICRO_TOP10_OPTIMIZED_STRATEGIES` dict
- **啟用清單**：`render.yaml` → `CRYPTO_MICRO_ACTIVE_STRATEGIES` env var
- **預設值**：`crypto_bot.py` → `CONFIG["microActiveStrategies"]` default
- **優化器輸出**：`data/qualified_strategies.pkl` → 經 `update_strategies.py` 同步