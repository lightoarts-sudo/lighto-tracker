(() => {
  "use strict";

  // 在「共同持股統計」的範圍切換列加上一個「全球佈局」標籤，顯示海外佈局的
  // 主動式 ETF 手上握有哪些台股。
  //
  // .scope-switch 與表格都由 React 產生，所以這裡只 append，不插入既有子節點
  // 之間；切換時隱藏 React 的表格並在 section 末端顯示自己的面板。
  const SWITCH = ".scope-switch";
  const PANEL = "section.stats-panel";
  const TABLE_WRAP = ".stats-table-scroll";
  const CHIP_FLAG = "data-global-tw-chip";
  const VIEW_FLAG = "data-global-tw-view";
  const LABEL = "全球佈局";

  // 站台網址可能沒有結尾斜線，相對路徑會解析到根目錄，所以基準取自本腳本位置。
  const BASE = (() => {
    const self = document.currentScript && document.currentScript.src;
    if (self) return self.slice(0, self.lastIndexOf("/") + 1);
    const marker = "/popostock/";
    const at = location.pathname.indexOf(marker);
    if (at >= 0) return location.origin + location.pathname.slice(0, at + marker.length);
    return location.origin + "/popostock/";
  })();

  let payload = null;
  let loading = null;
  let active = false;

  function style() {
    if (document.getElementById("global-tw-style")) return;
    const el = document.createElement("style");
    el.id = "global-tw-style";
    el.textContent = [
      "[" + VIEW_FLAG + "]{padding:0 0 4px}",
      "[" + VIEW_FLAG + "] .gt-note{color:#667483;font-size:12.5px;line-height:1.75;margin:2px 0 12px}",
      "[" + VIEW_FLAG + "] .gt-sum{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 14px}",
      "[" + VIEW_FLAG + "] .gt-stat{background:#f4f7fb;border:1px solid #e2e8f2;border-radius:12px;",
      "padding:10px 16px;min-width:132px}",
      "[" + VIEW_FLAG + "] .gt-stat b{display:block;font-size:21px;color:#12295c;font-weight:900;line-height:1.3}",
      "[" + VIEW_FLAG + "] .gt-stat span{font-size:12.5px;color:#667483;font-weight:700}",
      "[" + VIEW_FLAG + "] .gt-funds{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}",
      "[" + VIEW_FLAG + "] .gt-fund{font-size:12px;font-weight:800;border-radius:999px;padding:3px 11px;",
      "background:#eef2f8;color:#5b6b80;border:1px solid #dde5f0}",
      "[" + VIEW_FLAG + "] .gt-fund.has{background:#12295c;border-color:#12295c;color:#fff}",
      "[" + VIEW_FLAG + "] .gt-scroll{overflow-x:auto}",
      "[" + VIEW_FLAG + "] table{width:100%;border-collapse:collapse;font-size:14px;min-width:720px}",
      "[" + VIEW_FLAG + "] th{text-align:right;padding:10px 12px;color:#cfdcf0;font-weight:800;",
      "font-size:12.5px;white-space:nowrap;border-bottom:2px solid #e2e8f2}",
      "[" + VIEW_FLAG + "] th:first-child,[" + VIEW_FLAG + "] th:last-child{text-align:left}",
      "[" + VIEW_FLAG + "] td{text-align:right;padding:11px 12px;border-bottom:1px solid #eef2f7;",
      "color:#12295c;font-variant-numeric:tabular-nums;white-space:nowrap}",
      "[" + VIEW_FLAG + "] td:first-child,[" + VIEW_FLAG + "] td:last-child{text-align:left}",
      "[" + VIEW_FLAG + "] tbody tr:hover{background:#f8fafd}",
      "[" + VIEW_FLAG + "] .gt-name{font-weight:800}",
      "[" + VIEW_FLAG + "] .gt-name i{font-style:normal;color:#8b98ab;font-weight:700;margin-left:7px;font-size:12.5px}",
      "[" + VIEW_FLAG + "] .gt-amt{font-weight:900}",
      "[" + VIEW_FLAG + "] .gt-who{color:#5b6b80;font-size:12.5px;font-weight:700;white-space:normal}",
      "[" + VIEW_FLAG + "] .gt-empty{padding:40px 0;text-align:center;color:#8b98ab;font-weight:700}",
    ].join("");
    document.head.appendChild(el);
  }

  const num = (value, digits) =>
    value === null || value === undefined
      ? "—"
      : Number(value).toLocaleString("zh-TW", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });

  function load() {
    if (payload || loading) return loading;
    loading = fetch(BASE + "data/global-etf-tw-holdings.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        payload = data;
        if (active) renderView();
      })
      .catch(() => {});
    return loading;
  }

  function renderView() {
    const view = document.querySelector("[" + VIEW_FLAG + "]");
    if (!view) return;
    if (!payload) {
      view.innerHTML = '<div class="gt-empty">資料載入中…</div>';
      return;
    }
    const rows = payload.stocks || [];
    const body = rows
      .map((s) => {
        const who = (s.etfs || [])
          .map((e) => e.code)
          .join("、");
        return (
          '<tr><td class="gt-name">' + s.stockName + "<i>" + s.stockCode + "</i></td>" +
          "<td>" + s.etfCount + "</td>" +
          "<td>" + num(s.totalLots, 0) + "</td>" +
          "<td>" + num(s.closePrice, 2) + "</td>" +
          '<td class="gt-amt">' + num(s.totalAmountTwd / 1e8, 2) + "</td>" +
          '<td class="gt-who">' + who + "</td></tr>"
        );
      })
      .join("");
    const funds = (payload.funds || [])
      .map(
        (f) =>
          '<span class="gt-fund' + (f.domesticCount ? " has" : "") + '">' +
          f.code + " " + f.name +
          (f.domesticCount ? "　台股 " + f.domesticWeightPct + "%" : "　無台股") +
          "</span>",
      )
      .join("");
    view.innerHTML =
      '<div class="gt-sum">' +
      '<div class="gt-stat"><b>' + payload.globalFundCount + "</b><span>全球佈局 ETF</span></div>" +
      '<div class="gt-stat"><b>' + payload.holdingFundCount + "</b><span>其中持有台股</span></div>" +
      '<div class="gt-stat"><b>' + payload.stockCount + "</b><span>台股檔數</span></div>" +
      '<div class="gt-stat"><b>' + num(payload.totalAmountTwd / 1e8, 2) + "</b><span>台股部位（億元）</span></div>" +
      "</div>" +
      '<div class="gt-funds">' + funds + "</div>" +
      '<div class="gt-scroll"><table><thead><tr>' +
      "<th>股票</th><th>持有檔數</th><th>合計張數</th><th>收盤價</th>" +
      "<th>部位金額（億）↓</th><th>持有的 ETF</th>" +
      "</tr></thead><tbody>" +
      (body || '<tr><td colspan="6" class="gt-empty">目前沒有台股部位</td></tr>') +
      "</tbody></table></div>" +
      '<p class="gt-note">' + (payload.methodology || "") +
      "　資料更新 " + (payload.generatedAt || "").replace("T", " ").slice(0, 16) + "。</p>";
  }

  function reactChips(bar) {
    return Array.from(bar.querySelectorAll("button")).filter(
      (b) => !b.hasAttribute(CHIP_FLAG),
    );
  }

  function show(on) {
    const panel = document.querySelector(PANEL);
    const bar = panel && panel.querySelector(SWITCH);
    if (!panel || !bar) return;
    active = on;
    const chip = bar.querySelector("[" + CHIP_FLAG + "]");
    if (chip) chip.classList.toggle("is-active", on);

    // React 自己的 chip 只做視覺上的取消選取，不動它們的狀態。
    reactChips(bar).forEach((b) => {
      if (on) {
        if (b.classList.contains("is-active")) {
          b.dataset.globalTwWas = "1";
          b.classList.remove("is-active");
        }
      } else if (b.dataset.globalTwWas === "1") {
        b.classList.add("is-active");
        delete b.dataset.globalTwWas;
      }
    });

    Array.from(panel.children).forEach((node) => {
      if (node.hasAttribute(VIEW_FLAG) || node.contains(bar)) return;
      if (on) {
        if (node.dataset.globalTwHidden === undefined) {
          node.dataset.globalTwHidden = node.style.display || "";
        }
        node.style.display = "none";
      } else if (node.dataset.globalTwHidden !== undefined) {
        node.style.display = node.dataset.globalTwHidden;
        delete node.dataset.globalTwHidden;
      }
    });

    let view = panel.querySelector("[" + VIEW_FLAG + "]");
    if (on) {
      if (!view) {
        view = document.createElement("div");
        view.setAttribute(VIEW_FLAG, "");
        panel.appendChild(view);
      }
      view.style.display = "";
      load();
      renderView();
    } else if (view) {
      view.style.display = "none";
    }
  }

  function attach() {
    // .scope-switch 不是共同持股統計專用的——績效排行頁也用同一個 class。
    // 只有在同一個 section.stats-panel 底下的那一列才是我們要掛的，否則標籤會
    // 出現在其他分頁而點了沒反應（面板不存在）。
    const panel = document.querySelector(PANEL);
    const bar = panel && panel.querySelector(SWITCH);
    if (!bar || bar.querySelector("[" + CHIP_FLAG + "]")) return;
    const chip = document.createElement("button");
    chip.type = "button";
    chip.setAttribute(CHIP_FLAG, "");
    chip.textContent = LABEL;
    chip.addEventListener("click", () => show(true));
    // 一律 append 到最後，不插入 React 既有子節點之間。
    bar.appendChild(chip);
    // 點回 React 的任何一個 chip 就還原。
    bar.addEventListener("click", (event) => {
      const target = event.target.closest("button");
      if (target && !target.hasAttribute(CHIP_FLAG) && active) show(false);
    });
  }

  function start() {
    style();
    attach();
    let queued = false;
    const schedule = () => {
      if (queued) return;
      queued = true;
      // 背景分頁不會觸發 requestAnimationFrame，改用 setTimeout。
      setTimeout(() => {
        queued = false;
        // 離開共同持股統計時面板不再存在，狀態要跟著歸零，
        // 否則回到該頁會以為仍在「全球佈局」檢視。
        if (!document.querySelector(PANEL)) { active = false; return; }
        attach();
        if (active && !document.querySelector("[" + VIEW_FLAG + "]")) show(true);
      }, 60);
    };
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      attach();
      const bar = document.querySelector(PANEL + " " + SWITCH);
      if ((bar && bar.querySelector("[" + CHIP_FLAG + "]")) || attempts >= 40) clearInterval(timer);
    }, 500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
