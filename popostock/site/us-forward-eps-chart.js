/*
 * S&P 500 指數 vs 未來 12 個月預估 EPS（美股大盤）。
 *
 * 雙軸圖最常見的毛病是兩個刻度各自 autoscale，交叉點只是排版巧合。這裡把
 * 右軸（EPS）用一個「錨定本益比」綁在左軸（指數）上：
 *
 *     右軸範圍 = 左軸範圍 ÷ ANCHOR_PE（區間平均 forward P/E）
 *
 * 於是兩條線的垂直距離就是「當時本益比與區間平均的落差」——高於平均時
 * 指數線在 EPS 線之上，低於平均時在下。這樣的雙軸有明確定義，不是把兩條
 * 線硬湊在一起。錨定值會標在圖例上。
 *
 * 指數為每日、預估 EPS 為每週（FactSet 週五出刊），刻意不補內插值。
 */
(function () {
  "use strict";

  var ATTRIBUTE = "data-forward-eps-chart";
  var LIBRARY_FILE = "lightweight-charts.standalone.production.js";

  var THEME = {
    background: "#ffffff",
    text: "#667483",
    grid: "#edf1f4",
    border: "#d6dee6",
    fontFamily: 'var(--font-geist-sans), "Noto Sans TC", Arial, sans-serif',
  };

  // 與參考圖一致：指數用淺藍、EPS 用深藍。兩者亮度差夠大，
  // 列印或色覺障礙下仍可分辨，圖例也各自直接標色塊。
  var INDEX_COLOR = "#3fa9c9";
  var EPS_COLOR = "#1b2f7a";

  var libraryPromise = null;

  function loadLibrary() {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    if (libraryPromise) return libraryPromise;
    libraryPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = LIBRARY_FILE;
      script.onload = function () {
        window.LightweightCharts
          ? resolve(window.LightweightCharts)
          : reject(new Error("lightweight-charts 載入後找不到全域物件"));
      };
      script.onerror = function () {
        reject(new Error("lightweight-charts 載入失敗"));
      };
      document.head.appendChild(script);
    });
    return libraryPromise;
  }

  function fmt(value, digits) {
    return Number(value).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function readingBar(index, eps) {
    var bar = document.createElement("div");
    bar.className = "forward-eps-reading";
    // 指數是每日、預估 EPS 是每週，最新的兩個點通常不同天。這裡同時給出
    // FactSet 當期自述的 P/E（與 EPS 同一天，可回溯到來源），以及用最新收盤
    // 重算的 P/E（每天會動）。只標一個「forward P/E」會讓讀者拿去跟 FactSet
    // 的數字對照時對不上。
    var live = eps ? index[1] / eps[1] : null;
    bar.innerHTML =
      '<span class="fe-item"><b>' + fmt(index[1], 2) + "</b><i>S&P 500 收盤（" + index[0] + "）</i></span>" +
      (eps
        ? '<span class="fe-item"><b>$' + fmt(eps[1], 2) + "</b><i>未來 12 個月預估 EPS（" + eps[0] + "）</i></span>" +
          '<span class="fe-item"><b>' + fmt(eps[2], 1) + "</b><i>FactSet forward P/E（" + eps[0] + "）</i></span>" +
          '<span class="fe-item"><b>' + fmt(live, 1) + "</b><i>以 " + index[0] + " 收盤重算</i></span>"
        : "");
    return bar;
  }

  function legend(anchorPe) {
    var box = document.createElement("div");
    box.className = "forward-eps-legend";
    box.innerHTML =
      '<span><i style="background:' + INDEX_COLOR + '"></i>S&P 500 指數（左軸）</span>' +
      '<span><i style="background:' + EPS_COLOR + '"></i>未來 12 個月預估 EPS（右軸，美元）</span>' +
      '<span class="fe-note">右軸以區間平均 forward P/E ' + fmt(anchorPe, 1) +
      " 對齊左軸；兩線距離即為當時本益比與此平均的落差</span>";
    return box;
  }

  function installStyles() {
    if (document.getElementById("forward-eps-styles")) return;
    var style = document.createElement("style");
    style.id = "forward-eps-styles";
    style.textContent =
      ".forward-eps-reading{display:flex;flex-wrap:wrap;gap:10px 26px;margin:2px 0 12px}" +
      ".forward-eps-reading .fe-item{display:flex;flex-direction:column;gap:1px}" +
      ".forward-eps-reading b{font-size:22px;font-weight:900;color:#06275f;" +
      "font-variant-numeric:tabular-nums;line-height:1.15}" +
      ".forward-eps-reading i{font-style:normal;font-size:11.5px;font-weight:700;color:#8b98ab}" +
      ".forward-eps-legend{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center;" +
      "margin-top:10px;font-size:12px;font-weight:700;color:#667483}" +
      ".forward-eps-legend i{display:inline-block;width:11px;height:11px;border-radius:3px;" +
      "margin-right:6px;vertical-align:-1px}" +
      ".forward-eps-legend .fe-note{flex-basis:100%;font-weight:500;color:#8b98ab;line-height:1.5}" +
      ".forward-eps-error{color:#8a4b2a;font-size:13px;font-weight:700;padding:10px 0}";
    document.head.appendChild(style);
  }

  function render(container, data, lc) {
    var index = (data.index || []).filter(function (p) {
      return p && p[1];
    });
    var eps = (data.forwardEps || []).filter(function (p) {
      return p && p[1];
    });
    if (index.length < 2) throw new Error("指數資料不足");

    // 只畫有預估 EPS 的區間，否則左半段會是一條孤零零的指數線。
    var from = eps.length ? eps[0][0] : index[0][0];
    index = index.filter(function (p) {
      return p[0] >= from;
    });

    var pes = eps.map(function (p) {
      return p[2];
    });
    var anchorPe =
      pes.length
        ? pes.reduce(function (a, b) {
            return a + b;
          }, 0) / pes.length
        : 20;

    installStyles();
    container.innerHTML = "";
    container.appendChild(readingBar(index[index.length - 1], eps[eps.length - 1]));
    var chartDiv = document.createElement("div");
    chartDiv.style.minHeight = "300px";
    container.appendChild(chartDiv);
    container.appendChild(legend(anchorPe));

    var chart = lc.createChart(chartDiv, {
      layout: {
        background: { type: lc.ColorType.Solid, color: THEME.background },
        textColor: THEME.text,
        fontFamily: THEME.fontFamily,
        fontSize: 12,
      },
      width: chartDiv.clientWidth,
      height: 300,
      crosshairMode: lc.CrosshairMode.Normal,
      grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
      leftPriceScale: { visible: true, borderColor: THEME.border },
      rightPriceScale: { visible: true, borderColor: THEME.border },
      timeScale: { borderColor: THEME.border, timeVisible: false, rightOffset: 2 },
    });

    // 兩個刻度都鎖成固定範圍，右軸恰為左軸 ÷ anchorPe，
    // 交叉點才有意義；交給 autoscale 會讓兩軸各自伸縮。
    var lo = Math.min.apply(null, index.map(function (p) { return p[1]; }));
    var hi = Math.max.apply(null, index.map(function (p) { return p[1]; }));
    var pad = (hi - lo) * 0.08 || 1;
    var indexRange = { minValue: lo - pad, maxValue: hi + pad };
    var epsRange = {
      minValue: indexRange.minValue / anchorPe,
      maxValue: indexRange.maxValue / anchorPe,
    };

    var indexSeries = chart.addSeries(lc.LineSeries, {
      color: INDEX_COLOR,
      lineWidth: 2,
      priceScaleId: "left",
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: function () {
        return { priceRange: indexRange };
      },
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    indexSeries.setData(
      index.map(function (p) {
        return { time: p[0], value: p[1] };
      })
    );

    var epsSeries = chart.addSeries(lc.LineSeries, {
      color: EPS_COLOR,
      lineWidth: 2,
      priceScaleId: "right",
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: function () {
        return { priceRange: epsRange };
      },
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    epsSeries.setData(
      eps.map(function (p) {
        return { time: p[0], value: p[1] };
      })
    );

    chart.timeScale().fitContent();

    // 面板常在分頁尚未版面配置時就掛載，寬度會是 0；跟著實際寬度走，
    // 不用計時器猜。
    var lastWidth = 0;
    var applyWidth = function () {
      var width = chartDiv.clientWidth;
      if (width > 0 && width !== lastWidth) {
        lastWidth = width;
        chart.applyOptions({ width: width });
        chart.timeScale().fitContent();
      }
    };
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(applyWidth).observe(chartDiv);
    } else {
      window.addEventListener("resize", applyWidth);
      setTimeout(applyWidth, 200);
      setTimeout(applyWidth, 1000);
    }
    applyWidth();
  }

  function mount(container) {
    if (container.dataset.forwardEpsReady === "1") return;
    container.dataset.forwardEpsReady = "1";
    var url = container.getAttribute(ATTRIBUTE);
    Promise.all([
      fetch(url, { cache: "no-store" }).then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      }),
      loadLibrary(),
    ])
      .then(function (results) {
        render(container, results[0], results[1]);
      })
      .catch(function (error) {
        container.dataset.forwardEpsReady = "";
        container.innerHTML =
          '<p class="forward-eps-error">預估 EPS 圖表載入失敗：' +
          (error && error.message ? error.message : error) +
          "</p>";
      });
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    Array.prototype.forEach.call(
      scope.querySelectorAll("[" + ATTRIBUTE + "]"),
      mount
    );
  }

  function watch() {
    scan(document);
    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        Array.prototype.forEach.call(mutation.addedNodes, function (node) {
          if (node.nodeType !== 1) return;
          if (node.hasAttribute && node.hasAttribute(ATTRIBUTE)) mount(node);
          scan(node);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
