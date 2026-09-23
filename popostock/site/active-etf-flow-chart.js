(() => {
  "use strict";

  /*
   * 在「台股加權指數大盤」頁，於選擇權波動率區塊上方插入一張
   * 「主動式 ETF 共識加減碼」柱狀圖：0 軸以上紅色＝加碼，以下綠色＝減碼，
   * 並與大盤 K 線雙向同步時間軸。
   *
   * 位置用 CSS order，不去動 React 的子節點順序：插進它管理的節點會跟
   * reconciliation 打架（這站有過 NotFoundError 的教訓），所以一律 append，
   * 再把父層設成 flex column 並給每個子元素明確的 order。實測把父層從
   * block 改成 flex，七個子元素的寬高完全沒有變化。
   *
   * 時間軸與大盤連動：大盤那張圖是主 bundle 自己建立的
   * （它內嵌了一份 lightweight-charts，不讀 window 上的全域），所以攔截
   * LightweightCharts.createChart 只抓得到覆蓋層自己的圖。實例也沒掛在 DOM、
   * React fiber 裡同樣找不到。因此改由 patch-popostock-chart-registry.mjs
   * 在 bundle 的建立點把實例推進 window.__popostockCharts，這裡再讀它。
   */

  const DATA_URL = "data/active-etf-flow.json";
  const FLAG = "data-popostock-active-flow";
  const PANEL = "popostock-active-flow-block";
  const UP = "#c23d4b";      // 加碼（台股慣例紅）
  const DOWN = "#16845b";    // 減碼

  /* 大盤圖表實例由 bundle patch 推進 window.__popostockCharts。
     取「容器不是比較區塊」的那一張，也就是主圖。 */
  function mainChart() {
    const list = window.__popostockCharts || [];
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const entry = list[i];
      if (!entry || !entry.container || !entry.container.closest) continue;
      if (!document.contains(entry.container)) continue;
      const stage = entry.container.closest(".nav-chart-stage");
      if (stage && !stage.classList.contains("market-comparison-stage")) return entry.chart;
    }
    return null;
  }

  function style() {
    if (document.getElementById("popostock-active-flow-style")) return;
    const el = document.createElement("style");
    el.id = "popostock-active-flow-style";
    el.textContent = [
      "." + PANEL + " .flow-heading{display:flex;justify-content:space-between;",
      "align-items:flex-end;gap:12px;margin-bottom:6px}",
      "." + PANEL + " .flow-heading h4{margin:0;font-size:17px;color:#12295c}",
      "." + PANEL + " .flow-heading span{font-size:12px;color:#7b8aa6}",
      "." + PANEL + " .flow-heading strong{font-size:13px;color:#12295c;white-space:nowrap}",
      "." + PANEL + " .flow-summary{display:flex;gap:18px;flex-wrap:wrap;margin:4px 0 8px;",
      "font-size:13px;font-weight:700;color:#5b6b80}",
      "." + PANEL + " .flow-summary b{font-variant-numeric:tabular-nums}",
      "." + PANEL + " .flow-note{margin-top:6px;font-size:12px;color:#8b98ab;line-height:1.5}",
      "." + PANEL + " .flow-stage{position:relative}",
      "." + PANEL + " .flow-tip{position:absolute;pointer-events:none;z-index:6;display:none;",
      "background:#12295cf2;color:#fff;border-radius:8px;padding:7px 10px;font-size:12px;",
      "line-height:1.55;white-space:nowrap;box-shadow:0 4px 14px rgba(18,41,92,.28)}",
      "." + PANEL + " .flow-tip b{font-size:14px;font-variant-numeric:tabular-nums}",
      "." + PANEL + " .flow-tip i{font-style:normal;color:#9fb3d9}",
    ].join("");
    document.head.appendChild(el);
  }

  function fmt(v) {
    return (v > 0 ? "+" : "") + v.toFixed(1);
  }

  function build(rows, meta, volBlock) {
    const lc = window.LightweightCharts;
    const host = volBlock.parentNode;
    const block = document.createElement("section");
    block.className = "market-comparison-block " + PANEL;
    block.setAttribute("aria-label", "主動式 ETF 共識加減碼同步柱狀圖");

    const last = rows[rows.length - 1];
    const head = document.createElement("div");
    head.className = "market-comparison-heading flow-heading";
    head.innerHTML =
      "<div><h4>主動式 ETF 共識加減碼</h4>" +
      "<span>與大盤同一段日期 · 可自行拖曳縮放</span></div>" +
      "<strong>單位：新台幣億元</strong>";
    block.appendChild(head);

    const summary = document.createElement("div");
    summary.className = "nav-chart-summary market-comparison-summary flow-summary";
    summary.innerHTML =
      "<span>最新 " + last.time + "　淨額 <b style=\"color:" +
      (last.net >= 0 ? UP : DOWN) + "\">" + fmt(last.net) + " 億</b></span>" +
      "<span>加碼 <b style=\"color:" + UP + "\">" + last.buy.toFixed(1) + "</b>　" +
      "減碼 <b style=\"color:" + DOWN + "\">" + last.sell.toFixed(1) + "</b></span>" +
      "<span>納入比較 <b>" + last.comparable + "/" + last.tracked + "</b> 檔</span>";
    block.appendChild(summary);

    const stage = document.createElement("div");
    stage.className = "nav-chart-stage market-comparison-stage flow-stage";
    stage.style.height = "180px";
    block.appendChild(stage);

    const tip = document.createElement("div");
    tip.className = "flow-tip";
    stage.appendChild(tip);

    const note = document.createElement("div");
    note.className = "market-comparison-note flow-note";
    note.textContent = meta.methodology + "。" + meta.coverageNote;
    block.appendChild(note);

    host.appendChild(block);
    place(host, block, volBlock);

    const chart = lc.createChart(stage, {
      height: 180,
      layout: { background: { color: "transparent" }, textColor: "#5b6b80", fontSize: 11 },
      grid: { vertLines: { color: "#eef2f7" }, horzLines: { color: "#eef2f7" } },
      rightPriceScale: { borderColor: "#dfe5ee" },
      timeScale: { borderColor: "#dfe5ee", timeVisible: false },
      crosshair: { mode: lc.CrosshairMode ? lc.CrosshairMode.Normal : 0 },
    });
    const series = chart.addSeries(lc.HistogramSeries, {
      priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      base: 0,
    });
    series.setData(rows.map((r) => ({
      time: r.time, value: r.net, color: r.net >= 0 ? UP : DOWN,
    })));
    chart.timeScale().fitContent();
    keepSynced(chart, rows);
    attachTooltip(chart, series, stage, tip, rows);

    // 改變寬度時只調寬度，**不要** fitContent——那會經由同步把大盤的
    // 可視範圍一起拉回全區間，使用者拖曳過的位置就被重設了。
    new ResizeObserver(() => {
      chart.applyOptions({ width: stage.clientWidth });
    }).observe(stage);
    return block;
  }


  /* 用 flex order 把面板排到波動率區塊前面。沒有明確 order 的元素預設是 0，
     會全部擠到最前，所以每個子元素都要給值，不能只設自己那一顆。 */
  function place(host, block, volBlock) {
    const style = window.getComputedStyle(host);
    if (style.display !== "flex") {
      host.style.display = "flex";
      host.style.flexDirection = "column";
    }
    let step = 0;
    for (const child of Array.from(host.children)) {
      if (child === block) continue;
      step += 10;
      child.style.order = String(step);
      if (child === volBlock) block.style.order = String(step - 5);
    }
  }

  /* 單向同步：大盤 → 本圖，而且必須同步**時間範圍**，不能同步邏輯索引。
     大盤有一萬多根 K 棒，本圖只有數十根；直接套用索引範圍（實測是
     [11068, 11157]）會落在本圖資料尾端之外，畫面只剩最後一根柱子。
     改用 getVisibleRange() 的日期，並夾在本圖資料的起訖之內。 */
  function keepSynced(mine, rows) {
    const first = rows[0].time;
    const last = rows[rows.length - 1].time;
    const clamp = (value) => (value < first ? first : (value > last ? last : value));
    let bound = null;
    let guard = false;

    const apply = (range) => {
      if (!range || guard) return;
      const from = clamp(String(range.from));
      const to = clamp(String(range.to));
      if (from >= to) return;   // 大盤視窗完全落在本圖資料之外，維持現狀
      guard = true;
      try { mine.timeScale().setVisibleRange({ from: from, to: to }); } catch (_) {}
      guard = false;
    };

    const tick = () => {
      const other = mainChart();
      if (!other || other === bound) return;
      bound = other;
      other.timeScale().subscribeVisibleTimeRangeChange(apply);
      try { apply(other.timeScale().getVisibleRange()); } catch (_) {}
    };
    tick();
    window.addEventListener("popostock:chart", tick);
    const timer = window.setInterval(tick, 500);
    window.addEventListener("beforeunload", () => window.clearInterval(timer));
  }

  function keepSynced(mine) {
    let bound = null;
    const tick = () => {
      const other = mainChart();
      if (!other || other === bound) return;
      bound = other;
      let guard = false;
      other.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (guard || !range) return;
        guard = true;
        try { mine.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        guard = false;
      });
      try {
        const range = other.timeScale().getVisibleLogicalRange();
        if (range) mine.timeScale().setVisibleLogicalRange(range);
      } catch (_) {}
    };
    tick();
    window.addEventListener("popostock:chart", tick);
    const timer = window.setInterval(tick, 500);
    window.addEventListener("beforeunload", () => window.clearInterval(timer));
  }

  let installed = false;

  function attempt(data) {
    if (installed) return;
    // 只在台股大盤頁動作：靠波動率區塊的 aria-label 認位置
    const blocks = Array.from(document.querySelectorAll(".market-comparison-block"));
    const vol = blocks.find((b) =>
      (b.getAttribute("aria-label") || "").indexOf("波動率") !== -1);
    if (!vol || !window.LightweightCharts) return;
    if (document.querySelector("." + PANEL)) { installed = true; return; }
    const rows = data.values.filter((r) => r.comparable >= data.minCoverage);
    if (!rows.length) return;
    style();
    build(rows, data, vol);
    installed = true;
  }

  fetch(DATA_URL, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then((data) => {
      attempt(data);
      // 換分頁時 React 會重建這一段，面板消失就重掛
      const observer = new MutationObserver(() => {
        if (installed && !document.querySelector("." + PANEL)) installed = false;
        attempt(data);
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    })
    .catch((error) => {
      console.warn("[popostock] 主動式 ETF 加減碼圖表載入失敗", error);
    });
})();
