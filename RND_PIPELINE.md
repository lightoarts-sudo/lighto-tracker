# LIGHTOARTS OKX 策略研發流程 (R&D Pipeline)

> 更新時間：2026-06-15  
> 核心原則：**Point-in-time 嚴謹、Walk-Forward 驗證、硬門檻不妥協、影子先行、原生硬停損**

---

## 🔄 完整四階段流程

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ ① 資料收集       │───→ │ ② 參數優化搜尋   │───→ │ ③ 驗證分級       │───→ │ ④ 實盤推廣       │
│  (每5分鐘持續)   │     │  (每日11:00)     │     │  (研究審核)      │     │  (每日23:00)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## ① 資料收集層（基礎設施）

| 腳本 | 頻率 | 功能 | 產出 |
|------|------|------|------|
| `okx_top10_1h_training_collector.py` | 每 5 分鐘 | 抓全市場 SPOT USDT → 計算 1H 漲幅 → 排名 → 追蹤 **進榜/出榜 session** → 存 5m K 線 | `data/okx_micro_5m_tracking.sqlite` |

### 關鍵設計
- **Session 定義**：幣種進入 Top10 = session 開始；摔出 Top10 = session 結束
- **Point-in-time 正確性**：每根 5m K 線記錄當時的 `rank_1h`、`change_1h_pct`，回測時**只能看當下可見資訊**
- **資料量**：~1.2 萬 closed sessions，200+ 幣種，從 2026-05-31 累積至今

---

## ② 參數優化搜尋（每日 11:00 自動跑）

**腳本**：`tmp_top10_training_optimizer.py`

### 搜尋空間（網格搜尋）
```python
# 入場規則組合
delay_bars = [3]                    # IC 分析證實 delay=3 最佳
max_entry_rank = [3]                # Rank 3 主導，Rank 5 衰減
min/max_entry_change = [(3, 10)]    # IC 證實 3-10% 最佳
require_green_confirm = [True]      # 綠K確認
max_upper_wick_pct = [1.2, 0.8]     # 1.2% 基礎 / 0.8% 嚴格
min_vol_ratio = [1.0, 2.0]          # 1.0x 基礎 / 2.0x 嚴格
reclaim_entry_price = [False, True] # 不回踩 / 回踩確認
session_duration = [(6,60), (8,50), (10,40)]  # session 長度過濾

# 出場規則組合
sl_pct = [0.8, 1.0, 1.2]
time_stop_bars = [8, 12, 18]
breakeven_after_pct = [0.6, 0.8]
trail_start_pct = [0.9, 1.2]
trail_giveback_pct = [0.4, 0.6]
```

**組合數**：~144 種 entry × 18 種 exit = **~2,600 個策略組合**

### Walk-Forward 驗證（防過擬合核心）
```python
# 拿最早 7 天當 train，接著 2 天當 test
# 滾動向前：train 7天 → test 2天 → train 9天 → test 2天 → ...
# 只看 test 期間表現，不看 train 期間
```

### 硬門檻篩選（優化器內建）
| 指標 | 門檻 | 來源 |
|------|------|------|
| `min_trades` | ≥ 10 | 樣本數基本門檻 |
| `net_avg_return` | > 0% | 必須有正期望值 |
| `profit_factor` | > 1.5 | 風險報酬比 |
| `max_loss` | > -2% | 單筆虧損可控 |
| `win_rate` | > 40% | 基本勝率 |

**輸出**：
- `data/qualified_strategies.pkl` (Top 3 組合，給 `update_strategies.py` 用)
- `data/top10_1h_optimizer_latest.json` (完整結果，供人工檢視)

---

## ③ 研究審核分級（人工/半自動把關）

**腳本**：`okx_strategy_research_review.py`  
**輸入**：`scan_top10_training_strategies.py` 產出的更廣泛掃描結果（掃描更多參數組合、更長時間窗）

### 三級分類標準

| 等級 | 標籤 | 升級條件 | 用途 |
|------|------|----------|------|
| **L1** | `research-only` | 任一硬門檻不達標 | 僅供觀察、不部署 |
| **L2** | `Render shadow candidate` | PF≥1.15, net_avg>0.05%, 日勝率≥55%, max_loss≥-1.5%, 交易數≥80 | 部署到 Render **影子模式**（不實際下單，只記錄訊號） |
| **L3** | `tiny-pilot candidate` | **PF≥1.5, net_avg>0.15%, 日勝率≥60%, max_loss≥-1.25%, 交易數≥100, 無警告** | 可申請 **OKX 小額實盤試驗** (tiny pilot) |

### 核心防過擬合檢查
```python
# 單日依賴度檢查
one_day_dependency = best_day_pct / net_sum_pct
if one_day_dependency >= 45%:  → WARNING
if net_sum_without_best_day <= 0:  → REJECT (扣掉最好的一天後還要賺錢)

# 連續性檢查
days >= 5 天
day_win_rate >= 50%
```

