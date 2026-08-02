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
  var MARKET_PREFIX = "data/market/";
  var LIBRARY_FILE = "lightweight-charts.standalone.production.js";
  var ledgers = new Map();
  var candles = new Map();
  var libraryPromise = null;
  var activeChart = null;
  var activeResizeObserver = null;
  var lastTrigger = null;
  var previousBodyOverflow = "";
  var activeRequest = 0;
  var openContext = null;

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

  function loadLibrary() {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    if (libraryPromise) return libraryPromise;
    libraryPromise = new Promise(function (resolve, reject) {
      var source = baseUrl() + "/" + LIBRARY_FILE;
      // consensus-stock-kline.js ships the same library; reuse its tag rather
      // than downloading a second copy.
      var existing = Array.from(document.scripts).find(function (script) {
        return script.src === source || script.src.endsWith("/" + LIBRARY_FILE);
      });
      var script = existing || document.createElement("script");
      script.addEventListener(
        "load",
        function () {
          if (window.LightweightCharts) resolve(window.LightweightCharts);
          else reject(new Error("LightweightCharts global missing"));
        },
        { once: true },
      );
      script.addEventListener(
        "error",
        function () {
          reject(new Error("failed to load " + LIBRARY_FILE));
        },
        { once: true },
      );
      if (!existing) {
        script.src = source;
        document.head.appendChild(script);
      }
    });
    return libraryPromise;
  }

  function loadCandles(stockCode) {
    if (candles.has(stockCode)) return Promise.resolve(candles.get(stockCode));
    return fetch(baseUrl() + "/" + MARKET_PREFIX + encodeURIComponent(stockCode) + ".json", {
      cache: "no-store",
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        var values = (payload.values || [])
          .filter(function (point) {
            return point && point.time &&
              [point.open, point.high, point.low, point.close].every(function (value) {
                return typeof value === "number";
              });
          })
          .sort(function (left, right) {
            return left.time < right.time ? -1 : left.time > right.time ? 1 : 0;
          });
        candles.set(stockCode, values);
        return values;
      })
      .catch(function () {
        candles.set(stockCode, null);
        return null;
      });
  }

  function clearChart() {
    if (activeResizeObserver) {
      activeResizeObserver.disconnect();
      activeResizeObserver = null;
    }
    if (activeChart) {
      activeChart.remove();
      activeChart = null;
    }
  }

  function drawChart(container, lc, values, position) {
    clearChart();
    var chart = lc.createChart(container, {
      layout: {
        background: { type: lc.ColorType.Solid, color: "#ffffff" },
        textColor: "#667483",
        fontFamily: 'var(--font-geist-sans), "Noto Sans TC", Arial, sans-serif',
        fontSize: 11,
      },
      width: container.clientWidth,
      height: container.clientHeight,
      crosshairMode: lc.CrosshairMode.Normal,
      grid: { vertLines: { color: "#edf1f4" }, horzLines: { color: "#edf1f4" } },
      rightPriceScale: { borderColor: "#d6dee6", scaleMargins: { top: 0.1, bottom: 0.16 } },
      timeScale: { borderColor: "#d6dee6", rightOffset: 2 },
    });
    var series = chart.addSeries(lc.CandlestickSeries, {
      upColor: "#c23d4b",
      downColor: "#16845b",
      borderUpColor: "#c23d4b",
      borderDownColor: "#16845b",
      wickUpColor: "#c23d4b",
      wickDownColor: "#16845b",
      priceLineVisible: false,
    });
    series.setData(
      values.map(function (point) {
        return {
          time: point.time,
          open: point.open,
          high: point.high,
          low: point.low,
          close: point.close,
        };
      }),
    );

    var chartDates = new Set(
      values.map(function (point) {
        return point.time;
      }),
    );
    var counts = { buy: 0, sell: 0 };
    var markers = position.events
      .filter(function (event) {
        return chartDates.has(event.date);
      })
      .map(function (event) {
        var isBuy = event.action === "buy";
        counts[isBuy ? "buy" : "sell"] += 1;
        // Buys sit under the bar, sells above it, so a date with both stays
        // readable instead of stacking two arrows on the same spot.
        return {
          time: event.date,
          position: isBuy ? "belowBar" : "aboveBar",
          color: isBuy ? "#c23d4b" : "#16845b",
          shape: isBuy ? "arrowUp" : "arrowDown",
          size: 1,
        };
      })
      .sort(function (left, right) {
        return left.time < right.time ? -1 : 1;
      });
    if (markers.length) {
      if (typeof lc.createSeriesMarkers === "function") lc.createSeriesMarkers(series, markers);
      else if (typeof series.setMarkers === "function") series.setMarkers(markers);
    }

    // The whole year would squeeze the tracking window into the last few
    // pixels, so open on the traded stretch and leave the rest scrollable.
    var firstEvent = position.events.length ? position.events[0].date : null;
    var fromIndex = 0;
    if (firstEvent) {
      var index = values.findIndex(function (point) {
        return point.time >= firstEvent;
      });
      fromIndex = Math.max(0, (index < 0 ? values.length : index) - 12);
    }
    var applyRange = function () {
      if (fromIndex > 0 && values.length - fromIndex > 3) {
        chart.timeScale().setVisibleRange({
          from: values[fromIndex].time,
          to: values[values.length - 1].time,
        });
      } else {
        chart.timeScale().fitContent();
      }
    };

    activeChart = chart;
    // A chart created while the container still measures 0 wide keeps a bar
    // spacing that leaves the candles crushed against the right edge, so the
    // range has to be reapplied once a real width arrives.
    var sized = container.clientWidth > 0;
    var resize = function () {
      if (!activeChart || !container.clientWidth) return;
      activeChart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      });
      if (!sized) {
        sized = true;
        applyRange();
      }
    };
    applyRange();
    if (typeof ResizeObserver === "function") {
      activeResizeObserver = new ResizeObserver(resize);
      activeResizeObserver.observe(container);
    } else {
      window.addEventListener("resize", resize, { once: true });
    }
    resize();
    return counts;
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
      ".active-etf-change-card li[data-position-stock],.daily-change-panel tr[data-position-stock]{cursor:pointer;transition:background .16s ease}" +
      ".active-etf-change-card li[data-position-stock]{border-radius:7px}" +
      ".active-etf-change-card li[data-position-stock]:hover,.daily-change-panel tr[data-position-stock]:hover>td{background:#eef8f7}" +
      ".active-etf-change-card li[data-position-stock]:focus-visible,.daily-change-panel tr[data-position-stock]:focus-visible{outline:3px solid rgba(8,117,111,.32);outline-offset:-2px}" +
      ".daily-change-panel tr[data-position-stock] td[data-label=\"股票\"] strong{text-decoration:underline;text-decoration-color:rgba(8,117,111,.45);text-underline-offset:3px}" +
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
      // The release stylesheet paints every th navy; these selectors are scoped
      // to the dialog so the table reads as a panel, not a site table.
      // min-width:0 overrides the release stylesheet's 900px table floor, which
      // pushed 累計持股 off the edge of the dialog.
      ".active-etf-position-dialog .active-etf-position-table{width:100%;min-width:0;border-collapse:collapse;font-size:12.5px;background:#fff}" +
      ".active-etf-position-dialog .active-etf-position-table th{padding:6px 6px;border-bottom:1px solid #d6dee6;background:#fff;color:#667483;font-size:11.5px;font-weight:800;text-align:right;white-space:nowrap}" +
      ".active-etf-position-dialog .active-etf-position-table th:first-child,.active-etf-position-dialog .active-etf-position-table td:first-child{text-align:left}" +
      ".active-etf-position-dialog .active-etf-position-table td{padding:6px 6px;border-bottom:1px solid #edf1f4;background:#fff;color:#06275f;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}" +
      ".active-etf-position-dialog .active-etf-position-table td.is-buy{color:#c23d4b;font-weight:800}" +
      ".active-etf-position-dialog .active-etf-position-table td.is-sell{color:#16845b;font-weight:800}" +
      ".active-etf-position-scroll{overflow-x:auto}" +
      ".active-etf-position-dialog .active-etf-position-source{display:inline-block;margin-left:6px;padding:1px 5px;border-radius:4px;background:#f0f3f6;color:#8794a3;font-size:10px;font-weight:800}" +
      ".active-etf-position-chart{width:100%;height:280px;margin:0 0 6px}" +
      ".active-etf-position-chart-note{margin:0 0 12px;color:#667483;font-size:12px;font-weight:700}" +
      ".active-etf-position-chart-missing{margin:0 0 12px;padding:9px 12px;border-radius:8px;background:#f5f8fa;color:#667483;font-size:12.5px}" +
      "@media(max-width:720px){.active-etf-position-chart{height:220px}}" +
      ".active-etf-position-closed{margin:14px 0 0;padding-top:12px;border-top:1px solid #edf1f4}" +
      ".active-etf-position-closed p{margin:0 0 7px;color:#667483;font-size:12px;font-weight:750}" +
      ".active-etf-position-closed div{display:flex;flex-wrap:wrap;gap:6px}" +
      ".active-etf-position-chip{padding:5px 10px;border:1px solid #d6dee6;border-radius:999px;background:#fff;color:#33485f;font-size:12px;font-family:inherit;cursor:pointer}" +
      ".active-etf-position-chip:hover{background:#f3f6f8}" +
      ".active-etf-position-chip b{margin-left:4px}" +
      ".active-etf-position-chip.is-up b{color:#c23d4b}" +
      ".active-etf-position-chip.is-down b{color:#16845b}" +
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
    clearChart();
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = previousBodyOverflow;
    if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
  }

  function showMessage(modal, text) {
    // Switching positions replaces the body, so drop the old chart first or it
    // keeps observing a detached node.
    clearChart();
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

  /*
   * A 加減碼 card only lists the stocks that moved on its own date, so a stock
   * the ETF has fully sold is unreachable from the grid — exactly the position
   * whose realised result is most worth seeing. Offer them from inside the
   * dialog instead.
   */
  function closedPositionLinks(ledger, current) {
    var closed = (ledger.positions || []).filter(function (item) {
      return item.closed && item.stockCode !== current.stockCode && item.events.length;
    });
    if (!closed.length) return "";
    closed.sort(function (left, right) {
      return (left.realizedTwd || 0) - (right.realizedTwd || 0);
    });
    var chips = closed
      .map(function (item) {
        var tone = item.realizedTwd === null || item.realizedTwd === undefined
          ? ""
          : toneClass(item.realizedTwd);
        var result = item.realizedTwd === null || item.realizedTwd === undefined
          ? "成本未知"
          : percent(item.realizedPct);
        return (
          '<button type="button" class="active-etf-position-chip' + tone +
          '" data-closed-stock="' + item.stockCode + '">' +
          item.stockName + " " + item.stockCode + " <b>" + result + "</b></button>"
        );
      })
      .join("");
    return (
      '<div class="active-etf-position-closed"><p>' + ledger.instrumentName +
      " 追蹤期內已出清（點擊查看績效）</p><div>" + chips + "</div></div>"
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
    if (position.externalEventCount > 0 && ledger.officialBaselineDate) {
      notes.push(
        ledger.baselineDate.replace(/-/g, "/") + " ~ " +
        ledger.officialBaselineDate.replace(/-/g, "/") +
        " 的持股張數來自第三方每日觀測（籌碼小宇），非投信官方揭露；" +
        "這段期間的加減碼張數由張數差推導，金額一律以 TWSE／TPEx 官方收盤重新計價。" +
        "明細表中這些日期標示「觀測」。",
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
        var tag =
          event.source === "external"
            ? '<small class="active-etf-position-source">觀測</small>'
            : "";
        return (
          "<tr><td>" + event.date.replace(/-/g, "/") + tag + "</td>" +
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
      '<div class="active-etf-position-chart-slot"></div>' +
      '<div class="active-etf-position-scroll"><table class="active-etf-position-table">' +
      "<thead><tr><th>日期</th><th>動作</th><th>張數</th><th>價格</th><th>金額</th><th>累計持股</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>" +
      closedPositionLinks(ledger, position) +
      '<p class="active-etf-position-method">' + ledger.costMethodology +
      " 追蹤期 " + ledger.baselineDate.replace(/-/g, "/") + " ~ " +
      ledger.latestDate.replace(/-/g, "/") + "（" + ledger.sessionCount + " 個交易日）。</p>";

    mountChart(modal, body.querySelector(".active-etf-position-chart-slot"), position);
  }

  /*
   * The chart is filled in after the rest of the dialog so a missing K-line —
   * every overseas holding, and any domestic stock not yet backfilled — never
   * blocks the numbers the user came for.
   */
  function mountChart(modal, slot, position) {
    if (!slot) return;
    var requestId = activeRequest;
    var domestic = /^\d{4,6}$/.test(position.stockCode);
    if (!domestic) {
      slot.innerHTML =
        '<p class="active-etf-position-chart-missing">海外標的沒有台灣官方日 K，僅顯示操作明細。</p>';
      return;
    }
    Promise.all([loadCandles(position.stockCode), loadLibrary()])
      .then(function (results) {
        if (requestId !== activeRequest || !modal.classList.contains("is-open")) return;
        var values = results[0];
        var lc = results[1];
        if (!values || !values.length) {
          slot.innerHTML =
            '<p class="active-etf-position-chart-missing">目前沒有這檔股票的官方日 K 資料。</p>';
          return;
        }
        slot.innerHTML =
          '<div class="active-etf-position-chart"></div>' +
          '<p class="active-etf-position-chart-note"></p>';
        var counts = drawChart(
          slot.querySelector(".active-etf-position-chart"),
          lc,
          values,
          position,
        );
        var parts = [];
        if (counts.buy) parts.push("🔼 加碼 " + counts.buy + " 天");
        if (counts.sell) parts.push("🔽 減碼 " + counts.sell + " 天");
        slot.querySelector(".active-etf-position-chart-note").textContent = parts.length
          ? parts.join(" · ") + "（這檔 ETF 的操作日 · 可捲動或縮放查看整年走勢）"
          : "近一年官方日 K（追蹤期內沒有可標記的操作日）";
      })
      .catch(function () {
        if (requestId !== activeRequest) return;
        slot.innerHTML =
          '<p class="active-etf-position-chart-missing">K 線載入失敗，操作明細不受影響。</p>';
      });
  }

  function openRecord(etfCode, etfName, stockCode, stockName, trigger) {
    var modal = ensureModal();
    var requestId = ++activeRequest;
    openContext = { etfCode: etfCode, etfName: etfName };
    if (trigger) lastTrigger = trigger;
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
      markActivatable(
        item,
        etfCode,
        etfName.trim(),
        stockCode,
        nameElement.textContent.trim(),
      );
    });
  }

  function markActivatable(element, etfCode, etfName, stockCode, stockName) {
    element.dataset.positionStock = stockCode;
    element.dataset.positionEtf = etfCode;
    element.dataset.positionEtfName = etfName;
    element.dataset.positionName = stockName;
    element.setAttribute("role", "button");
    element.setAttribute("tabindex", "0");
    element.setAttribute(
      "title",
      "查看 " + etfName + " 操作 " + stockName + " 的 K 線與加減碼紀錄",
    );
  }

  /*
   * The per-ETF detail page shows the same daily changes as a table. Its rows
   * open the same dialog, with the ETF taken from the detail header so it
   * follows whichever ETF is on screen.
   */
  function decorateDetailPanel(panel) {
    var header = document.querySelector(".detail-header");
    var eyebrow = header && header.querySelector(".eyebrow");
    var match = eyebrow && eyebrow.textContent.match(/(\d{5}[A-Z])/);
    if (!match) return;
    var etfCode = match[1];
    var titleElement = header.querySelector("h2");
    var etfName = titleElement ? titleElement.textContent.trim() : etfCode;
    panel.querySelectorAll("tbody tr").forEach(function (row) {
      var cell = row.querySelector('td[data-label="股票"]');
      if (!cell) return;
      var codeElement = cell.querySelector(".code-note");
      var nameElement = cell.querySelector("strong");
      if (!codeElement || !nameElement) return;
      var stockCode = codeElement.textContent.trim();
      if (!stockCode || row.dataset.positionStock === stockCode) return;
      markActivatable(row, etfCode, etfName, stockCode, nameElement.textContent.trim());
    });
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    if (scope.matches && scope.matches(".active-etf-change-card")) decorateCard(scope);
    scope.querySelectorAll(".active-etf-change-card").forEach(decorateCard);
    if (scope.matches && scope.matches(".daily-change-panel")) decorateDetailPanel(scope);
    scope.querySelectorAll(".daily-change-panel").forEach(decorateDetailPanel);
    // React swaps the detail body in place, so a re-render that only replaces
    // the rows still has to be picked up.
    if (scope.closest && scope.closest(".daily-change-panel")) {
      decorateDetailPanel(scope.closest(".daily-change-panel"));
    }
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
      if (!event.target.closest) return;
      var chip = event.target.closest("[data-closed-stock]");
      if (chip && openContext) {
        var ledger = ledgers.get(openContext.etfCode);
        var target = ledger && (ledger.positions || []).find(function (item) {
          return item.stockCode === chip.dataset.closedStock;
        });
        if (target) {
          openRecord(
            openContext.etfCode,
            openContext.etfName,
            target.stockCode,
            target.stockName,
            null,
          );
        }
        return;
      }
      var item = event.target.closest("[data-position-stock]");
      if (item) activate(item);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeModal();
        return;
      }
      var item = event.target.closest ? event.target.closest("[data-position-stock]") : null;
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
