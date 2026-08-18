(() => {
  "use strict";

  // 在「主動式 ETF 加減碼」每張卡的深藍標題列內，補上該檔當日的買賣統計。
  //
  // 卡片本身由 React 產生，所以這裡只做兩件事：append 到 <header> 的最後，
  // 以及在 React 重繪後重新補上。絕不插入既有子節點之間（會 NotFoundError）。
  const CARD = ".active-etf-change-card";
  const FLAG = "data-ac-stats";
  const cache = new Map();

  function style() {
    if (document.getElementById("ac-stats-style")) return;
    const element = document.createElement("style");
    element.id = "ac-stats-style";
    element.textContent = [
      // 深藍底，所以全部用亮色；數字用等寬避免逐張跳動。
      "[" + FLAG + "]{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;",
      "margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.16);",
      "font-size:12.5px;font-weight:800;color:#cfdcf0;font-variant-numeric:tabular-nums}",
      "[" + FLAG + "] i{font-style:normal;color:#9fb3d9;font-weight:700;margin-right:4px}",
      "[" + FLAG + "] b{font-weight:900}",
      "[" + FLAG + "] b.up{color:#ff8a80}",
      "[" + FLAG + "] b.down{color:#7ee2a8}",
      "[" + FLAG + "] b.flat{color:#cfdcf0}",
      "[" + FLAG + "] .net{margin-left:auto}",
    ].join("");
    document.head.appendChild(element);
  }

  const money = (value) => {
    const yi = Math.abs(value) / 1e8;
    // 小於 0.05 億會四捨五入成 0.0，看起來像沒有異動，改用門檻表示。
    if (value !== 0 && yi < 0.05) return "<0.1";
    return yi.toFixed(yi >= 100 ? 0 : 1);
  };

  function summarise(payload) {
    const rows = (payload.holdings || []).filter(
      (h) => h.action && h.action !== "hold" && (h.lotChange || 0) !== 0,
    );
    let buyCount = 0, sellCount = 0, buySum = 0, sellSum = 0, unpriced = 0;
    rows.forEach((h) => {
      const amount = h.amountTwd;
      // 美股成分股沒有台股收盤價（00989A 持有的 Unity 等），金額會是 null；
      // 計入檔數但不計入金額，否則總和會少算而看不出來。
      if (typeof amount !== "number") unpriced += 1;
      if ((h.lotChange || 0) > 0) { buyCount += 1; buySum += amount || 0; }
      else { sellCount += 1; sellSum += amount || 0; }
    });
    return { buyCount, sellCount, buySum, sellSum, net: buySum + sellSum, unpriced };
  }

  function render(header, s) {
    let box = header.querySelector("[" + FLAG + "]");
    if (!box) {
      box = document.createElement("div");
      box.setAttribute(FLAG, "");
      header.appendChild(box);
    }
    // 0 檔時不印「−0.0 億」；有異動但金額全為 0（成分股無台股報價）印破折號，
    // 不要讓「沒查到價格」看起來像「金額為零」。
    const side = (label, klass, sign, count, sum) => {
      if (!count) return "<span><i>" + label + "</i>0 檔</span>";
      const value = sum === 0 ? "—" : sign + money(sum);
      return '<span><i>' + label + "</i>" + count + " 檔 " +
        '<b class="' + klass + '">' + value + "</b>" + (sum === 0 ? "" : " 億") + "</span>";
    };
    const netClass = s.net > 0 ? "up" : s.net < 0 ? "down" : "flat";
    const netSign = s.net > 0 ? "+" : s.net < 0 ? "−" : "";
    const netValue = s.net === 0 ? "—" : netSign + money(s.net);
    box.innerHTML =
      side("加碼", "up", "+", s.buyCount, s.buySum) +
      side("減碼", "down", "−", s.sellCount, s.sellSum) +
      '<span class="net"><i>淨額</i><b class="' + netClass + '">' + netValue + "</b>" +
      (s.net === 0 ? "" : " 億") +
      (s.unpriced ? '<i style="margin-left:6px">（' + s.unpriced + " 檔無台股報價未計）</i>" : "") +
      "</span>";
  }

  function load(code, date) {
    const key = code + "/" + date;
    if (!cache.has(key)) {
      cache.set(
        key,
        fetch("data/holding-changes/" + code + "/" + date + ".json", { cache: "no-store" })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null),
      );
    }
    return cache.get(key);
  }

  function decorate() {
    document.querySelectorAll(CARD).forEach((card) => {
      const header = card.querySelector("header");
      if (!header) return;
      const label = header.textContent || "";
      // 標題列格式為「00981A · 2026/08/18」。
      const match = label.match(/(\d{4,6}[A-Z]?)\s*·\s*(\d{4})\/(\d{2})\/(\d{2})/);
      if (!match) return;
      const code = match[1];
      const date = match[2] + "-" + match[3] + "-" + match[4];
      if (header.dataset.acStatsKey === code + "/" + date) return;
      header.dataset.acStatsKey = code + "/" + date;
      load(code, date).then((payload) => {
        if (!payload || header.dataset.acStatsKey !== code + "/" + date) return;
        render(header, summarise(payload));
      });
    });
  }

  function start() {
    style();
    decorate();
    // React 換頁／換日期會整批重繪，重繪後既有節點被丟棄，必須重新補上。
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; decorate(); });
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
