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
  const VIEWS = new Set(["calendar", "table", "calc"]);
  let view = viewFromUrl();

  function viewFromUrl() {
    try {
      const value = new URL(window.location.href).searchParams.get("view");
      return VIEWS.has(value) ? value : "calendar";
    } catch (error) {
      return "calendar";
    }
  }

  /*
   * 三個子分頁各有自己的網址（?tab=dividends&view=calendar|table|calc），
   * 才分享得出去、也才能用上一頁回到前一個子分頁。
   *
   * 站台的 popostock-url-state.js 會在切換主分頁時重寫網址，但它是從現有
   * 網址複製再改 tab／code，不會動 view，所以這裡只要負責自己那一個參數。
   * 預設的行事曆不寫進網址，維持 ?tab=dividends 這個既有的乾淨連結。
   */
  function syncViewUrl(mode) {
    try {
      const url = new URL(window.location.href);
      if (view === "calendar") url.searchParams.delete("view");
      else url.searchParams.set("view", view);
      if (url.href === window.location.href) return;
      window.history[mode === "push" ? "pushState" : "replaceState"]({ popostock: true }, "", url);
    } catch (error) {
      /* 網址寫不進去不影響頁面 */
    }
  }
  // Starts empty on purpose: an all-checked calendar shows every ETF paying in
  // every month, which is the same as showing nothing.
  let selected = new Set();
  // 使用者的持股（代號＋張數）。存在瀏覽器本機，不上傳。
  const CALC_KEY = "popostock-dividend-calc-v1";
  let holdings = loadHoldings();

  function loadHoldings() {
    try {
      const raw = localStorage.getItem(CALC_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed)
        ? parsed.filter((h) => h && h.code).map((h) => ({ code: String(h.code), lots: Number(h.lots) || 0 }))
        : [];
    } catch (error) {
      return [];  // 私密視窗擋儲存時照常可用，只是不會記住。
    }
  }

  function saveHoldings() {
    try {
      localStorage.setItem(CALC_KEY, JSON.stringify(holdings));
    } catch (error) {
      /* 存不進去不影響試算 */
    }
  }

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
      ".dividend-next-amt{display:block;margin-top:3px;color:#12295c;font-size:11.5px;font-weight:900;white-space:nowrap}",
      ".dividend-next-amt em{font-style:normal;color:#8b6b00;background:#fff3cd;border-radius:999px;padding:1px 6px;margin-left:5px;font-size:10.5px}",
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
      ".dividend-calc{margin-top:4px}",
      ".dividend-calc .add{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-bottom:14px}",
      ".dividend-calc .fld{display:flex;flex-direction:column;gap:5px}",
      ".dividend-calc .fld label{color:#8b98ab;font-size:12px;font-weight:900}",
      ".dividend-calc input{border:1px solid #d6dee6;border-radius:8px;padding:8px 11px;",
      "font-size:14px;font-weight:800;color:#12295c;background:#fff;min-height:38px}",
      ".dividend-calc input:focus{outline:2px solid rgba(8,117,111,.3);outline-offset:-1px}",
      ".dividend-calc .pick{min-width:260px;flex:1 1 260px}",
      ".dividend-calc .lots{width:110px}",
      ".dividend-calc .go{border:1px solid #e8bd22;background:#ffd43b;color:#12295c;font-weight:900;",
      "border-radius:8px;padding:9px 18px;cursor:pointer;min-height:38px}",
      ".dividend-calc .go:hover{background:#ffdc57}",
      ".dividend-calc .warn{color:#d64038;font-size:12.5px;font-weight:800;margin:-6px 0 10px}",
      ".dividend-calc table{width:100%;border-collapse:collapse;font-size:13.5px}",
      ".dividend-calc th{background:#12295c;color:#ffd43b;font-size:12px;font-weight:900;",
      "padding:8px 10px;text-align:left;white-space:nowrap}",
      ".dividend-calc th.n,.dividend-calc td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}",
      ".dividend-calc td{padding:9px 10px;border-bottom:1px solid #eef1f5;color:#33485f}",
      ".dividend-calc td.nm{color:#12295c;font-weight:900}",
      ".dividend-calc td.nm i{font-style:normal;color:#8b98ab;font-weight:700;margin-left:6px}",
      ".dividend-calc td.nm b.thin{display:block;margin-top:3px;color:#b26a00;background:#fff3cd;",
      "border-radius:999px;padding:1px 8px;font-size:11px;font-weight:900;width:fit-content}",
      ".dividend-calc td.cash{color:#12295c;font-weight:900}",
      ".dividend-calc tfoot td{border-top:2px solid #12295c;border-bottom:0;padding-top:11px;",
      "color:#12295c;font-weight:900;font-size:15px}",
      ".dividend-calc .del{border:1px solid #f0c8c8;background:#fff;color:#d64038;font-size:12px;",
      "font-weight:900;border-radius:7px;padding:5px 11px;cursor:pointer}",
      ".dividend-calc .sum{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0 4px}",
      ".dividend-calc .sum div{background:#f4f7fb;border:1px solid #e2e8f2;border-radius:12px;",
      "padding:10px 16px;min-width:150px;flex:1}",
      ".dividend-calc .sum b{display:block;color:#12295c;font-size:23px;font-weight:900}",
      ".dividend-calc .sum span{color:#7b8aa6;font-size:12px;font-weight:800}",
      ".dividend-calc .note{margin-top:12px;color:#7b8aa6;font-size:12px;font-weight:700;line-height:1.7}",
      ".dividend-calc .empty{color:#8b98ab;font-weight:800;padding:26px 0;text-align:center}",
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

  // 每年配幾次，用來判斷近十二個月的紀錄是否已經走完一輪。走不完一輪就不能
  // 把 trailingAmount 當成「一年配多少」，新掛牌的 ETF 會被嚴重低估。
  const CADENCE_TIMES = { "月配": 12, "季配": 4, "半年配": 2, "年配": 1 };

  function money(value) {
    return Math.round(value).toLocaleString("en-US");
  }

  function calcRows() {
    const byCode = new Map((payload?.instruments || []).map((i) => [i.code, i]));
    return holdings.map((h) => {
      const info = byCode.get(h.code);
      const shares = (Number(h.lots) || 0) * 1000;
      const perUnit = info && typeof info.trailingAmount === "number" ? info.trailingAmount : 0;
      const close = info && typeof info.latestClose === "number" ? info.latestClose : null;
      const times = CADENCE_TIMES[info?.cadence] || 0;
      const count = info?.trailingCount || 0;
      // 配過但還沒滿一輪（00981A 季配、近一年只有兩次）：直接加總會少算一半。
      // 用「已配的每次平均 × 年配次數」補成整年，比抓最近一次乘上去穩——
      // 主動式 ETF 的單次金額波動大，只取最後一次會被單一數字帶著跑。
      const thin = count > 0 && times > 0 && count < times;
      const annual = thin ? (perUnit / count) * times : perUnit;
      return {
        code: h.code,
        lots: Number(h.lots) || 0,
        name: info ? info.name : h.code,
        cadence: info?.cadence || "—",
        perUnit,
        annual,
        shares,
        cash: shares * annual,
        value: close === null ? null : shares * close,
        // 沒配過就沒有殖利率可言；印 0.00% 會被讀成「算出來是零」而不是「沒有資料」。
        yieldPct: close && annual ? (annual / close) * 100 : null,
        // 兩種「估不準」要分開講：完全沒配過，和配了但還沒滿一輪。
        never: !info || !info.payoutCount,
        thin,
        trailingCount: count,
        times,
      };
    });
  }

  function renderCalc() {
    const options = (payload?.instruments || [])
      .slice()
      .sort((a, b) => a.code.localeCompare(b.code))
      .map((i) => '<option value="' + i.code + " " + i.name + '"></option>')
      .join("");

    const list = calcRows();
    const estimated = list.some((r) => r.thin);
    const totalCash = list.reduce((sum, r) => sum + r.cash, 0);
    const totalValue = list.reduce((sum, r) => sum + (r.value || 0), 0);
    const body = list
      .map((r, index) => {
        const flag = r.never
          ? '<b class="thin">尚無配息紀錄</b>'
          : r.thin
            ? '<b class="thin">年化推估：已配 ' + r.trailingCount + " 次共 " +
              num(r.perUnit, 3) + " 元 × " + r.times + "／" + r.trailingCount + "</b>"
            : "";
        return (
          "<tr>" +
          '<td class="nm">' + r.name + "<i>" + r.code + "</i>" + flag + "</td>" +
          '<td class="n">' + r.lots.toLocaleString("en-US") + " 張</td>" +
          '<td class="n">' + (r.value === null ? "—" : money(r.value)) + "</td>" +
          '<td class="n">' + (r.annual ? num(r.annual, 3) : "—") + "</td>" +
          '<td class="n cash">' + (r.cash ? money(r.cash) : "—") + "</td>" +
          '<td class="n">' + (r.yieldPct === null ? "—" : num(r.yieldPct, 2) + "%") + "</td>" +
          '<td class="n"><button type="button" class="del" data-calc-del="' + index + '">刪除</button></td>' +
          "</tr>"
        );
      })
      .join("");

    return (
      '<div class="dividend-calc">' +
      '<div class="add">' +
      '<div class="fld pick"><label>ETF（輸入代號或名稱會自動列出）</label>' +
      '<input type="text" list="dividend-calc-options" data-calc-pick placeholder="例如 00919 或 群益" autocomplete="off"></div>' +
      '<div class="fld lots"><label>張數</label>' +
      '<input type="number" min="0" step="1" data-calc-lots placeholder="1" autocomplete="off"></div>' +
      '<button type="button" class="go" data-calc-add>＋ 加入</button>' +
      '<datalist id="dividend-calc-options">' + options + "</datalist></div>" +
      '<p class="warn" data-calc-warn hidden></p>' +
      (list.length
        ? '<div class="dividend-scroll"><table><thead><tr>' +
          "<th>ETF</th><th class=\"n\">張數</th><th class=\"n\">市值</th>" +
          "<th class=\"n\">整年每單位</th><th class=\"n\">整年配息</th>" +
          "<th class=\"n\">推估整年殖利率</th><th></th></tr></thead><tbody>" + body +
          '</tbody><tfoot><tr><td colspan="2">合計</td>' +
          '<td class="n">' + money(totalValue) + "</td><td></td>" +
          '<td class="n">' + money(totalCash) + "</td>" +
          '<td class="n">' + (totalValue ? num((totalCash / totalValue) * 100, 2) + "%" : "—") + "</td>" +
          "<td></td></tr></tfoot></table></div>" +
          '<div class="sum">' +
          "<div><b>" + money(totalCash) + "</b><span>整年配息合計（元）" +
          (estimated ? "・含推估" : "") + "</span></div>" +
          "<div><b>" + money(totalCash / 12) + "</b><span>平均每月（元）</span></div>" +
          "<div><b>" + money(totalValue) + "</b><span>持股市值（元）</span></div>" +
          "<div><b>" +
          (totalValue ? num((totalCash / totalValue) * 100, 2) + "%" : "—") +
          "</b><span>推估整年綜合殖利率</span></div></div>"
        : '<div class="empty">還沒有持股。上面選一檔 ETF、填張數，就會算出近一年大概配多少。</div>') +
      '<p class="note">' +
      "配息以「整年每單位 × 張數 × 1000」計算，實配金額來自交易所除權除息計算結果表；" +
      "市值與殖利率以最新收盤價計算。近十二個月已配滿一輪的，整年金額就是實配加總；" +
      "<b>還沒配滿一輪的（如新掛牌的主動式 ETF），以「已配次數的平均 × 年配次數」年化推估</b>，" +
      "並在該列標示計算過程。<b>這不是預測</b>——配息每期由投信依已實現損益決定，" +
      "會變動甚至不配，推估值只是把已知的幾次攤成整年。<br>" +
      "<b>這裡的數字會低於投信公告與新聞的「年化配息率」</b>：那是拿最近一次乘上年配次數" +
      "（例如 00981A 用 0.63×4 得到 8.3%），只反映最新一期；本頁用已配次數的平均" +
      "（0.41 與 0.63 平均 0.52，×4 得 6.85%），把先前配得少的那幾次也算進去，因此較保守。" +
      "兩種算法都沒錯，看的是不同問題。持股只存在你自己的瀏覽器，不會上傳。</p>" +
      "</div>"
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
        // 公告的金額是投信的預估數，除息後會被交易所的實際數取代，所以標出來，
        // 並把最後買進日／發放日與出處放進 title，欄位才不會被撐爆。
        let next = '<span class="dividend-none">未公告</span>';
        if (i.nextExDate) {
          const hint = [
            i.nextLastBuyDate ? "最後買進日 " + i.nextLastBuyDate : "",
            i.nextRecordDate ? "基準日 " + i.nextRecordDate : "",
            i.nextPayDate ? "發放日 " + i.nextPayDate : "",
            i.nextSourceTier || "",
            i.nextSourceTitle || "",
          ].filter(Boolean).join("　");
          const amount =
            typeof i.nextAmount === "number"
              ? '<span class="dividend-next-amt">每單位 ' + num(i.nextAmount, 2) +
                (i.nextAmountStatus ? "<em>" + i.nextAmountStatus + "</em>" : "") + "</span>"
              : "";
          next =
            '<span class="dividend-next soon"' + (hint ? ' title="' + hint + '"' : "") + ">" +
            i.nextExDate.slice(5) + "</span>" + amount;
        }
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
      '<button type="button" data-view="calc"' +
      (view === "calc" ? ' class="is-on"' : "") + ">配息計算機</button>" +
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
      (view === "calc" ? renderCalc() : "") +
      (view !== "table" ? "" :
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
    view = viewFromUrl();
    // 認不得的 view=xxx 會退回行事曆，網址也一併正規化，不留一個沒有作用的參數。
    syncViewUrl("replace");
    render();
    load();
  }

  // 上一頁／下一頁回到不同子分頁時要跟著換，否則網址變了畫面沒變。
  window.addEventListener("popstate", () => {
    if (!active) return;
    const next = viewFromUrl();
    if (next === view) return;
    view = next;
    render();
  });

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
        syncViewUrl("push");
        render();
        return;
      }
      const add = event.target.closest?.("[" + PANEL_FLAG + "] [data-calc-add]");
      if (add) {
        addHolding();
        return;
      }
      const del = event.target.closest?.("[" + PANEL_FLAG + "] [data-calc-del]");
      if (del) {
        holdings.splice(Number(del.dataset.calcDel), 1);
        saveHoldings();
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

  /*
   * datalist 的值是「代號 名稱」，使用者也可能只打代號或只打名稱就按加入。
   * 三種都接：先抓開頭的代號，抓不到就用名稱比對，仍找不到才報錯——與其
   * 靜靜加進一筆查無此檔的持股，不如當場說清楚。
   */
  function addHolding() {
    const panel = ourPanel();
    if (!panel) return;
    const pick = panel.querySelector("[data-calc-pick]");
    const lotsInput = panel.querySelector("[data-calc-lots]");
    const warn = panel.querySelector("[data-calc-warn]");
    const raw = (pick.value || "").trim();
    const lots = Number(lotsInput.value);
    const say = (message) => {
      warn.textContent = message;
      warn.hidden = !message;
    };

    if (!raw) return say("請先選一檔 ETF。");
    const all = payload?.instruments || [];
    const code = (raw.split(/\s+/)[0] || "").toUpperCase();
    const found =
      all.find((i) => i.code.toUpperCase() === code) ||
      all.find((i) => i.name === raw) ||
      all.find((i) => i.name.includes(raw));
    if (!found) return say("找不到「" + raw + "」，請從下拉選單挑一檔。");
    if (!(lots > 0)) return say("張數要大於 0。");

    const existing = holdings.find((h) => h.code === found.code);
    if (existing) existing.lots += lots;
    else holdings.push({ code: found.code, lots: lots });
    saveHoldings();
    say("");
    pick.value = "";
    lotsInput.value = "";
    render();
    ourPanel()?.querySelector("[data-calc-pick]")?.focus();
  }

  // Enter 直接加入，不用移到按鈕；輸入框在表單之外，沒有原生 submit 可用。
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const field = event.target.closest?.(
      "[" + PANEL_FLAG + "] [data-calc-pick], [" + PANEL_FLAG + "] [data-calc-lots]",
    );
    if (!field) return;
    event.preventDefault();
    addHolding();
  });

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
