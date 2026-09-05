/*
 * 主動式 ETF 的衍生品部位。
 *
 * 官方持股揭露分成「股票」與「衍生品」兩個資產分類，站上的加減碼只涵蓋前者
 * ——共識以張數計算並用交易所收盤價計價，把以「口」為單位的期貨混進去，金額
 * 與張數都會失真。但整塊丟掉等於漏報：00981A 在 2026-09-04 持有 679 口台指期
 * 多方、佔淨值 2.24%（63 億），站上原本一個字都沒有。
 *
 * 所以另立一區掛在加減碼卡片下方，並帶出與前一次揭露的口數變化。
 */
(function () {
  "use strict";

  var DATA_URL = "data/active-etf-derivatives.json";
  var FLAG = "data-etf-derivatives";
  var payload = null;
  var loading = null;

  function baseUrl() {
    var base = document.querySelector("base[href]");
    if (base) {
      return new URL(base.getAttribute("href"), window.location.href).href.replace(/\/$/, "");
    }
    var match = window.location.href.match(/^(https?:\/\/[^/]+\/popostock)/);
    return match ? match[1] : "";
  }

  function style() {
    if (document.getElementById("etf-derivatives-style")) return;
    var element = document.createElement("style");
    element.id = "etf-derivatives-style";
    element.textContent = [
      ".etf-derivatives{margin:14px 0 0;border:1px solid #d6dee6;border-radius:10px;",
      "background:#f7fafc;padding:12px 14px}",
      ".etf-derivatives h4{margin:0 0 3px;color:#06275f;font-size:14px;font-weight:900;",
      "display:flex;align-items:baseline;justify-content:space-between;gap:10px}",
      ".etf-derivatives h4 span{color:#7b8aa6;font-size:11.5px;font-weight:800}",
      ".etf-derivatives .note{margin:0 0 9px;color:#8b98ab;font-size:11.5px;font-weight:700;line-height:1.6}",
      ".etf-derivatives .row{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;",
      "padding:7px 0;border-top:1px solid #e6ecf2}",
      ".etf-derivatives .row:first-of-type{border-top:0}",
      ".etf-derivatives .nm{color:#12295c;font-weight:900;font-size:13.5px}",
      ".etf-derivatives .side{border-radius:999px;padding:1px 8px;font-size:11px;font-weight:900;color:#fff}",
      ".etf-derivatives .side.long{background:#c23d4b}.etf-derivatives .side.short{background:#16845b}",
      ".etf-derivatives .mth{color:#7b8aa6;font-size:11.5px;font-weight:800}",
      ".etf-derivatives .num{margin-left:auto;color:#12295c;font-weight:900;font-size:13.5px;",
      "font-variant-numeric:tabular-nums;white-space:nowrap}",
      ".etf-derivatives .chg{font-size:12.5px;font-weight:900;white-space:nowrap}",
      ".etf-derivatives .chg.up{color:#c23d4b}.etf-derivatives .chg.dn{color:#16845b}",
      ".etf-derivatives .chg.na{color:#a8b3c4}",
    ].join("");
    document.head.appendChild(element);
  }

  function load() {
    if (payload || loading) return loading;
    loading = fetch(baseUrl() + "/" + DATA_URL, { cache: "no-store" })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        payload = data || { instruments: [] };
        scan();
      })
      .catch(function () {
        payload = { instruments: [] };
      });
    return loading;
  }

  function money(value) {
    if (typeof value !== "number" || !isFinite(value) || !value) return "";
    return value >= 1e8
      ? "　" + (value / 1e8).toFixed(2) + " 億"
      : "　" + Math.round(value / 1e4).toLocaleString("en-US") + " 萬";
  }

  function rowHtml(row) {
    var change = row.contractChange;
    var chg;
    if (typeof change !== "number") {
      chg = '<span class="chg na">首次揭露</span>';
    } else if (change === 0) {
      chg = '<span class="chg na">持平</span>';
    } else {
      chg =
        '<span class="chg ' + (change > 0 ? "up" : "dn") + '">' +
        (change > 0 ? "+" : "−") + Math.abs(change).toLocaleString("en-US") + " 口</span>";
    }
    var side = row.position === "S" ? "short" : "long";
    return (
      '<div class="row"><span class="nm">' + (row.name || row.code) + "</span>" +
      '<span class="side ' + side + '">' + (row.positionLabel || row.position || "") + "</span>" +
      '<span class="mth">契約 ' + (row.contractMonth || "—") + "</span>" +
      '<span class="num">' + Number(row.contracts || 0).toLocaleString("en-US") + " 口" +
      money(row.amountTwd) + "　權重 " + row.weight + "%</span>" + chg + "</div>"
    );
  }

  function panelFor(code) {
    var item = ((payload && payload.instruments) || []).find(function (entry) {
      return entry.code === code;
    });
    if (!item || !item.positions.length) return null;
    var box = document.createElement("div");
    box.className = "etf-derivatives";
    box.setAttribute(FLAG, code);
    box.innerHTML =
      "<h4>衍生品部位<span>官方揭露 " + item.sourceDate +
      (item.comparisonDate ? "　比較 " + item.comparisonDate : "　首次揭露") + "</span></h4>" +
      '<p class="note">期貨以「口」計價，不計入上方的加減碼與共識統計' +
      "（那些以張數計算）。變動以同一契約年月比較，換月不相減。</p>" +
      item.positions.map(rowHtml).join("");
    return box;
  }

  function scan() {
    if (!payload) return;
    document.querySelectorAll(".active-etf-change-card").forEach(function (card) {
      var header = card.querySelector("header span");
      if (!header) return;
      var code = (header.textContent.split("·")[0] || "").trim();
      if (!/^[0-9]{5}[A-Z]$/.test(code)) return;
      if (card.querySelector("[" + FLAG + '="' + code + '"]')) return;
      var panel = panelFor(code);
      // 只 append，不插進 React 的子節點之間——這個站踩過 NotFoundError。
      if (panel) card.appendChild(panel);
    });
  }

  function boot() {
    style();
    load();
    // React 重繪卡片時會把這一區丟掉，要補回來。
    new MutationObserver(function () {
      scan();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