> **關鍵原則**：研究審核**永遠不宣稱 live-ready**，最多只到 tiny-pilot candidate。真正上實盤還要經過第 4 階段。

---

## ④ 實盤推廣流程（每日 23:00）

```
Render 上的最佳策略
       ↓
Preflight 檢查（本地跑）：
  ├─ 樣本數充足？(trades ≥ 30)
  ├─ PF ≥ 1.5？
  ├─ 淨期望值 > 0 且穩定？
  ├─ 最大虧損 > -2%？
  ├─ 勝率 > 40%？
  ├─ 不依賴單一天？(one_day_dependency < 45%)
  └─ 近期表現無顯著衰退？
       ↓
通過 → 推送到 OKX 實盤 (原生 1% 硬停損)
失敗 → PAUSE + 通報
```

---

## ⚖️ 研發鐵律（不可違反的規則）

| 原則 | 說明 | 違反後果 |
|------|------|----------|
| **Point-in-time 嚴謹** | 回測只能用進場當下可見的 rank/change/volume，不能用 session 結束後的資料 | 看起來很美但實盤失效 |
| **Walk-Forward > In-sample** | 只相信 test window 表現，train window 只用來選參數 | In-sample 過擬合 |
| **硬門檻不妥協** | PF<1.5、max_loss<-2%、WR<40% 直接淘汰，不討論 | 實盤爆雷 |
| **單日依賴度 < 45%** | 扣掉最好的一天還要賺錢 | 幸運者偏差 |
| **最小樣本數** | 研究 ≥30、影子 ≥80、實盤 ≥100 | 小樣本隨機性 |
| **原生硬停損** | 實盤每筆必掛 OKX 1% 止損單，軟體停損只能做輔助 | 系統故障/網路斷線不爆倉 |
| **影子先行** | 任何新策略必須先在 Render 跑 2 週影子模式，訊號驗證無誤才能申請實盤 | 未驗證直上實盤 |

---

## 📁 完整腳本鏈路

```
資料收集
  okx_top10_1h_training_collector.py (每5m)
        ↓ SQLite
參數優化
  tmp_top10_training_optimizer.py (每日11:00)
        ↓ pkl + json
部署同步
  update_strategies.py (優化後立即)
        ↓ git push → Render 自動部署
廣泛掃描/研究
  scan_top10_training_strategies.py (手動/排程)
        ↓ json
研究審核分級
  okx_strategy_research_review.py (輸出 md/json)
        ↓
實盤推廣決策
  人工/半自動 Preflight (每日23:00)
        ↓
OKX 實盤執行
  okx_strategy22_live_pilot.py / okx_dplus_live_pilot.py
```

---

## 🎯 目前研發重心（2026-06 狀態）

1. **動態排序策略**：已驗證 `delay=3, rank≤3, chg=3-10%, green_confirm, wick≤1.2%, vol≥1.0x` 是核心骨架
2. **出場參數微調**：SL 0.8/1.0/1.2%、time_stop 8/12/18、BE 0.6/0.8、Trail 0.9×0.4 vs 1.2×0.6
3. **Session 長度過濾**：`dur=10-40` 目前勝過 `dur=6-60`，代表太短/太長的 session 都不好
4. **回踩確認**：目前動態三條 `reclaim=False`（突破即進），固定策略用 `reclaim=True`，兩種互補
5. **防過擬合**：Walk-forward + 單日依賴度 + 最小樣本數 三重把關

---

## 📂 關鍵輸出檔案對照表

| 階段 | 檔案 | 用途 |
|------|------|------|
| 資料 | `data/okx_micro_5m_tracking.sqlite` | 原始 session + K 線資料庫 |
| 優化 | `data/qualified_strategies.pkl` | Top 3 給部署腳本用 |
| 優化 | `data/top10_1h_optimizer_latest.json` | 完整優化結果（含所有指標） |
| 掃描 | `data/top10_training_strategy_scan_latest.json` | 廣泛參數掃描結果 |
| 審核 | `data/okx_strategy_research_review_latest.json` | 分級標籤 + 詳細指標 |
| 審核 | `data/okx_strategy_research_review_latest.md` | 人工閱讀報告 |
| 部署 | `render.yaml` | Render 環境變數（含 CRYPTO_MICRO_ACTIVE_STRATEGIES） |
| 部署 | `crypto_bot.py` | 實盤主程式（含 MICRO_TOP10_OPTIMIZED_STRATEGIES 定義） |

---

## 🔧 相關文件
- `STRATEGY_LOGIC.md` — 策略入出場邏輯細節
- `RND_PIPELINE.md` — 本文件（研發流程總覽）