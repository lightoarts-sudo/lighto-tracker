/*
 * PoPoStock active-ETF position record dialog.
 *
 * Every stock listed on a 主動式 ETF 加減碼 card becomes activatable. Opening
 * one shows how that ETF traded that stock inside the tracking window: each
 * add/trim with its official price, the average cost of the lots we can price,
 * the unrealised result at the latest close, and the realised result once the
 * position is closed.
 *
 * The dialog is deliberately explicit about what it cannot know. Lots the ETF
 * already held on the baseline date have no purchase price, so they are shown
 * as 期初持股（成本未知）rather than folded into an average that would look
 * authoritative and be wrong.
 */
(function () {
  "use strict";

  var DATA_PREFIX = "data/active-etf-positions/";
  var ledgers = new Map();
  var lastTrigger = null;
  var previousBodyOverflow = "";
  var activeRequest = 0;

  function baseUrl() {
    var base = document.querySelector("base[href]");
    if (base) return new URL(base.getAttribute("href"), window.location.href).href.replace(/\/$/, "");
    var match = window.location.href.match(/^(https?:\/\/[^/]+\/popostock)/);
    return match ? match[1] : "";
  }

  function loadLedger(etfCode) {
    if (ledgers.has(etfCode)) return Promise.resolve(ledgers.get(etfCode));
    return fetch(baseUrl() + "/" + DATA_PREFIX + encodeURIComponent(etfCode) + ".json", {
      cache: "no-store",
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        ledgers.set(etfCode, payload);
        return payload;
      });
  }

  function lots(value) {
    var number = Number(value || 0);
    return (Math.round(number * 100) / 100).toLocaleString("zh-TW") + " 張";
  }

  function money(value) {
    if (value === null || value === undefined) return "—";
    var number = Number(value);
    var sign = number < 0 ? "−" : "";
    var size = Math.abs(number);
    if (size >= 1e8) return sign + (size / 1e8).toFixed(4).replace(/0+$/, "").replace(/\.$/, "") + " 億";
    if (size >= 1e4) return sign + (size / 1e4).toFixed(1) + " 萬";
    return sign + size.toLocaleString("zh-TW");
  }

  function price(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
  }

  function percent(value) {
    if (value === null || value === undefined) return "";
    return (value >= 0 ? "+" : "−") + Math.abs(value).toFixed(2) + "%";
  }

  function toneClass(value) {
    if (value === null || value === undefined) return "";
    return value >= 0 ? " is-up" : " is-down";
  }

  function installStyles() {
    if (document.getElementById("active-etf-position-styles")) return;
    var style = document.createElement("style");
    style.id = "active-etf-position-styles";
    style.textContent =
      ".active-etf-change-card li[data-position-stock]{cursor:pointer;border-radius:7px;transition:background .16s ease}" +
      ".active-etf-change-card li[data-position-stock]:hover{background:#eef8f7}" +
      ".active-etf-change-card li[data-position-stock]:focus-visible{outline:3px solid rgba(8,117,111,.32);outline-offset:-2px}" +
      ".active-etf-position-modal{position:fixed;inset:0;z-index:10000;display:none;align-items:center;justify-content:center;padding:24px;background:rgba(5,24,48,.66);backdrop-filter:blur(4px)}" +
      ".active-etf-position-modal.is-open{display:flex}" +
      ".active-etf-position-dialog{width:min(880px,100%);max-height:min(860px,calc(100vh - 40px));overflow:auto;border:1px solid #d6dee6;border-radius:16px;background:#fff;box-shadow:0 28px 70px rgba(3,25,52,.3)}" +
      ".active-etf-position-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:20px 22px 14px;border-bottom:1px solid #e4e9ee}" +
      ".active-etf-position-eyebrow{margin:0 0 4px;color:#08756f;font-size:12px;font-weight:900;letter-spacing:.08em}" +
      ".active-etf-position-title{margin:0;color:#06275f;font-size:23px;line-height:1.25}" +
      ".active-etf-position-subtitle{margin:6px 0 0;color:#667483;font-size:13px}" +
      ".active-etf-position-close{flex:0 0 auto;width:38px;height:38px;border:1px solid #d6dee6;border-radius:50%;background:#fff;color:#33485f;font-size:22px;line-height:1;cursor:pointer}" +
      ".active-etf-position-close:hover{background:#f3f6f8}" +
      ".active-etf-position-body{padding:18px 22px 22px}" +
      ".active-etf-position-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}" +
      ".active-etf-position-stat{padding:10px 12px;border-radius:10px;background:#f5f8fa}" +
      ".active-etf-position-stat span{display:block;color:#667483;font-size:12px;font-weight:700}" +
      ".active-etf-position-stat strong{display:block;margin-top:3px;color:#06275f;font-size:19px}" +
      ".active-etf-position-stat strong.is-up{color:#c23d4b}" +
      ".active-etf-position-stat strong.is-down{color:#16845b}" +
      ".active-etf-position-stat em{display:block;margin-top:2px;font-size:12px;font-style:normal;font-weight:750}" +
      ".active-etf-position-stat em.is-up{color:#c23d4b}" +
      ".active-etf-position-stat em.is-down{color:#16845b}" +
      ".active-etf-position-note{margin:0 0 14px;padding:9px 12px;border-left:3px solid #d8a13a;border-radius:0 8px 8px 0;background:#fdf6e8;color:#6b5220;font-size:12.5px;line-height:1.6}" +
      ".active-etf-position-table{width:100%;border-collapse:collapse;font-size:13px}" +
      ".active-etf-position-table th{padding:7px 8px;border-bottom:1px solid #d6dee6;color:#667483;font-size:12px;text-align:right}" +
      ".active-etf-position-table th:first-child,.active-etf-position-table td:first-child{text-align:left}" +
      ".active-etf-position-table td{padding:7px 8px;border-bottom:1px solid #edf1f4;color:#06275f;text-align:right;font-variant-numeric:tabular-nums}" +
      ".active-etf-position-table td.is-buy{color:#c23d4b;font-weight:800}" +
      ".active-etf-position-table td.is-sell{color:#16845b;font-weight:800}" +
      ".active-etf-position-scroll{overflow-x:auto}" +
      ".active-etf-position-method{margin:12px 0 0;color:#8794a3;font-size:11.5px;line-height:1.6}" +
      ".active-etf-position-message{display:grid;place-items:center;min-height:180px;color:#667483;font-weight:750}" +
      "@media(max-width:720px){.active-etf-position-modal{padding:10px}.active-etf-position-dialog{max-height:calc(100vh - 20px);border-radius:12px}.active-etf-position-header{padding:16px}.active-etf-position-title{font-size:19px}.active-etf-position-body{padding:14px 12px 16px}}";
    document.head.appendChild(style);
  }

  function ensureModal() {
    var modal = document.getElementById("active-etf-position-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "active-etf-position-modal";
    modal.className = "active-etf-position-modal";
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML =
      '<section class="active-etf-position-dialog" role="dialog" aria-modal="true" aria-labelledby="active-etf-position-title">' +
      '<header class="active-etf-position-header"><div>' +
      '<p class="active-etf-position-eyebrow">主動式 ETF 操作紀錄</p>' +
      '<h2 class="active-etf-position-title" id="active-etf-position-title"></h2>' +
      '<p class="active-etf-position-subtitle"></p></div>' +
      '<button class="active-etf-position-close" type="button" aria-label="關閉操作紀錄">×</button></header>' +
      '<div class="active-etf-position-body"><div class="active-etf-position-message">載入中…</div></div></section>';
    document.body.appendChild(modal);
    modal.querySelector(".active-etf-position-close").addEventListener("click", closeModal);
    modal.addEventListener("click", function (event) {
      if (event.target === modal) closeModal();
    });
    return modal;
  }

  function closeModal() {
    var modal = document.getElementById("active-etf-position-modal");
    if (!modal || !modal.classList.contains("is-open")) return;
    activeRequest += 1;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = previousBodyOverflow;
    if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
  }

  function showMessage(modal, text) {
    var body = modal.querySelector(".active-etf-position-body");
    body.innerHTML = "";
    var message = document.createElement("div");
    message.className = "active-etf-position-message";
    message.textContent = text;
    body.appendChild(message);
  }

  function statCard(label, value, tone, sub, subTone) {
    return (
      '<div class="active-etf-position-stat"><span>' + label + "</span>" +
      "<strong" + (tone || "") + ">" + value + "</strong>" +
      (sub ? "<em" + (subTone || "") + ">" + sub + "</em>" : "") +
      "</div>"
    );
  }

  function renderRecord(modal, ledger, position) {
    var body = modal.querySelector(".active-etf-position-body");
    var stats = "";

    stats += statCard("目前持股", lots(position.currentLots),
      position.closed ? "" : "", position.closed ? "已出清" : null);

    if (position.averageCost !== null && position.averageCost !== undefined) {
      stats += statCard(
        "追蹤期平均成本",
        price(position.averageCost),
        "",
        lots(position.openLots) + " · 成本 " + money(position.openCostTwd),
      );
    } else if (
      position.realizedAverageCost !== null &&
      position.realizedAverageCost !== undefined
    ) {
      // Nothing is still open, so the meaningful average is what the sold lots
      // cost — saying "no priced buys" here would be plainly wrong.
      stats += statCard(
        "出清平均成本",
        price(position.realizedAverageCost),
        "",
        position.realizedAveragePrice
          ? "平均賣出 " + price(position.realizedAveragePrice)
          : null,
      );
    } else {
      stats += statCard("追蹤期平均成本", "—", "", "期間內無可計價加碼");
    }

    stats += statCard(
      "最新收盤",
      price(position.closePrice),
      "",
      position.priceDate ? position.priceDate.replace(/-/g, "/") : null,
    );

    if (position.unrealizedTwd !== null && position.unrealizedTwd !== undefined) {
      stats += statCard(
        "未實現損益",
        money(position.unrealizedTwd),
        toneClass(position.unrealizedTwd),
        percent(position.unrealizedPct),
        toneClass(position.unrealizedTwd),
      );
    }
    if (position.realizedTwd !== null && position.realizedTwd !== undefined) {
      stats += statCard(
        position.closed ? "出清績效" : "已實現損益",
        money(position.realizedTwd),
        toneClass(position.realizedTwd),
        percent(position.realizedPct) + " · " + lots(position.realizedLots),
        toneClass(position.realizedTwd),
      );
    }

    var notes = [];
    if (position.baselineLots > 0) {
      notes.push(
        "此標的在追蹤起點 " + ledger.baselineDate.replace(/-/g, "/") + " 已持有 " +
        lots(position.baselineLots) + "，官方沒有揭露當初的買進價格，因此這部分成本不可知；" +
        "上方成本與損益只涵蓋追蹤期內買進的部位。",
      );
    }
    if (position.unknownCostLotsSold > 0) {
      notes.push(
        "減碼中有 " + lots(position.unknownCostLotsSold) +
        " 以先進先出沖銷到期初持股，這部分無法計算績效。",
      );
    }
    if (position.unknownCostLotsHeld > 0 && position.baselineLots === 0) {
      notes.push(
        "有 " + lots(position.unknownCostLotsHeld) + " 的加碼當日沒有官方價格，未列入成本計算。",
      );
    }

    var rows = position.events
      .slice()
      .reverse()
      .map(function (event) {
        var isBuy = event.action === "buy";
        return (
          "<tr><td>" + event.date.replace(/-/g, "/") + "</td>" +
          '<td class="' + (isBuy ? "is-buy" : "is-sell") + '">' + (isBuy ? "加碼" : "減碼") + "</td>" +
          '<td class="' + (isBuy ? "is-buy" : "is-sell") + '">' +
          (isBuy ? "+" : "−") + lots(Math.abs(event.lots)) + "</td>" +
          "<td>" + price(event.price) + "</td>" +
          "<td>" + money(event.amountTwd) + "</td>" +
          "<td>" + lots(event.heldLots) + "</td></tr>"
        );
      })
      .join("");

    body.innerHTML =
      '<div class="active-etf-position-grid">' + stats + "</div>" +
      notes
        .map(function (note) {
          return '<p class="active-etf-position-note">' + note + "</p>";
        })
        .join("") +
      '<div class="active-etf-position-scroll"><table class="active-etf-position-table">' +
      "<thead><tr><th>日期</th><th>動作</th><th>張數</th><th>價格</th><th>金額</th><th>累計持股</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>" +
      '<p class="active-etf-position-method">' + ledger.costMethodology +
      " 追蹤期 " + ledger.baselineDate.replace(/-/g, "/") + " ~ " +
      ledger.latestDate.replace(/-/g, "/") + "（" + ledger.sessionCount + " 個交易日）。</p>";
  }

  function openRecord(etfCode, etfName, stockCode, stockName, trigger) {
    var modal = ensureModal();
    var requestId = ++activeRequest;
    lastTrigger = trigger;
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    modal.querySelector(".active-etf-position-title").textContent =
      stockName + "（" + stockCode + "）";
    modal.querySelector(".active-etf-position-subtitle").textContent =
      etfName + " " + etfCode + " 的操作紀錄與成本";
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    showMessage(modal, "載入操作紀錄…");
    modal.querySelector(".active-etf-position-close").focus();

    loadLedger(etfCode)
      .then(function (ledger) {
        if (requestId !== activeRequest) return;
        var position = (ledger.positions || []).find(function (item) {
          return item.stockCode === stockCode;
        });
        if (!position) {
          showMessage(modal, "追蹤期內沒有這檔股票的操作紀錄。");
          return;
        }
        renderRecord(modal, ledger, position);
      })
      .catch(function () {
        if (requestId !== activeRequest) return;
        showMessage(modal, "操作紀錄載入失敗，請稍後重試。");
      });
  }

  function decorateCard(card) {
    var header = card.querySelector("header span");
    if (!header) return;
    var etfCode = (header.textContent.split("·")[0] || "").trim();
    if (!/^[0-9]{5}[A-Z]$/.test(etfCode)) return;
    var etfName = (card.querySelector("header strong") || {}).textContent || etfCode;
    card.querySelectorAll("li").forEach(function (item) {
      if (item.dataset.positionStock) return;
      var codeElement = item.querySelector("small");
      var nameElement = item.querySelector("strong");
      if (!codeElement || !nameElement) return;
      var stockCode = codeElement.textContent.trim();
      if (!stockCode) return;
      item.dataset.positionStock = stockCode;
      item.dataset.positionEtf = etfCode;
      item.dataset.positionEtfName = etfName.trim();
      item.dataset.positionName = nameElement.textContent.trim();
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");
      item.setAttribute(
        "title",
        "查看 " + etfName.trim() + " 操作 " + nameElement.textContent.trim() + " 的紀錄與成本",
      );
    });
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    if (scope.matches && scope.matches(".active-etf-change-card")) decorateCard(scope);
    scope.querySelectorAll(".active-etf-change-card").forEach(decorateCard);
  }

  function activate(item) {
    openRecord(
      item.dataset.positionEtf,
      item.dataset.positionEtfName,
      item.dataset.positionStock,
      item.dataset.positionName,
      item,
    );
  }

  function watch() {
    installStyles();
    scan(document);
    // React re-renders the whole 加減碼 grid when the tab or data changes, so
    // the decoration has to be reapplied to newly mounted cards.
    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) scan(node);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });

    document.addEventListener("click", function (event) {
      var item = event.target.closest ? event.target.closest("li[data-position-stock]") : null;
      if (item) activate(item);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeModal();
        return;
      }
      var item = event.target.closest ? event.target.closest("li[data-position-stock]") : null;
      if (item && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        activate(item);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
