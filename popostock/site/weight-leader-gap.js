(() => {
  "use strict";

  // The production bundle is prebuilt, so this page is added as an overlay:
  // its tab button is appended as the LAST child of the tab strip and its
  // panel as the LAST child of the shell. Nothing is ever inserted between
  // React's own children — doing that throws NotFoundError on the next render.
  const TAB_LABEL = "權值股回前高";
  const DATA_URL = "data/weight-leader-gap.json";
  const TAB_FLAG = "data-weight-gap-tab";
  const PANEL_FLAG = "data-weight-gap-panel";

  let payload = null;
  let loading = null;
  let active = false;

  function style() {
    if (document.getElementById("weight-gap-style")) return;
    const element = document.createElement("style");
    element.id = "weight-gap-style";
    element.textContent = [
      ".weight-gap-panel{padding:4px 0 28px}",
      ".weight-gap-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 18px;margin:0 0 6px}",
      ".weight-gap-head h2{font-size:20px;font-weight:800;color:#12295c;margin:0}",
      ".weight-gap-head .meta{color:#667483;font-size:13px;font-weight:700}",
      ".weight-gap-summary{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 16px}",
      ".weight-gap-stat{background:#f4f7fb;border:1px solid #e2e8f2;border-radius:12px;padding:10px 16px;min-width:150px}",
      ".weight-gap-stat b{display:block;font-size:22px;color:#12295c;font-weight:900;line-height:1.25}",
      ".weight-gap-stat span{font-size:12.5px;color:#667483;font-weight:700}",
      ".weight-gap-scroll{overflow-x:auto}",
      ".weight-gap-table{width:100%;border-collapse:collapse;font-size:14px;min-width:660px}",
      ".weight-gap-table th{text-align:right;padding:10px 12px;color:#5b6b80;font-weight:800;",
      "border-bottom:2px solid #e2e8f2;white-space:nowrap;font-size:12.5px}",
      ".weight-gap-table th:nth-child(1),.weight-gap-table th:nth-child(2){text-align:left}",
      ".weight-gap-table td{text-align:right;padding:11px 12px;border-bottom:1px solid #eef2f7;",
      "white-space:nowrap;font-variant-numeric:tabular-nums;color:#12295c}",
      ".weight-gap-table td:nth-child(1),.weight-gap-table td:nth-child(2){text-align:left}",
      ".weight-gap-table tbody tr:hover{background:#f8fafd}",
      ".weight-gap-rank{color:#8b98ab;font-weight:800}",
      ".weight-gap-name{font-weight:800}",
      ".weight-gap-name i{font-style:normal;color:#8b98ab;font-weight:700;margin-left:7px;font-size:12.5px}",
      ".weight-gap-need{color:#d92b2b;font-weight:900}",
      ".weight-gap-over{display:inline-block;background:#ffd43b;color:#12295c;font-weight:900;",
      "border-radius:999px;padding:2px 11px}",
      ".weight-gap-note{margin-top:14px;color:#667483;font-size:12.5px;line-height:1.7}",
      ".weight-gap-note a{color:#2f6fd0}",
      ".weight-gap-empty{padding:40px 0;text-align:center;color:#8b98ab;font-weight:700}",
    ].join("");
    document.head.appendChild(element);
  }

  function shell() {
    return document.querySelector(".tracker-shell");
  }

  function tabStrip() {
    return document.querySelector(".workspace-tabs");
  }

  function ourTab() {
    return document.querySelector("[" + TAB_FLAG + "]");
  }

  function ourPanel() {
    return document.querySelector("[" + PANEL_FLAG + "]");
  }

  function reactPanels() {
    const host = shell();
    if (!host) return [];
    const strip = tabStrip();
    if (!strip) return [];
    const children = Array.from(host.children);
    const index = children.indexOf(strip);
    return children
      .slice(index + 1)
      .filter((node) => !node.hasAttribute(PANEL_FLAG));
  }

  function number(value, digits) {
    return Number(value).toLocaleString("zh-TW", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function render() {
    const panel = ourPanel();
    if (!panel) return;
    if (!payload) {
      panel.innerHTML = '<div class="weight-gap-empty">資料載入中…</div>';
      return;
    }
    const rows = payload.instruments || [];
    if (!rows.length) {
      panel.innerHTML = '<div class="weight-gap-empty">目前沒有可顯示的資料。</div>';
      return;
    }
    const month = String(payload.peakMonth || "").replace("-", " 年 ") + " 月";
    const closeDate = rows[0].closeDate || "";
    const body = rows
      .map((row) => {
        const gap = row.abovePeak
          ? '<span class="weight-gap-over">已超越 ' +
            number(Math.abs(row.premiumPct), 2) +
            "%</span>"
          : '<span class="weight-gap-need">還要漲 ' + number(row.gapPct, 2) + "%</span>";
        return (
          "<tr><td class=\"weight-gap-rank\">" + row.rank + "</td>" +
          '<td class="weight-gap-name">' + row.name + "<i>" + row.code + "</i></td>" +
          "<td>" + number(row.weightPct, 4) + "%</td>" +
          "<td>" + number(row.close, 2) + "</td>" +
          "<td>" + number(row.peakClose, 2) + "</td>" +
          "<td>" + (row.peakCloseDate || "").slice(5) + "</td>" +
          "<td>" + gap + "</td></tr>"
        );
      })
      .join("");

    panel.innerHTML =
      '<div class="weight-gap-head"><h2>權值股回前高</h2>' +
      '<span class="meta">市值前 ' + rows.length + " 大成分股　|　基準：" + month +
      "最高收盤　|　收盤日 " + closeDate + "</span></div>" +
      '<div class="weight-gap-summary">' +
      '<div class="weight-gap-stat"><b>' + payload.abovePeakCount + " / " + rows.length +
      "</b><span>已站回六月高點</span></div>" +
      '<div class="weight-gap-stat"><b>' + number(payload.weightedGapPct, 2) +
      "%</b><span>加權缺口（全部回前高的指數空間）</span></div>" +
      '<div class="weight-gap-stat"><b>' + number(rows[0].gapPct, 2) +
      "%</b><span>台積電距前高</span></div>" +
      "</div>" +
      '<div class="weight-gap-scroll"><table class="weight-gap-table"><thead><tr>' +
      "<th>排行</th><th>證券</th><th>市值比重</th><th>最新收盤</th>" +
      "<th>六月最高收盤</th><th>高點日</th><th>距前高</th>" +
      "</tr></thead><tbody>" + body + "</tbody></table></div>" +
      '<p class="weight-gap-note">' + (payload.methodology || "") +
      "<br>排行與市值比重取自臺灣期貨交易所「臺灣證券交易所發行量加權股價指數成分股暨市值比重」；" +
      "價格取自證交所／櫃買中心每日收盤行情。<b>價格未還原除權息</b>，除息後的股價會使距前高幅度略為高估。" +
      "資料更新時間 " + (payload.generatedAt || "").replace("T", " ").slice(0, 16) +
      "。</p>";
  }

  function load() {
    if (payload || loading) return loading;
    loading = fetch(DATA_URL, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        payload = data;
        render();
      })
      .catch(() => {
        payload = null;
        const panel = ourPanel();
        if (panel) {
          panel.innerHTML = '<div class="weight-gap-empty">資料暫時無法載入。</div>';
        }
      });
    return loading;
  }

  function activate() {
    if (!ensure()) return;
    active = true;
    reactPanels().forEach((node) => {
      if (node.dataset.weightGapHidden === undefined) {
        node.dataset.weightGapHidden = node.style.display || "";
      }
      node.style.display = "none";
    });
    const panel = ourPanel();
    if (panel) panel.style.display = "";
    const tab = ourTab();
    if (tab) {
      tab.setAttribute("aria-selected", "true");
      tab.classList.add("is-active");
    }
    Array.from(document.querySelectorAll('.workspace-tabs [role="tab"]')).forEach((button) => {
      if (button.hasAttribute(TAB_FLAG)) return;
      button.setAttribute("aria-selected", "false");
      button.classList.remove("is-active");
    });
    render();
    load();
  }

  function deactivate() {
    active = false;
    reactPanels().forEach((node) => {
      if (node.dataset.weightGapHidden !== undefined) {
        node.style.display = node.dataset.weightGapHidden;
        delete node.dataset.weightGapHidden;
      } else {
        node.style.display = "";
      }
    });
    const panel = ourPanel();
    if (panel) panel.style.display = "none";
    const tab = ourTab();
    if (tab) {
      tab.setAttribute("aria-selected", "false");
      tab.classList.remove("is-active");
    }
  }

  function ensure() {
    const strip = tabStrip();
    const host = shell();
    if (!strip || !host) return false;
    style();
    if (!ourTab()) {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", "false");
      button.setAttribute(TAB_FLAG, "");
      button.textContent = TAB_LABEL;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        activate();
      });
      strip.appendChild(button);
    }
    if (!ourPanel()) {
      const panel = document.createElement("section");
      panel.className = "weight-gap-panel";
      panel.setAttribute(PANEL_FLAG, "");
      panel.style.display = "none";
      host.appendChild(panel);
    }
    return true;
  }

  document.addEventListener(
    "click",
    (event) => {
      const button = event.target.closest?.('.workspace-tabs [role="tab"]');
      if (!button || button.hasAttribute(TAB_FLAG)) return;
      if (active) deactivate();
    },
    true,
  );

  function sync() {
    if (!ensure()) return;
    if (active) {
      // React re-rendered the panel underneath us; hide it again.
      reactPanels().forEach((node) => {
        node.style.display = "none";
      });
      const panel = ourPanel();
      if (panel && panel.style.display === "none") panel.style.display = "";
    }
  }

  function boot() {
    ensure();
    new MutationObserver(() => {
      sync();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
