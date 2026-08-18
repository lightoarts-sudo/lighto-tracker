(() => {
  "use strict";

  // 站台網址可能是 /popostock/ 也可能是 /popostock（無結尾斜線）。後者會讓
  // 相對路徑 "data/..." 解析到網站根目錄而 404，所以基準路徑取自本腳本的位置。
  var ASSET_BASE = (function () {
    var self = document.currentScript && document.currentScript.src;
    if (self) return self.slice(0, self.lastIndexOf("/") + 1);
    var marker = "/popostock/";
    var at = location.pathname.indexOf(marker);
    if (at >= 0) return location.origin + location.pathname.slice(0, at + marker.length);
    return location.origin + "/popostock/";
  })();


  // Overlay tab, same contract as weight-leader-gap.js: the button is appended
  // as the LAST child of the tab strip and the panel as the LAST child of the
  // shell. Nothing is inserted between React's own children.
  const TAB_LABEL = "配息資訊";
  const DATA_URL = ASSET_BASE + "data/dividend-schedule.json";
  const TAB_FLAG = "data-dividend-tab";
  const PANEL_FLAG = "data-dividend-panel";
  const KLINE_INDEX_URL = ASSET_BASE + "data/consensus-stock-kline-index.json";
  // The same file the 績效排行 page reads, so a YTD shown here can never drift
  // from the one shown there.
  const RANKING_URL = ASSET_BASE + "data/performance-ranking.json";

  let payload = null;
  let ranking = null;    // code -> YTD %
  let loading = null;
  let active = false;
  let filter = "all";
  let view = "calendar";
  // Starts empty on purpose: an all-checked calendar shows every ETF paying in
  // every month, which is the same as showing nothing.
  let selected = new Set();

  function style() {
    if (document.getElementById("dividend-style")) return;
    const element = document.createElement("style");
    element.id = "dividend-style";
    element.textContent = [
      ".dividend-panel{background:#fff;border:1px solid #c8d6e8;border-radius:8px;",
      "box-shadow:0 14px 34px rgba(3,24,63,.1);padding:20px 20px 24px}",
      ".dividend-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 18px;margin:0 0 6px}",
      ".dividend-head h2{font-size:20px;font-weight:800;color:#12295c;margin:0}",
      ".dividend-head .meta{color:#667483;font-size:13px;font-weight:700}",
      ".dividend-sum{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}",
      ".dividend-stat{background:#f4f7fb;border:1px solid #e2e8f2;border-radius:12px;padding:10px 16px;min-width:140px}",
      ".dividend-stat b{display:block;font-size:22px;color:#12295c;font-weight:900;line-height:1.25}",
      ".dividend-stat span{font-size:12.5px;color:#667483;font-weight:700}",
      ".dividend-filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}",
      ".dividend-filters button{border:1px solid #c8d6e8;background:#fff;color:#5b6b80;",
      "font-size:13px;font-weight:800;border-radius:999px;padding:6px 15px;cursor:pointer}",
      ".dividend-filters button.is-on{background:#12295c;border-color:#12295c;color:#fff}",
      ".dividend-scroll{overflow-x:auto}",
      ".dividend-table{width:100%;border-collapse:collapse;font-size:14px;min-width:760px}",
      ".dividend-table th{text-align:right;padding:10px 12px;color:#cfdcf0;font-weight:800;",
      "border-bottom:2px solid #e2e8f2;white-space:nowrap;font-size:12.5px}",
      ".dividend-table th:nth-child(1),.dividend-table th:nth-child(2){text-align:left}",
      ".dividend-table td{text-align:right;padding:11px 12px;border-bottom:1px solid #eef2f7;",
      "white-space:nowrap;font-variant-numeric:tabular-nums;color:#12295c}",
      ".dividend-table td:nth-child(1),.dividend-table td:nth-child(2){text-align:left}",
      ".dividend-table tbody tr:hover{background:#f8fafd}",
      ".dividend-name{font-weight:800}",
      ".dividend-name i{font-style:normal;color:#8b98ab;font-weight:700;margin-left:7px;font-size:12.5px}",
      ".dividend-tag{display:inline-block;font-size:11.5px;font-weight:800;border-radius:999px;",
      "padding:1px 9px;margin-left:7px;background:#e9edf4;color:#5b6b80}",
      ".dividend-tag.act{background:#ffe9c9;color:#8a5a12}",
      ".dividend-next{color:#12295c;font-weight:900}",
      ".dividend-next.soon{background:#ffd43b;border-radius:999px;padding:2px 10px}",
      ".dividend-none{color:#a8b3c4}",
      ".dividend-yield{font-weight:900;color:#d92b2b}",
      ".dividend-note{margin-top:14px;color:#667483;font-size:12.5px;line-height:1.7}",
      ".dividend-empty{padding:40px 0;text-align:center;color:#8b98ab;font-weight:700}",
      ".dividend-cal{width:100%;border-collapse:collapse;font-size:13.5px;min-width:760px}",
      ".dividend-cal th{padding:9px 4px;color:#cfdcf0;font-weight:800;font-size:12.5px;",
      "border-bottom:2px solid #e2e8f2;text-align:center;white-space:nowrap}",
      ".dividend-cal th.who{text-align:left;padding-left:10px;min-width:230px}",
      ".dividend-cal td{padding:7px 4px;border-bottom:1px solid #eef2f7;text-align:center;",
      "font-size:16px;line-height:1.2}",
      ".dividend-cal td.who{text-align:left;padding-left:10px;font-size:13.5px;color:#12295c;font-weight:800}",
      ".dividend-cal tbody tr:hover{background:#f8fafd}",
      ".dividend-cal tr.off td.who{color:#a8b3c4;font-weight:700}",
      ".dividend-cal label{display:flex;align-items:center;gap:8px;cursor:pointer}",
      ".dividend-cal input{width:15px;height:15px;accent-color:#12295c;flex:none;margin:0}",
      ".dividend-cal .code{color:#8b98ab;font-weight:700;font-size:12px}",
      ".dividend-cal td.hit{background:#fffbe9}",
      ".dividend-cal td.dim{color:#dfe5ee}",
      ".dividend-cal td.hit.plan{background:#f6f8fc}",
      ".dividend-cal td.hit.plan span,.dividend-cal td.hit.plan{opacity:.42}",
      ".dividend-legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0 0 10px;",
      "color:#667483;font-size:12.5px;font-weight:700}",
      ".dividend-legend b{font-weight:400}",
      ".dividend-legend b.plan{opacity:.42}",
      ".dividend-views{display:flex;gap:8px;margin:0 0 12px}",
      ".dividend-views button{border:1px solid #c8d6e8;background:#fff;color:#5b6b80;font-size:13px;",
      "font-weight:800;border-radius:var(--radius,8px);padding:7px 16px;cursor:pointer}",
      ".dividend-views button.is-on{background:#ffd43b;border-color:#e8bd22;color:#12295c}",
      ".dividend-bulk{margin-left:auto;display:flex;gap:8px}",
      ".dividend-cal th .mn{display:block}",
      ".dividend-cal th .cnt{display:block;margin-top:2px;font-size:11.5px;font-weight:900;color:#ffd43b}",
      ".dividend-cal th .cnt.zero{color:#7f93bb}",
      ".dividend-cal th.who .hint{display:block;font-weight:700;font-size:11.5px;color:#9fb3d9;margin-top:2px}",
      ".dividend-cal .ytd{margin-left:auto;font-weight:900;font-size:12.5px;",
      "color:#d92b2b;font-variant-numeric:tabular-nums}",
      ".dividend-cal .ytd.dn{color:#1a7a3c}",
      ".dividend-cal .ytd.na{color:#c3ccda}",
    ].join("");
    document.head.appendChild(element);
  }

  const shell = () => document.querySelector(".tracker-shell");
  const strip = () => document.querySelector(".workspace-tabs");
  const ourTab = () => document.querySelector("[" + TAB_FLAG + "]");
  const ourPanel = () => document.querySelector("[" + PANEL_FLAG + "]");

  function reactPanels() {
    const host = shell();
    const bar = strip();
    if (!host || !bar) return [];
    const children = Array.from(host.children);
    return children.slice(children.indexOf(bar) + 1).filter((n) => !n.hasAttribute(PANEL_FLAG));
  }

  function num(value, digits) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("zh-TW", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function rows() {
    const all = (payload && payload.instruments) || [];
    if (filter === "upcoming") return all.filter((i) => i.nextExDate);
    if (filter === "monthly") return all.filter((i) => i.cadence === "月配");
    if (filter === "active") return all.filter((i) => i.group === "activeEtfs");
    if (filter === "none") return all.filter((i) => !i.payoutCount);
    return all.filter((i) => i.payoutCount);
  }

  function ytdOf(code) {
    const value = ranking && ranking[code];
    return value === undefined || value === null ? null : value;
  }

  function calendarRows() {
    // Ranked by this year's return, best first. An ETF the ranking has no YTD
    // for (too recently listed to have a start-of-year price) sorts last rather
    // than being treated as 0%.
    return ((payload && payload.instruments) || [])
      .filter((i) => i.payoutCount)
      .slice()
      .sort((a, b) => {
        const x = ytdOf(a.code);
        const y = ytdOf(b.code);
        if (x === null && y === null) return a.code < b.code ? -1 : 1;
        if (x === null) return 1;
        if (y === null) return -1;
        return y - x;
      });
  }

  function renderCalendar() {
    const list = calendarRows();
    // How many of the *checked* ETFs distribute in each month — the point of
    // the calendar is spotting the thin months once a portfolio is picked.
    const perMonth = Array.from({ length: 12 }, () => 0);
    list.forEach((i) => {
      if (!selected.has(i.code)) return;
      // 計數用「預期配息月份」而非只有已發生的，否則剛掛牌的季配 ETF 會讓
      // 下半年看起來完全沒有配息。
      (i.expectedMonths || i.payoutMonths || []).forEach((m) => {
        if (m >= 1 && m <= 12) perMonth[m - 1] += 1;
      });
    });
    const any = selected.size > 0;
    const head =
      '<tr><th class="who">ETF（勾選以顯示）<span class="hint">依今年以來報酬排序</span></th>' +
      Array.from({ length: 12 }, (_, n) =>
        '<th><span class="mn">' + (n + 1) + "月</span>" +
        '<span class="cnt' + (any && perMonth[n] === 0 ? " zero" : "") + '">' +
        (any ? perMonth[n] + " 次" : "—") + "</span></th>"
      ).join("") + "</tr>";
    const body = list
      .map((i) => {
        const on = selected.has(i.code);
        const paid = new Set(i.payoutMonths || []);
        const planned = new Set(i.announcedMonths || []);
        const cells = Array.from({ length: 12 }, (_, n) => {
          const month = n + 1;
          if (!on || (!paid.has(month) && !planned.has(month))) {
            return '<td class="dim">·</td>';
          }
          // 已除息與僅為公告預期，必須看得出差別，否則等於宣稱錢已經配了。
          return paid.has(month)
            ? '<td class="hit">💰</td>'
            : '<td class="hit plan" title="投信公告之配息月份，尚未除息">💰</td>';
        }).join("");
        const ytd = ytdOf(i.code);
        const perf =
          ytd === null
            ? '<span class="ytd na">—</span>'
            : '<span class="ytd' + (ytd < 0 ? " dn" : "") + '">' +
              (ytd >= 0 ? "+" : "") + num(ytd, 1) + "%</span>";
        return (
          '<tr class="' + (on ? "" : "off") + '"><td class="who"><label>' +
          '<input type="checkbox" data-code="' + i.code + '"' + (on ? " checked" : "") + ">" +
          "<span>" + i.name + ' <span class="code">' + i.code + "</span></span>" +
          perf + "</label></td>" + cells + "</tr>"
        );
      })
      .join("");
    return (
      '<div class="dividend-scroll"><table class="dividend-cal"><thead>' + head +
      "</thead><tbody>" + body + "</tbody></table></div>"
    );
  }

  function render() {
    const panel = ourPanel();
    if (!panel) return;
    if (!payload) {
      panel.innerHTML = '<div class="dividend-empty">資料載入中…</div>';
      return;
    }
    const list = rows();
    const soon = payload.instruments.filter((i) => i.nextExDate);
    const body = list
      .map((i) => {
        const next = i.nextExDate
          ? '<span class="dividend-next soon">' + i.nextExDate.slice(5) + "</span>"
          : '<span class="dividend-none">未公告</span>';
        const tag =
          '<span class="dividend-tag' + (i.group === "activeEtfs" ? " act" : "") + '">' +
          i.groupLabel + "</span>";
        return (
          '<tr><td class="dividend-name">' + i.name + "<i>" + i.code + "</i>" + tag + "</td>" +
          "<td>" + (i.cadence || "—") + "</td>" +
          "<td>" + (i.lastExDate || "—") + "</td>" +
          "<td>" + num(i.lastAmount, 3) + "</td>" +
          "<td>" + num(i.trailingAmount, 2) + "</td>" +
          '<td class="dividend-yield">' +
          (i.trailingYieldPct === null || i.trailingYieldPct === undefined
            ? "—"
            : num(i.trailingYieldPct, 2) + "%") + "</td>" +
          "<td>" + i.payoutCount + "</td>" +
          "<td>" + next + "</td></tr>"
        );
      })
      .join("");

    const chip = (key, label) =>
      '<button type="button" data-filter="' + key + '"' +
      (filter === key ? ' class="is-on"' : "") + ">" + label + "</button>";

    panel.innerHTML =
      '<div class="dividend-head"><h2>配息資訊</h2>' +
      '<span class="meta">追蹤 ' + payload.instrumentCount + " 檔 ETF　|　資料日 " +
      (payload.asOf || "") + "</span></div>" +
      '<div class="dividend-sum">' +
      '<div class="dividend-stat"><b>' + payload.payingCount + " / " + payload.instrumentCount +
      "</b><span>有配息紀錄</span></div>" +
      '<div class="dividend-stat"><b>' + soon.length +
      "</b><span>已公告下次除息</span></div>" +
      '<div class="dividend-stat"><b>' +
      (soon.length ? soon[0].nextExDate : "—") +
      "</b><span>最近一個除息日</span></div>" +
      "</div>" +
      '<div class="dividend-views">' +
      '<button type="button" data-view="calendar"' +
      (view === "calendar" ? ' class="is-on"' : "") + ">配息行事曆</button>" +
      '<button type="button" data-view="table"' +
      (view === "table" ? ' class="is-on"' : "") + ">明細表</button>" +
      (view === "calendar"
        ? '<span class="dividend-bulk">' +
          '<button type="button" data-bulk="all">全選</button>' +
          '<button type="button" data-bulk="none">全不選</button></span>'
        : "") +
      "</div>" +
      (view === "calendar"
        ? '<div class="dividend-legend"><span><b>💰</b> 已完成除息</span>' +
          '<span><b class="plan">💰</b> 投信公告之配息月份，尚未除息</span></div>'
        : "") +
      (view === "calendar" ? renderCalendar() : "") +
      (view === "calendar" ? "" :
      '<div class="dividend-filters">' + chip("all", "有配息") + chip("upcoming", "已公告除息") +
      chip("monthly", "月配") + chip("active", "主動式") + chip("none", "尚未配息") + "</div>" +
      '<div class="dividend-scroll"><table class="dividend-table"><thead><tr>' +
      "<th>ETF</th><th>頻率</th><th>最近除息日</th><th>最近配息</th>" +
      "<th>近一年配息</th><th>殖利率</th><th>累計次數</th><th>下次除息</th>" +
      "</tr></thead><tbody>" +
      (body || '<tr><td colspan="8" class="dividend-empty">此條件沒有標的</td></tr>') +
      "</tbody></table></div>") +
      '<p class="dividend-note">' + (payload.methodology || "") +
      "<br>資料來源：" + (payload.sourceTitle || "") +
      "。更新時間 " + (payload.generatedAt || "").replace("T", " ").slice(0, 16) + "。</p>";
  }

  function load() {
    if (payload || loading) return loading;
    loading = Promise.all([
      fetch(DATA_URL, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
      // A missing or failed ranking must not blank the calendar; the YTD column
      // simply shows "—" and the order falls back to code.
      fetch(RANKING_URL, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ])
      .then(([data, ranked]) => {
        payload = data;
        ranking = {};
        ((ranked && ranked.instruments) || []).forEach((i) => {
          const ytd = i.returns && i.returns.ytd;
          if (ytd && typeof ytd.returnPct === "number") ranking[i.code] = ytd.returnPct;
        });
        render();
      })
      .catch(() => {
        const panel = ourPanel();
        if (panel) panel.innerHTML = '<div class="dividend-empty">資料暫時無法載入。</div>';
      });
    return loading;
  }

  function activate() {
    if (!ensure()) return;
    active = true;
    reactPanels().forEach((node) => {
      if (node.dataset.dividendHidden === undefined) {
        node.dataset.dividendHidden = node.style.display || "";
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
      if (node.dataset.dividendHidden !== undefined) {
        node.style.display = node.dataset.dividendHidden;
        delete node.dataset.dividendHidden;
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
    const bar = strip();
    const host = shell();
    if (!bar || !host) return false;
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
      bar.appendChild(button);
    }
    if (!ourPanel()) {
      const panel = document.createElement("section");
      panel.className = "dividend-panel";
      panel.setAttribute(PANEL_FLAG, "");
      panel.style.display = "none";
      host.appendChild(panel);
    }
    return true;
  }

  document.addEventListener(
    "click",
    (event) => {
      const viewBtn = event.target.closest?.("[" + PANEL_FLAG + "] .dividend-views button[data-view]");
      if (viewBtn) {
        view = viewBtn.dataset.view;
        render();
        return;
      }
      const bulk = event.target.closest?.("[" + PANEL_FLAG + "] button[data-bulk]");
      if (bulk) {
        const list = calendarRows();
        selected = bulk.dataset.bulk === "all" ? new Set(list.map((i) => i.code)) : new Set();
        render();
        return;
      }
      const chip = event.target.closest?.("[" + PANEL_FLAG + "] .dividend-filters button");
      if (chip) {
        filter = chip.dataset.filter;
        render();
        return;
      }
      const tab = event.target.closest?.('.workspace-tabs [role="tab"]');
      if (!tab || tab.hasAttribute(TAB_FLAG)) return;
      if (active) deactivate();
    },
    true,
  );

  document.addEventListener("change", (event) => {
    const box = event.target.closest?.("[" + PANEL_FLAG + "] input[data-code]");
    if (!box) return;
    if (box.checked) selected.add(box.dataset.code);
    else selected.delete(box.dataset.code);
    render();
  });

  function boot() {
    ensure();
    new MutationObserver(() => {
      if (!ensure()) return;
      if (active) {
        reactPanels().forEach((n) => {
          n.style.display = "none";
        });
        const panel = ourPanel();
        if (panel && panel.style.display === "none") panel.style.display = "";
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
