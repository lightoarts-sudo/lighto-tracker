(() => {
  "use strict";

  // 「全球主動ETF」「台灣主動ETF」兩個開關，掛在兩個地方：
  //   1. 主動式 ETF 加減碼面板的標題列（深藍底）
  //   2. 主動式 ETF 清單側欄的標題列（白底）
  // 兩邊共用同一組開關狀態，切分頁不會各自為政。
  //
  // 卡片、清單、標題都由 React 產生，所以這裡只 append 到容器最後，再用 CSS
  // order 排位；絕不插入既有子節點之間（會 NotFoundError）。React 重繪後會重補。
  //
  // 站台網址可能是 /popostock/ 也可能是 /popostock（無結尾斜線），後者會讓
  // 相對路徑 "data/..." 解析到網站根目錄而 404，所以基準路徑取自本腳本位置。
  const BASE = (() => {
    const self = document.currentScript && document.currentScript.src;
    if (self) return self.slice(0, self.lastIndexOf("/") + 1);
    return new URL("./", location.href).href;
  })();

  const PANEL = "section.active-etf-change-panel";
  const HEADING = "header.active-etf-change-heading";
  const CARD = ".active-etf-change-card";
  const SIDE = "aside.side-panel";
  const SIDE_HEAD = ".panel-heading";
  const ROW = ".item-row";
  const FLAG = "data-ae-scope";
  const HIDDEN = "ae-scope-hidden";

  // 兩個都預設開啟，也就是不篩選時與原本畫面完全一致。
  const shown = { global: true, tw: true };
  let scopes = null;
  let counts = { global: 0, tw: 0 };

  function style() {
    if (document.getElementById("ae-scope-style")) return;
    const element = document.createElement("style");
    element.id = "ae-scope-style";
    element.textContent = [
      "[" + FLAG + "]{display:flex;flex-wrap:wrap;align-items:center;gap:8px}",
      "[" + FLAG + '="dark"]{margin-top:12px}',
      "[" + FLAG + "] .ae-scope-label{font-size:12.5px;font-weight:800;margin-right:2px}",
      "[" + FLAG + "] button{appearance:none;cursor:pointer;font:inherit;font-size:12.5px;",
      "font-weight:800;line-height:1.4;padding:5px 13px;border-radius:999px;",
      "transition:background .16s ease,color .16s ease,border-color .16s ease}",
      "[" + FLAG + "] button b{font-weight:900;margin-left:6px;font-variant-numeric:tabular-nums}",
      "[" + FLAG + "] .ae-scope-note{font-size:12px;font-weight:800}",
      // 深藍底（加減碼面板）：未選取維持可讀的淺字，不只靠淡化。
      "[" + FLAG + '="dark"] .ae-scope-label{color:#9fb3d9}',
      "[" + FLAG + '="dark"] button{border:1px solid rgba(255,255,255,.28);',
      "background:rgba(255,255,255,.06);color:#cfdcf0}",
      "[" + FLAG + '="dark"] button:hover{background:rgba(255,255,255,.16)}',
      "[" + FLAG + '="dark"] button[aria-pressed="true"]{background:#ffd43b;',
      "border-color:#ffd43b;color:#12295c}",
      "[" + FLAG + '="dark"] .ae-scope-note{color:#ffd43b}',
      // 白底（清單側欄）
      "[" + FLAG + '="light"] .ae-scope-label{color:#7b8aa6}',
      "[" + FLAG + '="light"] button{border:1px solid #d6deea;background:#f4f7fb;color:#4a5b75}',
      "[" + FLAG + '="light"] button:hover{background:#e7eefa}',
      "[" + FLAG + '="light"] button[aria-pressed="true"]{background:#06275f;',
      "border-color:#06275f;color:#fff}",
      "[" + FLAG + '="light"] .ae-scope-note{color:#7b8aa6;margin-left:auto}',
      "." + HIDDEN + "{display:none !important}",
    ].join("");
    document.head.appendChild(element);
  }

  // 加減碼卡：代號只能取自專屬的那個 <span>。用整個 header 的文字比對會把
  // 基金名稱尾端的數字一起吃掉（「主動統一升級50」+「00403A」→ 000403A）。
  function cardCode(card) {
    const header = card.querySelector("header");
    if (!header) return null;
    const link = header.querySelector("a") || header;
    const spans = link.querySelectorAll("span");
    const label = spans.length ? spans[spans.length - 1].textContent || "" : "";
    const match = label.trim().match(/^(\d{4,6}[A-Z]?)\s*·/);
    return match ? match[1] : null;
  }

  function rowCode(row) {
    const chip = row.querySelector(".code-chip");
    return chip ? (chip.textContent || "").trim() : null;
  }

  // 側欄是三個分頁共用的同一塊 DOM，切到基金／被動式時標題會換掉。
  // 只認主動式 ETF 那一份，否則會把別的分頁一起篩掉。
  function activeSide() {
    for (const side of document.querySelectorAll(SIDE)) {
      const title = side.querySelector(SIDE_HEAD + " h2");
      if (title && (title.textContent || "").includes("主動式 ETF")) return side;
    }
    return null;
  }

  function visible(code) {
    const scope = code && scopes[code];
    // 分類表查不到的（剛上市、還沒重建資料）一律顯示，不要讓它憑空消失。
    return !scope || shown[scope];
  }

  function apply() {
    if (!scopes) return;
    let cards = 0;
    document.querySelectorAll(CARD).forEach((card) => {
      const show = visible(cardCode(card));
      card.classList.toggle(HIDDEN, !show);
      if (show) cards += 1;
    });

    const side = activeSide();
    // 切到基金／被動式分頁時，React 會沿用同一批節點，殘留的隱藏 class
    // 會讓那邊憑空少幾列，所以先全部清掉再只對主動式那份套用。
    document.querySelectorAll(ROW).forEach((row) => row.classList.remove(HIDDEN));
    let rows = 0, total = 0;
    if (side) {
      side.querySelectorAll(ROW).forEach((row) => {
        total += 1;
        const show = visible(rowCode(row));
        row.classList.toggle(HIDDEN, !show);
        if (show) rows += 1;
      });
    }

    document.querySelectorAll("[" + FLAG + '="dark"] .ae-scope-note').forEach((note) => {
      note.textContent = cards ? "" : "兩個分類都已關閉，目前沒有可顯示的 ETF。";
    });
    document.querySelectorAll("[" + FLAG + '="light"] .ae-scope-note').forEach((note) => {
      note.textContent = total ? "顯示 " + rows + " / " + total : "";
    });
  }

  function button(scope, text, count) {
    const element = document.createElement("button");
    element.type = "button";
    element.dataset.aeScopeKey = scope;
    element.setAttribute("aria-pressed", String(shown[scope]));
    element.innerHTML = text + "<b>" + count + "</b>";
    element.addEventListener("click", () => {
      shown[scope] = !shown[scope];
      document
        .querySelectorAll("[" + FLAG + '] button[data-ae-scope-key="' + scope + '"]')
        .forEach((twin) => twin.setAttribute("aria-pressed", String(shown[scope])));
      apply();
    });
    return element;
  }

  function bar(theme) {
    const element = document.createElement("div");
    element.setAttribute(FLAG, theme);
    const label = document.createElement("span");
    label.className = "ae-scope-label";
    label.textContent = "投資區域";
    element.appendChild(label);
    element.appendChild(button("global", "全球主動ETF", counts.global));
    element.appendChild(button("tw", "台灣主動ETF", counts.tw));
    const note = document.createElement("span");
    note.className = "ae-scope-note";
    element.appendChild(note);
    return element;
  }

  function mountChanges() {
    document.querySelectorAll(PANEL).forEach((panel) => {
      const heading = panel.querySelector(HEADING);
      if (!heading || heading.querySelector("[" + FLAG + "]")) return;
      heading.appendChild(bar("dark"));
    });
  }

  function mountSide() {
    // 標題換成別的分頁時，把先前掛上的工具列收掉。
    document.querySelectorAll(SIDE).forEach((side) => {
      const mine = side.querySelector("[" + FLAG + '="light"]');
      const title = side.querySelector(SIDE_HEAD + " h2");
      const isActive = title && (title.textContent || "").includes("主動式 ETF");
      if (mine && !isActive) mine.remove();
    });
    const side = activeSide();
    if (!side || side.querySelector("[" + FLAG + '="light"]')) return;
    const element = bar("light");
    side.appendChild(element);
    // side-panel 是 grid，用 order 排位而非插入既有子節點之間。
    // 每個手足都要給明確 order，沒給的會塌成 0 跳到最前面。
    let step = 0;
    for (const child of Array.from(side.children)) {
      if (child === element) continue;
      step += 10;
      child.style.order = String(step);
      if (child.classList.contains("item-list")) element.style.order = String(step - 5);
    }
  }

  function mount() {
    if (!scopes) return;
    mountChanges();
    mountSide();
    apply();
  }

  function start() {
    style();
    fetch(BASE + "data/active-etf-scope.json", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (!payload || !payload.scopes) return;
        scopes = payload.scopes;
        counts = payload.counts || counts;
        mount();
        // React 換分頁／換日期會整批重繪，重繪後既有節點被丟棄，必須重新補上。
        // 這裡用 setTimeout 而非 requestAnimationFrame：分頁在背景時 rAF 不會
        // 觸發，於是在背景開啟的頁面永遠不會補上按鈕。
        let queued = false;
        const schedule = () => {
          if (queued) return;
          queued = true;
          setTimeout(() => { queued = false; mount(); }, 60);
        };
        new MutationObserver(schedule).observe(document.body, {
          childList: true,
          subtree: true,
        });
        // 保險：面板可能在 observer 掛上前就渲染完成，之後不再有任何變動，
        // 那樣就沒有任何事件會觸發掛載。開頭數秒內定期重試。
        let attempts = 0;
        const timer = setInterval(() => {
          attempts += 1;
          mount();
          if (attempts >= 40) clearInterval(timer);
        }, 500);
      })
      .catch(() => {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
