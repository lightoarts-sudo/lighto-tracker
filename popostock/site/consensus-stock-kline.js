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
  var US_INDEX_FILE = "data/us-holding-index.json";
  var stockNames = new Map();
  var stockBuySessions = new Map();
  var stockSellSessions = new Map();
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

  /*
   * 美股清單獨立一個檔案，不併進共識索引：共識索引由台股的加減碼金額門檻
   * 產生，把沒有價格的外國持股塞進去會讓那份資料的意義變糊。檔案不存在或
   * 讀失敗時回空陣列，台股那側照常運作。
   */
  function loadUsHoldingIndex() {
    return fetch(baseUrl() + "/" + US_INDEX_FILE, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) {
        return Array.isArray(payload.stocks) ? payload.stocks : [];
      })
      .catch(function () {
        return [];
      });
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

  /*
   * 台股是四碼數字；外國持股多數投信寫成彭博式的 "NVDA US"，00989A 寫純代號。
   * 英文代號不像數字那樣好認——公司名稱裡本來就有大寫字母（"ADVANCED MICRO
   * DEVICES"），純靠字型比對會誤判。所以英文這條一律要求命中 stockNames，
   * 也就是真的有抓到 K 線的那批，抓不到的就維持不可點。
   */
  function stockCodeFromCell(cell) {
    if (cell.dataset.consensusStockCode) {
      return normalizeForeignCode(cell.dataset.consensusStockCode);
    }
    var codeNote = cell.querySelector(".code-note");
    var text = (codeNote ? codeNote.textContent : cell.textContent) || "";
    /*
     * 日股、韓股、港股的代號也是數字（"6981 JP" 村田、"3308 HK" 中際旭創），
     * 直接套四碼規則會當成台股，開出另一家公司的 K 線。今天還不會踩到是因為
     * 這些號碼剛好不在共識清單裡，但兩邊的號碼段本來就重疊，清單一長就會中。
     * 看到非美股的市場後綴就直接放棄——這些市場我們本來就沒有行情。
     */
    if (/\b\d{3,6}\s+(?!US\b)[A-Z]{2}\b/.test(text)) return "";
    var tw = text.match(/\b\d{4}\b/);
    if (tw) return tw[0];
    var tokens = text.match(/\b[A-Z]{1,5}(?:\s+US)?\b/g) || [];
    for (var i = 0; i < tokens.length; i += 1) {
      var candidate = normalizeForeignCode(tokens[i]);
      if (candidate && stockNames.has(candidate)) return candidate;
    }
    return "";
  }

  function normalizeForeignCode(raw) {
    return String(raw || "").trim().replace(/\s+US$/, "").trim();
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
      ".consensus-kline-moves{margin:18px 0 0;border-top:1px solid #e4e9ee;padding-top:14px}" +
      ".consensus-kline-moves h4{margin:0 0 2px;color:#06275f;font-size:15px;font-weight:900}" +
      ".consensus-kline-moves .hint{margin:0 0 10px;color:#8b98ab;font-size:12px;font-weight:700}" +
      ".consensus-kline-moves table{width:100%;border-collapse:collapse;font-size:13px}" +
      ".consensus-kline-moves th{padding:7px 8px;background:#06275f;color:#ffd43b;font-size:12px;font-weight:900;text-align:left;white-space:nowrap}" +
      ".consensus-kline-moves th.num,.consensus-kline-moves td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}" +
      ".consensus-kline-moves td{padding:7px 8px;border-bottom:1px solid #eef1f5;color:#33485f;vertical-align:top}" +
      ".consensus-kline-moves tr.is-first td{border-top:1px solid #dde3ea}" +
      ".consensus-kline-moves td.date{color:#06275f;font-weight:900;white-space:nowrap}" +
      ".consensus-kline-moves td.etf i{font-style:normal;color:#8b98ab;font-weight:700;margin-left:6px}" +
      ".consensus-kline-moves .dir{display:inline-block;border-radius:999px;padding:1px 9px;color:#fff;font-size:11px;font-weight:900}" +
      ".consensus-kline-moves .dir.buy{background:#c23d4b}.consensus-kline-moves .dir.sell{background:#16845b}" +
      ".consensus-kline-moves td.buy{color:#c23d4b;font-weight:900}.consensus-kline-moves td.sell{color:#16845b;font-weight:900}" +
      ".consensus-kline-moves tr.is-link{cursor:pointer}" +
      ".consensus-kline-moves tr.is-link:hover td{background:#eef8f7}" +
      ".consensus-kline-moves tr.is-link:focus-visible td{outline:2px solid rgba(8,117,111,.4);outline-offset:-2px}" +
      ".consensus-kline-moves td.etf b.go{display:inline-block;margin-left:8px;color:#08756f;" +
      "font-size:11.5px;font-weight:900;opacity:0;transition:opacity .14s ease}" +
      ".consensus-kline-moves tr.is-link:hover td.etf b.go," +
      ".consensus-kline-moves tr.is-link:focus-visible td.etf b.go{opacity:1}" +
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
  function visibleSessions(map, code, chartDates) {
    return (map.get(code) || []).filter(function (session) {
      return session && chartDates.has(session.date);
    });
  }

  function applyMoveMarkers(lc, series, buys, sells) {
    var markers = buys
      .map(function (session) {
        return {
          time: session.date,
          position: "belowBar",
          color: "#c23d4b",
          shape: "arrowUp",
          size: 1,
        };
      })
      .concat(
        sells.map(function (session) {
          return {
            time: session.date,
            position: "aboveBar",
            color: "#16845b",
            shape: "arrowDown",
            size: 1,
          };
        }),
      )
      // 同一天可能同時有加碼與減碼，標記必須按時間排序才畫得出來。
      .sort(function (left, right) {
        return left.time < right.time ? -1 : left.time > right.time ? 1 : 0;
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

  /*
   * 累積買超：把每天各檔 ETF 的加碼張數減去減碼張數，沿著交易日累加。
   * 用張數而非金額——同一檔股票的價格在這幾個月動輒差一倍，用金額累加
   * 會把「價格漲了」混進「買了多少」裡面。
   *
   * 從第一筆異動的前一個交易日以 0 起算，線才看得出是從哪裡開始爬的；
   * 之後每個交易日都補一個點，沒有異動的日子維持前一天的水位。
   */
  function buildNetBuySeries(values, buys, sells) {
    var delta = new Map();
    buys.forEach(function (session) {
      delta.set(session.date, (delta.get(session.date) || 0) + (session.lots || 0));
    });
    sells.forEach(function (session) {
      delta.set(session.date, (delta.get(session.date) || 0) - (session.lots || 0));
    });
    if (!delta.size) return [];
    var firstIndex = -1;
    for (var i = 0; i < values.length; i += 1) {
      if (delta.has(values[i].time)) {
        firstIndex = i;
        break;
      }
    }
    if (firstIndex < 0) return [];
    var start = Math.max(0, firstIndex - 1);
    var total = 0;
    var points = [];
    for (var j = start; j < values.length; j += 1) {
      total += delta.get(values[j].time) || 0;
      points.push({ time: values[j].time, value: Math.round(total * 100) / 100 });
    }
    return points;
  }

  function lotText(value) {
    return Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  // 金額用億／萬分段，和站上其他地方一致；沒有官方收盤價時不編金額。
  function moneyText(amount) {
    if (typeof amount !== "number" || !isFinite(amount)) return "—";
    var value = Math.abs(amount);
    if (value >= 1e8) return (value / 1e8).toFixed(2) + " 億";
    if (value >= 1e4) return Math.round(value / 1e4).toLocaleString("en-US") + " 萬";
    return Math.round(value).toLocaleString("en-US") + " 元";
  }

  /*
   * 每一天一組列，每檔 ETF 一列：使用者要的是「哪一天、哪一檔、幾張、大約多少
   * 錢」，只給日期加總看不出是誰買的。日期新到舊排，最近的動作在最上面。
   */
  function renderMoveList(body, buys, sells) {
    var rows = [];
    buys.forEach(function (session) {
      rows.push({ dir: "buy", session: session });
    });
    sells.forEach(function (session) {
      rows.push({ dir: "sell", session: session });
    });
    if (!rows.length) return;
    rows.sort(function (left, right) {
      if (left.session.date !== right.session.date) {
        return left.session.date < right.session.date ? 1 : -1;
      }
      return left.dir === right.dir ? 0 : left.dir === "buy" ? -1 : 1;
    });

    var html = "";
    rows.forEach(function (row) {
      var etfs = row.session.etfs || [];
      var label = row.dir === "buy" ? "加碼" : "減碼";
      var sign = row.dir === "buy" ? "+" : "−";
      if (!etfs.length) {
        etfs = [{ code: "", name: "—", lots: row.session.lots, amountTwd: row.session.amountTwd }];
      }
      etfs.forEach(function (etf, index) {
        // 只有主動式 ETF 有操作紀錄可查（代號形如 00981A）；其餘不給點，
        // 否則點下去只會開一個「查無紀錄」的空視窗。
        var linkable = /^[0-9]{5}[A-Z]$/.test(etf.code || "");
        var classes = (index === 0 ? "is-first " : "") + (linkable ? "is-link" : "");
        html +=
          "<tr" + (classes.trim() ? ' class="' + classes.trim() + '"' : "") +
          (linkable
            ? ' data-etf="' + etf.code + '" data-etf-name="' +
              String(etf.name || etf.code).replace(/"/g, "&quot;") + '" tabindex="0"' +
              ' title="查看 ' + etf.code + ' 對這檔股票的完整操作紀錄"'
            : "") + ">" +
          '<td class="date">' + (index === 0 ? row.session.date : "") + "</td>" +
          "<td>" + (index === 0 ? '<span class="dir ' + row.dir + '">' + label + "</span>" : "") + "</td>" +
          '<td class="etf">' + (etf.name || etf.code || "—") +
          (etf.code ? "<i>" + etf.code + "</i>" : "") +
          (linkable ? '<b class="go">操作紀錄 ›</b>' : "") + "</td>" +
          '<td class="num ' + row.dir + '">' +
          (typeof etf.lots === "number" ? sign + etf.lots.toLocaleString("en-US") + " 張" : "—") + "</td>" +
          '<td class="num ' + row.dir + '">' +
          (typeof etf.amountTwd === "number" ? sign + moneyText(etf.amountTwd) : "—") + "</td>" +
          "</tr>";
      });
    });

    var section = document.createElement("div");
    section.className = "consensus-kline-moves";
    section.innerHTML =
      "<h4>共識加減碼明細 · 加碼 " + buys.length + " 天、減碼 " + sells.length + " 天</h4>" +
      '<p class="hint">僅涵蓋共識統計起算後的交易日；金額以當日官方均價推估，非實際成交價。</p>' +
      "<table><thead><tr><th>日期</th><th>方向</th><th>ETF</th>" +
      '<th class="num">張數</th><th class="num">約當金額</th></tr></thead>' +
      "<tbody>" + html + "</tbody></table>";
    body.appendChild(section);
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
    var chartDates = new Set(
      values.map(function (point) {
        return point.time;
      }),
    );
    var buys = visibleSessions(stockBuySessions, code, chartDates);
    var sells = visibleSessions(stockSellSessions, code, chartDates);
    // 累積買超放在獨立的窗格，和 K 線共用同一條時間軸（Lightweight Charts v5）。
    var netData = buildNetBuySeries(values, buys, sells);
    if (netData.length) {
      var net = chart.addSeries(
        lc.BaselineSeries,
        {
          baseValue: { type: "price", price: 0 },
          topLineColor: "#c23d4b",
          topFillColor1: "rgba(194,61,75,.30)",
          topFillColor2: "rgba(194,61,75,.03)",
          bottomLineColor: "#16845b",
          bottomFillColor1: "rgba(22,132,91,.03)",
          bottomFillColor2: "rgba(22,132,91,.30)",
          lineWidth: 2,
          priceLineVisible: false,
          priceFormat: { type: "custom", minMove: 0.01, formatter: lotText },
        },
        1,
      );
      net.setData(netData);
      chartElement.style.height = "540px";
      var panes = typeof chart.panes === "function" ? chart.panes() : [];
      if (panes.length > 1) {
        panes[0].setHeight(390);
        panes[1].setHeight(150);
      }
    }
    var markerCount = applyMoveMarkers(lc, candles, buys, sells);
    if (markerCount) {
      var legend = document.createElement("p");
      legend.className = "consensus-kline-marker-note";
      legend.textContent =
        "🔼 主動 ETF 加碼 " + buys.length + " 天　🔽 減碼 " + sells.length +
        " 天　下方為累積買超張數（加碼減去減碼，紅色為淨買超、綠色為淨賣超）" +
        "；僅涵蓋共識統計起算後的交易日";
      body.appendChild(legend);
    }
    renderMoveList(body, buys, sells);
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

  /*
   * 兩個彈窗互相導航：這裡列出「哪些 ETF 動了這檔股票」，個別 ETF 的操作紀錄
   * 則有完整成本與進出。彼此用 window 上的小介面呼叫，任一支腳本沒載入時
   * 另一支只是少一個按鈕，不會壞。
   */
  window.popostockConsensusStock = {
    open: function (code, name) {
      openStock(String(code), name || stockNames.get(String(code)) || String(code), null);
    },
    has: function (code) {
      return stockNames.has(String(code));
    },
  };

  /*
   * 從共識明細跳到「某檔 ETF 對這檔股票」的操作紀錄。股票代號與名稱從對話框
   * 標題取回（開窗時就是這樣寫進去的），免得再存一份會走味的狀態。
   */
  function openEtfRecord(row) {
    var api = window.popostockPositionRecord;
    if (!api || typeof api.open !== "function") return;
    var title = document.querySelector(".consensus-kline-title");
    var match = ((title && title.textContent) || "").match(/^(.*)（(\d{4})）$/);
    if (!match) return;
    closeModal();
    api.open(row.dataset.etf, row.dataset.etfName || row.dataset.etf, match[2], match[1]);
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
    Promise.all([loadStockIndex(), loadUsHoldingIndex()])
      .then(function (results) {
        results[0].forEach(function (stock) {
          var code = String(stock.code || stock.symbol || "");
          if (/^\d{4}$/.test(code)) {
            stockNames.set(code, String(stock.name || code));
            stockBuySessions.set(
              code,
              Array.isArray(stock.buySessions) ? stock.buySessions : [],
            );
            stockSellSessions.set(
              code,
              Array.isArray(stock.sellSessions) ? stock.sellSessions : [],
            );
          }
        });
        /*
         * 主動式 ETF 持有的美股。這批沒有加減碼標記——holding-changes 裡外國
         * 持股的 closePrice 是 null，推不出可信的張數與金額，硬標會是假的。
         * 先給得出 K 線，標記等價格來源補上再說。
         */
        results[1].forEach(function (stock) {
          var code = String(stock.code || "");
          if (!code || stockNames.has(code)) return;
          stockNames.set(code, String(stock.name || code));
          stockBuySessions.set(code, []);
          stockSellSessions.set(code, []);
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
      // 明細表裡點某一檔 ETF → 轉去看它對這檔股票的完整操作紀錄與成本。
      var row = event.target.closest
        ? event.target.closest(".consensus-kline-moves tr.is-link")
        : null;
      if (row) {
        openEtfRecord(row);
        return;
      }
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
      var row = event.target.closest
        ? event.target.closest(".consensus-kline-moves tr.is-link")
        : null;
      if (row && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        openEtfRecord(row);
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
