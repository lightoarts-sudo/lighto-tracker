/*
 * PoPoStock consensus stock K-line dialog.
 *
 * Stocks listed in consensus-stock-kline-index.json become keyboard-accessible
 * table cells. Activating one opens its official one-year OHLCV history in a
 * modal candlestick chart. The script is observer-driven because React swaps
 * the daily/weekly consensus tables without a full page reload.
 */
(function () {
  "use strict";

  var LIBRARY_FILE = "lightweight-charts.standalone.production.js";
  var INDEX_FILE = "data/consensus-stock-kline-index.json";
  var stockNames = new Map();
  var stockBuySessions = new Map();
  var libraryPromise = null;
  var activeChart = null;
  var activeResizeObserver = null;
  var activeRequest = 0;
  var lastTrigger = null;
  var previousBodyOverflow = "";

  function baseUrl() {
    var base = document.querySelector("base[href]");
    if (base) return new URL(base.getAttribute("href"), window.location.href).href.replace(/\/$/, "");
    var match = window.location.href.match(/^(https?:\/\/[^/]+\/popostock)/);
    return match ? match[1] : "";
  }

  function loadLibrary() {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    if (libraryPromise) return libraryPromise;

    libraryPromise = new Promise(function (resolve, reject) {
      var source = baseUrl() + "/" + LIBRARY_FILE;
      var existing = Array.from(document.scripts).find(function (script) {
        return script.src === source || script.src.endsWith("/" + LIBRARY_FILE);
      });
      var script = existing || document.createElement("script");
      var finish = function () {
        if (window.LightweightCharts) resolve(window.LightweightCharts);
        else reject(new Error("LightweightCharts global missing"));
      };
      script.addEventListener("load", finish, { once: true });
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

  function loadStockIndex() {
    return fetch(baseUrl() + "/" + INDEX_FILE, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        return Array.isArray(payload.stocks) ? payload.stocks : [];
      })
      .catch(function () {
        return fetch(baseUrl() + "/api/instruments", { cache: "no-store" })
          .then(function (response) {
            if (!response.ok) throw new Error("HTTP " + response.status);
            return response.json();
          })
          .then(function (payload) {
            var instruments = Array.isArray(payload)
              ? payload
              : Array.isArray(payload.instruments)
                ? payload.instruments
                : [];
            return instruments.filter(function (item) {
              return item.category === "stock";
            });
          });
      });
  }

  function stockCodeFromCell(cell) {
    if (cell.dataset.consensusStockCode) return cell.dataset.consensusStockCode;
    var codeNote = cell.querySelector(".code-note");
    var match = (codeNote ? codeNote.textContent : cell.textContent).match(/\b\d{4}\b/);
    return match ? match[0] : "";
  }

  function decorateCell(cell) {
    var code = stockCodeFromCell(cell);
    if (!stockNames.has(code)) return;
    var nameElement = cell.querySelector("strong");
    var name = (nameElement ? nameElement.textContent : stockNames.get(code) || code).trim();
    cell.dataset.consensusStockKlineCode = code;
    cell.dataset.consensusStockKlineName = name;
    cell.classList.add("consensus-stock-kline-cell");
    cell.setAttribute("role", "button");
    cell.setAttribute("tabindex", "0");
    cell.setAttribute("aria-label", name + " " + code + "，查看一年日 K");
    cell.setAttribute("title", "查看 " + name + "（" + code + "）一年日 K");
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    if (scope.matches && scope.matches(".consensus-table tbody td:first-child")) {
      decorateCell(scope);
    }
    scope
      .querySelectorAll(".consensus-table tbody td:first-child")
      .forEach(decorateCell);
  }

  function installStyles() {
    if (document.getElementById("consensus-stock-kline-styles")) return;
    var style = document.createElement("style");
    style.id = "consensus-stock-kline-styles";
    style.textContent =
      ".consensus-stock-kline-cell{position:relative;cursor:pointer;transition:background .16s ease,color .16s ease}" +
      ".consensus-stock-kline-cell:hover{background:#eef8f7;color:#08756f}" +
      ".consensus-stock-kline-cell:focus-visible{outline:3px solid rgba(8,117,111,.32);outline-offset:-3px}" +
      ".consensus-stock-kline-cell::after{content:'查看 K 線';display:block;margin-top:4px;color:#08756f;font-size:11px;font-weight:850;white-space:nowrap}" +
      ".consensus-kline-modal{position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;padding:24px;background:rgba(5,24,48,.66);backdrop-filter:blur(4px)}" +
      ".consensus-kline-modal.is-open{display:flex}" +
      ".consensus-kline-dialog{width:min(1040px,100%);max-height:min(850px,calc(100vh - 40px));overflow:auto;border:1px solid #d6dee6;border-radius:16px;background:#fff;box-shadow:0 28px 70px rgba(3,25,52,.3)}" +
      ".consensus-kline-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:20px 22px 14px;border-bottom:1px solid #e4e9ee}" +
      ".consensus-kline-eyebrow{margin:0 0 4px;color:#08756f;font-size:12px;font-weight:900;letter-spacing:.08em}" +
      ".consensus-kline-title{margin:0;color:#06275f;font-size:24px;line-height:1.25}" +
      ".consensus-kline-subtitle{margin:6px 0 0;color:#667483;font-size:13px}" +
      ".consensus-kline-close{flex:0 0 auto;width:38px;height:38px;border:1px solid #d6dee6;border-radius:50%;background:#fff;color:#33485f;font-size:22px;line-height:1;cursor:pointer}" +
      ".consensus-kline-close:hover{background:#f3f6f8}" +
      ".consensus-kline-body{padding:18px 22px 22px}" +
      ".consensus-kline-reading{display:flex;align-items:center;gap:16px;min-height:42px;margin-bottom:10px;padding:8px 12px;border-radius:9px;background:#f5f8fa;color:#667483;font-size:13px}" +
      ".consensus-kline-reading strong{color:#06275f;font-size:20px}" +
      ".consensus-kline-reading span:last-child{margin-left:auto}" +
      ".consensus-kline-chart{width:100%;height:430px}" +
      ".consensus-kline-marker-note{margin:10px 0 0;color:#667483;font-size:12px;font-weight:700}" +
      ".consensus-kline-message{display:grid;place-items:center;min-height:260px;color:#667483;font-weight:750}" +
      "@media(max-width:720px){.consensus-kline-modal{padding:10px}.consensus-kline-dialog{max-height:calc(100vh - 20px);border-radius:12px}.consensus-kline-header{padding:16px}.consensus-kline-title{font-size:20px}.consensus-kline-body{padding:14px 12px 16px}.consensus-kline-chart{height:340px}.consensus-kline-reading{align-items:flex-start;flex-wrap:wrap}.consensus-kline-reading span:last-child{width:100%;margin-left:0}}";
    document.head.appendChild(style);
  }

  function ensureModal() {
    var modal = document.getElementById("consensus-stock-kline-modal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "consensus-stock-kline-modal";
    modal.className = "consensus-kline-modal";
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML =
      '<section class="consensus-kline-dialog" role="dialog" aria-modal="true" aria-labelledby="consensus-kline-title">' +
      '<header class="consensus-kline-header"><div><p class="consensus-kline-eyebrow">共識加減碼股票</p>' +
      '<h2 class="consensus-kline-title" id="consensus-kline-title"></h2>' +
      '<p class="consensus-kline-subtitle">近一年官方日 K · 含成交量</p></div>' +
      '<button class="consensus-kline-close" type="button" aria-label="關閉 K 線">×</button></header>' +
      '<div class="consensus-kline-body"><div class="consensus-kline-message">載入中…</div></div></section>';
    document.body.appendChild(modal);

    modal.querySelector(".consensus-kline-close").addEventListener("click", closeModal);
    modal.addEventListener("click", function (event) {
      if (event.target === modal) closeModal();
    });
    return modal;
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

  function closeModal() {
    var modal = document.getElementById("consensus-stock-kline-modal");
    if (!modal || !modal.classList.contains("is-open")) return;
    activeRequest += 1;
    clearChart();
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = previousBodyOverflow;
    if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
  }

  function showMessage(modal, text) {
    clearChart();
    var body = modal.querySelector(".consensus-kline-body");
    body.innerHTML = "";
    var message = document.createElement("div");
    message.className = "consensus-kline-message";
    message.textContent = text;
    body.appendChild(message);
  }

  /*
   * Mark the sessions where active ETFs added to the stock with an up arrow
   * under the candle. Markers whose date is not in the series are dropped:
   * the consensus history only reaches back to the holding-change baseline,
   * while the chart shows a full year.
   */
  function applyBuyMarkers(lc, series, code, values) {
    var sessions = stockBuySessions.get(code) || [];
    if (!sessions.length) return 0;
    var chartDates = new Set(
      values.map(function (point) {
        return point.time;
      }),
    );
    var markers = sessions
      .filter(function (session) {
        return session && chartDates.has(session.date);
      })
      .map(function (session) {
        return {
          time: session.date,
          position: "belowBar",
          color: "#c23d4b",
          shape: "arrowUp",
          size: 1,
        };
      });
    if (!markers.length) return 0;
    if (typeof lc.createSeriesMarkers === "function") {
      lc.createSeriesMarkers(series, markers);
    } else if (typeof series.setMarkers === "function") {
      series.setMarkers(markers);
    } else {
      return 0;
    }
    return markers.length;
  }

  function renderChart(modal, lc, code, payload) {
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
    if (!values.length) {
      showMessage(modal, "目前沒有可顯示的官方 K 線資料。");
      return;
    }

    clearChart();
    var latest = values[values.length - 1];
    var body = modal.querySelector(".consensus-kline-body");
    body.innerHTML = "";
    var reading = document.createElement("div");
    reading.className = "consensus-kline-reading";
    reading.innerHTML =
      "<strong>" + Number(latest.close).toLocaleString("zh-TW") + "</strong>" +
      "<span>開 " + Number(latest.open).toLocaleString("zh-TW") +
      "　高 " + Number(latest.high).toLocaleString("zh-TW") +
      "　低 " + Number(latest.low).toLocaleString("zh-TW") + "</span>" +
      "<span>" + latest.time.replaceAll("-", "/") + " · " + values.length + " 個交易日</span>";
    var chartElement = document.createElement("div");
    chartElement.className = "consensus-kline-chart";
    body.appendChild(reading);
    body.appendChild(chartElement);

    var chart = lc.createChart(chartElement, {
      layout: {
        background: { type: lc.ColorType.Solid, color: "#ffffff" },
        textColor: "#667483",
        fontFamily: 'var(--font-geist-sans), "Noto Sans TC", Arial, sans-serif',
        fontSize: 12,
      },
      width: chartElement.clientWidth,
      height: chartElement.clientHeight,
      crosshairMode: lc.CrosshairMode.Normal,
      grid: {
        vertLines: { color: "#edf1f4" },
        horzLines: { color: "#edf1f4" },
      },
      rightPriceScale: {
        borderColor: "#d6dee6",
        scaleMargins: { top: 0.08, bottom: 0.27 },
      },
      timeScale: {
        borderColor: "#d6dee6",
        rightOffset: 3,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });
    var candles = chart.addSeries(lc.CandlestickSeries, {
      upColor: "#c23d4b",
      downColor: "#16845b",
      borderUpColor: "#c23d4b",
      borderDownColor: "#16845b",
      wickUpColor: "#c23d4b",
      wickDownColor: "#16845b",
      priceLineVisible: false,
    });
    candles.setData(
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
    var volume = chart.addSeries(lc.HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    volume.setData(
      values.map(function (point) {
        return {
          time: point.time,
          value: Number(point.volume || 0),
          color: point.close >= point.open
            ? "rgba(194,61,75,.5)"
            : "rgba(22,132,91,.5)",
        };
      }),
    );
    var markerCount = applyBuyMarkers(lc, candles, code, values);
    if (markerCount) {
      var legend = document.createElement("p");
      legend.className = "consensus-kline-marker-note";
      legend.textContent =
        "🔼 主動 ETF 加碼日 · 共 " + markerCount + " 天（僅涵蓋共識統計起算後的交易日）";
      body.appendChild(legend);
    }
    chart.timeScale().fitContent();
    activeChart = chart;

    var resize = function () {
      if (!activeChart || !chartElement.clientWidth) return;
      activeChart.applyOptions({
        width: chartElement.clientWidth,
        height: chartElement.clientHeight,
      });
    };
    if (typeof ResizeObserver === "function") {
      activeResizeObserver = new ResizeObserver(resize);
      activeResizeObserver.observe(chartElement);
    } else {
      window.addEventListener("resize", resize, { once: true });
    }
    resize();
  }

  function openStock(code, name, trigger) {
    var modal = ensureModal();
    var requestId = ++activeRequest;
    lastTrigger = trigger;
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    modal.querySelector(".consensus-kline-title").textContent =
      name + "（" + code + "）";
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    showMessage(modal, "載入 " + name + " K 線…");
    modal.querySelector(".consensus-kline-close").focus();

    Promise.all([
      fetch(baseUrl() + "/data/market/" + encodeURIComponent(code) + ".json", {
        cache: "no-store",
      }).then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      }),
      loadLibrary(),
    ])
      .then(function (results) {
        if (requestId !== activeRequest) return;
        renderChart(modal, results[1], code, results[0]);
      })
      .catch(function () {
        if (requestId !== activeRequest) return;
        showMessage(modal, "K 線載入失敗，請稍後重試。");
      });
  }

  function activate(cell) {
    var code = cell.dataset.consensusStockKlineCode;
    if (!code || !stockNames.has(code)) return;
    openStock(
      code,
      cell.dataset.consensusStockKlineName || stockNames.get(code) || code,
      cell,
    );
  }

  function watch() {
    installStyles();
    loadStockIndex()
      .then(function (stocks) {
        stocks.forEach(function (stock) {
          var code = String(stock.code || stock.symbol || "");
          if (/^\d{4}$/.test(code)) {
            stockNames.set(code, String(stock.name || code));
            stockBuySessions.set(
              code,
              Array.isArray(stock.buySessions) ? stock.buySessions : [],
            );
          }
        });
        scan(document);
        new MutationObserver(function (mutations) {
          mutations.forEach(function (mutation) {
            mutation.addedNodes.forEach(function (node) {
              if (node.nodeType === 1) scan(node);
            });
          });
        }).observe(document.body, { childList: true, subtree: true });
      })
      .catch(function () {
        // Keep the consensus table usable even if both index sources fail.
      });

    document.addEventListener("click", function (event) {
      var cell = event.target.closest
        ? event.target.closest(".consensus-stock-kline-cell")
        : null;
      if (cell) activate(cell);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeModal();
        return;
      }
      var cell = event.target.closest
        ? event.target.closest(".consensus-stock-kline-cell")
        : null;
      if (cell && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        activate(cell);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
