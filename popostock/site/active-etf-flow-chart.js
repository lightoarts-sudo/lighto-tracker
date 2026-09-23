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
   * 取得主圖表實例的方式：**攔截 LightweightCharts.createChart**。
   * 圖表實例沒有掛在 DOM 上，React fiber 也找不到；而覆蓋層在
   * DOMContentLoaded（約 1.1 秒）就執行，主 bundle 要到約 6 秒後才建圖，
   * 所以先包裝工廠函式一定攔得到。不碰 React 內部，也不改既有 DOM。
   */

  const DATA_URL = "data/active-etf-flow.json";
  const FLAG = "data-popostock-active-flow";
  const PANEL = "popostock-active-flow-block";
  const UP = "#c23d4b";      // 加碼（台股慣例紅）
  const DOWN = "#16845b";    // 減碼

  // container → chart，攔截工廠函式後累積
  const charts = new Map();

  function hookCreateChart() {
    const lc = window.LightweightCharts;
    if (!lc || typeof lc.createChart !== "function" || lc.__popostockFlowHooked) return;
    const original = lc.createChart;
    const wrapped = function (container) {
      const chart = original.apply(this, arguments);
      try { charts.set(container, chart); } catch (_) {}
      return chart;
    };
    // standalone build 的匯出物件是 frozen 的：直接指派會丟
    // "Cannot assign to read only property"，defineProperty 也會被擋。
    // 換上一份可寫的淺拷貝，應用程式在呼叫時才讀 window.LightweightCharts，
    // 所以拿到的是包裝後的版本。
    let host = lc;
    if (!Object.isExtensible(lc) || !Object.getOwnPropertyDescriptor(lc, "createChart").writable) {
      host = Object.assign({}, lc);
      window.LightweightCharts = host;
    }
    try {
      host.createChart = wrapped;
      host.__popostockFlowHooked = true;
    } catch (error) {
      // 掛不上就放棄同步，圖表照畫——寧可少一個聯動，也不要整支覆蓋層死掉。
      console.warn("[popostock] 無法攔截 createChart，加減碼圖表將不與大盤同步", error);
      charts.set(null, null);
    }
  }
  hookCreateChart();
  // LightweightCharts 可能比本檔晚載入，短暫重試直到掛上
  const hookTimer = window.setInterval(() => {
    hookCreateChart();
    const cur = window.LightweightCharts;
    if (cur && (cur.__popostockFlowHooked || charts.has(null))) {
      window.clearInterval(hookTimer);
    }
  }, 120);
  window.setTimeout(() => window.clearInterval(hookTimer), 60000);

  function mainChart() {
    // 大盤那張的容器是 .nav-chart-stage，且不是比較區塊用的
    for (const [container, chart] of charts) {
      if (!container || !container.closest) continue;
      const stage = container.closest(".nav-chart-stage");
      if (stage && !stage.classList.contains("market-comparison-stage")) return chart;
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
      "<span>時間軸跟隨大盤 K 線 · 拖曳或縮放大盤即同步移動</span></div>" +
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
    stage.className = "nav-chart-stage market-comparison-stage";
    stage.style.height = "180px";
    block.appendChild(stage);

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
    keepSynced(chart);

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

  /* 單向同步：大盤 → 本圖。
     不做雙向：兩張圖的資料長度不同（大盤上萬根、本圖數十根），把範圍推回去
     會被夾取成不同值再彈回來，實測會把主圖重設成全區間。需求是「跟著大盤
     動」，單向就完全滿足。

     綁定要持續監看，不能只在建立時試一次：React 掛上 DOM 與建立圖表不在同
     一步，切換分頁時還會整個重建，實測有時綁得到、有時綁不到。 */
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
    const timer = window.setInterval(tick, 400);
    window.addEventListener("beforeunload", () => window.clearInterval(timer));
    return () => bound !== null;
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
