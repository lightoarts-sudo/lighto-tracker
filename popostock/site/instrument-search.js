/*
 * 全站標的搜尋：打代號或名稱，跳到那一檔的頁面。
 *
 * 追蹤的標的已經一百多檔，分散在三個分頁的清單裡，用捲的找很慢。這個框把
 * 主動式 ETF、被動式 ETF 與基金放在同一個輸入框，選中之後改寫網址，交給
 * popostock-url-state.js 去切分頁與選標的——導航規則只有那一支在管，這裡
 * 不自己點按鈕，避免兩邊對「現在在哪」有不同看法。
 */
(function () {
  "use strict";

  var INDEX_URL = "data/performance-ranking.json";
  var FLAG = "data-popostock-search";
  var LIST_ID = "popostock-search-options";
  // performance-ranking 的分組代號 → 網址用的分頁代號。
  var TAB_FOR_GROUP = {
    activeEtfs: "active-etfs",
    passiveEtfs: "passive-etfs",
    funds: "funds",
  };
  var GROUP_LABEL = { activeEtfs: "主動", passiveEtfs: "被動", funds: "基金" };

  var instruments = [];
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
    if (document.getElementById("popostock-search-style")) return;
    var element = document.createElement("style");
    element.id = "popostock-search-style";
    element.textContent = [
      ".popostock-search{margin-top:14px;position:relative}",
      ".popostock-search label{display:block;color:#9fb3d9;font-size:11.5px;",
      "font-weight:900;letter-spacing:.04em;margin-bottom:5px}",
      ".popostock-search input{width:100%;border:1px solid #d3b85c;border-radius:8px;",
      "padding:9px 12px;font-size:14px;font-weight:800;color:#12295c;background:#fff;",
      "font-family:inherit}",
      ".popostock-search input::placeholder{color:#9aa8c7;font-weight:700}",
      ".popostock-search input:focus{outline:2px solid rgba(255,212,59,.5);outline-offset:1px}",
      ".popostock-search .hint{margin:5px 0 0;color:#7f93bb;font-size:11px;font-weight:700}",
      ".popostock-search .hint.warn{color:#ffd43b}",
    ].join("");
    document.head.appendChild(element);
  }

  function load() {
    if (instruments.length || loading) return loading;
    loading = fetch(baseUrl() + "/" + INDEX_URL, { cache: "no-store" })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (payload) {
        instruments = ((payload && payload.instruments) || []).filter(function (item) {
          return TAB_FOR_GROUP[item.group];
        });
        fillOptions();
      })
      .catch(function () {
        // 索引抓不到就讓輸入框留著但不給建議，不要整塊消失。
      });
    return loading;
  }

  function fillOptions() {
    var list = document.getElementById(LIST_ID);
    if (!list) return;
    list.innerHTML = instruments
      .map(function (item) {
        return (
          '<option value="' + item.code + " " + item.name + '">' +
          (GROUP_LABEL[item.group] || "") + "</option>"
        );
      })
      .join("");
  }

  /*
   * 三種輸入都要接：完整的「代號 名稱」（從選單選的）、只有代號、只有名稱。
   * 名稱用包含比對，因為使用者常只記得「高股息」這種片段。
   */
  function resolve(raw) {
    var text = String(raw || "").trim();
    if (!text) return null;
    var code = (text.split(/\s+/)[0] || "").toUpperCase();
    var exact = instruments.filter(function (item) {
      return item.code.toUpperCase() === code;
    });
    if (exact.length) return exact[0];
    var byName = instruments.filter(function (item) {
      return item.name === text;
    });
    if (byName.length) return byName[0];
    var partial = instruments.filter(function (item) {
      return item.name.indexOf(text) >= 0 || item.code.toUpperCase().indexOf(code) >= 0;
    });
    return partial.length === 1 ? partial[0] : null;
  }

  function go(item) {
    var url = new URL(window.location.href);
    url.searchParams.set("tab", TAB_FOR_GROUP[item.group]);
    url.searchParams.set("code", item.code.toUpperCase());
    url.searchParams.delete("view");
    window.history.pushState({ popostock: true }, "", url);
    // url-state 只在 popstate 時重新套用網址，pushState 不會自己觸發。
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  function submit(box) {
    var input = box.querySelector("input");
    var hint = box.querySelector(".hint");
    var item = resolve(input.value);
    if (!item) {
      hint.textContent = input.value.trim()
        ? "找不到「" + input.value.trim() + "」，請從下拉選單挑一檔"
        : "追蹤 " + instruments.length + " 檔・輸入代號或名稱";
      hint.className = input.value.trim() ? "hint warn" : "hint";
      return;
    }
    hint.className = "hint";
    hint.textContent = "追蹤 " + instruments.length + " 檔・輸入代號或名稱";
    input.value = "";
    input.blur();
    go(item);
  }

  function mount() {
    var header = document.querySelector(".workspace-header");
    if (!header || header.querySelector("[" + FLAG + "]")) return;
    style();
    var box = document.createElement("div");
    box.className = "popostock-search";
    box.setAttribute(FLAG, "");
    box.innerHTML =
      '<label for="popostock-search-input">搜尋 ETF ／ 基金</label>' +
      '<input id="popostock-search-input" type="text" list="' + LIST_ID + '"' +
      ' placeholder="輸入代號或名稱，例如 00981A 或 高股息" autocomplete="off">' +
      '<datalist id="' + LIST_ID + '"></datalist>' +
      '<p class="hint">載入標的清單…</p>';
    // 只 append，不插入 React 子節點之間——這個站踩過 NotFoundError。
    header.appendChild(box);
    load().then(function () {
      var hint = box.querySelector(".hint");
      if (!hint) return;
      hint.textContent = instruments.length
        ? "追蹤 " + instruments.length + " 檔・輸入代號或名稱"
        : "標的清單載入失敗";
    });
  }

  document.addEventListener("change", function (event) {
    // 從下拉選單挑一項會觸發 change，這時直接跳轉，不用再按 Enter。
    var input = event.target.closest
      ? event.target.closest("[" + FLAG + "] input")
      : null;
    if (input) submit(input.closest("[" + FLAG + "]"));
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    var input = event.target.closest
      ? event.target.closest("[" + FLAG + "] input")
      : null;
    if (!input) return;
    event.preventDefault();
    submit(input.closest("[" + FLAG + "]"));
  });

  function boot() {
    mount();
    // React 重繪 header 時會把搜尋框一起丟掉，要補回來。
    new MutationObserver(function () {
      mount();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
