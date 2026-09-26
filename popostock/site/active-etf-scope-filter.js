(() => {
  "use strict";

  // 在「主動式 ETF 加減碼」面板標題下方，加上「全球主動ETF」「台灣主動ETF」
  // 兩個開關，用來篩選要顯示哪些卡片。
  //
  // 卡片與標題都由 React 產生，所以這裡只 append 到 <header> 的最後，並在
  // React 重繪後重新補上；絕不插入既有子節點之間（會 NotFoundError）。
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
      "[" + FLAG + "]{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px}",
      "[" + FLAG + "] .ae-scope-label{font-size:12.5px;font-weight:800;color:#9fb3d9;margin-right:2px}",
      // 未選取時維持可讀的深底樣式，不要只靠淡化，否則在深藍標題上看不出是按鈕。
      "[" + FLAG + "] button{appearance:none;cursor:pointer;font:inherit;font-size:12.5px;",
      "font-weight:800;line-height:1.4;padding:5px 13px;border-radius:999px;",
      "border:1px solid rgba(255,255,255,.28);background:rgba(255,255,255,.06);",
      "color:#cfdcf0;transition:background .16s ease,color .16s ease,border-color .16s ease}",
      "[" + FLAG + "] button:hover{background:rgba(255,255,255,.16)}",
      "[" + FLAG + "] button:focus-visible{outline:3px solid rgba(255,212,59,.55);outline-offset:2px}",
      "[" + FLAG + '] button[aria-pressed="true"]{background:#ffd43b;border-color:#ffd43b;color:#12295c}',
      "[" + FLAG + "] button b{font-weight:900;margin-left:6px;font-variant-numeric:tabular-nums}",
      "[" + FLAG + "] .ae-scope-note{font-size:12px;font-weight:700;color:#ffd43b}",
      "." + HIDDEN + "{display:none !important}",
    ].join("");
    document.head.appendChild(element);
  }

  // 代號只能取自專屬的那個 <span>。用整個 header 的文字比對會把基金名稱
  // 尾端的數字一起吃掉（「主動統一升級50」+「00403A」→ 誤判成 000403A）。
  function codeOf(card) {
    const header = card.querySelector("header");
    if (!header) return null;
    const link = header.querySelector("a") || header;
    const spans = link.querySelectorAll("span");
    const label = spans.length ? spans[spans.length - 1].textContent || "" : "";
    const match = label.trim().match(/^(\d{4,6}[A-Z]?)\s*·/);
    return match ? match[1] : null;
  }

  function apply() {
    if (!scopes) return;
    let visible = 0;
    document.querySelectorAll(CARD).forEach((card) => {
      const code = codeOf(card);
      const scope = code && scopes[code];
      // 分類表查不到的檔（剛上架、還沒重建資料）一律顯示，不要讓它憑空消失。
      const show = !scope || shown[scope];
      card.classList.toggle(HIDDEN, !show);
      if (show) visible += 1;
    });
    document.querySelectorAll("[" + FLAG + "] .ae-scope-note").forEach((note) => {
      note.textContent = visible ? "" : "兩個分類都已關閉，目前沒有可顯示的 ETF。";
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

  function mount() {
    if (!scopes) return;
    document.querySelectorAll(PANEL).forEach((panel) => {
      const heading = panel.querySelector(HEADING);
      if (!heading || heading.querySelector("[" + FLAG + "]")) return;
      const bar = document.createElement("div");
      bar.setAttribute(FLAG, "");
      const label = document.createElement("span");
      label.className = "ae-scope-label";
      label.textContent = "投資區域";
      bar.appendChild(label);
      bar.appendChild(button("global", "全球主動ETF", counts.global));
      bar.appendChild(button("tw", "台灣主動ETF", counts.tw));
      const note = document.createElement("span");
      note.className = "ae-scope-note";
      bar.appendChild(note);
      heading.appendChild(bar);
    });
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
        // 那樣就沒有任何事件會觸發掛載。開頭數秒內定期重試，掛上後自動停止。
        let attempts = 0;
        const timer = setInterval(() => {
          attempts += 1;
          mount();
          if (document.querySelector("[" + FLAG + "]") || attempts >= 40) {
            clearInterval(timer);
          }
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
