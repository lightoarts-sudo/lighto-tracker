/*
 * CNN Fear & Greed Index - Line Chart
 * Standalone script: renders a line chart into elements carrying a
 * data-fng-chart attribute. The production UI mounts those elements from
 * React after this script runs, so initialisation is observer-driven.
 */
(function () {
  "use strict";

  var LIBRARY_FILE = "lightweight-charts.standalone.production.js";

  // The panel sits on the site's white detail card, so these mirror the
  // palette the bundled candlestick charts already use. The previous
  // white-on-white values left the grid and zone lines invisible.
  var THEME = {
    background: "#ffffff",
    text: "#667483",
    grid: "#edf1f4",
    border: "#d6dee6",
    fontFamily: 'var(--font-geist-sans), "Noto Sans TC", Arial, sans-serif',
  };

  // The site's teal, matching the TAIEX panel this ratio chart sits under.
  var RATIO_LINE_COLOR = "#08756f";

  // Ordered from most fearful to most greedy; neutral stays amber so the
  // fear and greed ends of the scale never read as the same colour.
  var ZONES = [
    { limit: 25, label: "極度恐慌", color: "#8B0000" },
    { limit: 45, label: "恐慌", color: "#CC4400" },
    { limit: 55, label: "中性", color: "#C8991A" },
    { limit: 75, label: "貪婪", color: "#228B22" },
    { limit: Infinity, label: "極度貪婪", color: "#006400" },
  ];

  function zoneFor(value) {
    for (var i = 0; i < ZONES.length; i++) {
      if (value <= ZONES[i].limit) return ZONES[i];
    }
    return ZONES[ZONES.length - 1];
  }

  function fngColor(value) {
    return zoneFor(value).color;
  }

  function fngLabel(value) {
    return zoneFor(value).label;
  }

  function buildRatioReadingBar(latest) {
    var bar = document.createElement("div");
    bar.className = "fng-reading-bar";
    bar.style.cssText =
      "display:flex;align-items:baseline;gap:10px;padding:10px 0;" +
      "border-bottom:1px solid #e5eaf0;margin-bottom:10px;";

    var value = document.createElement("span");
    value.style.cssText =
      "font-size:28px;font-weight:700;color:" + RATIO_LINE_COLOR + ";";
    value.textContent = latest.value.toFixed(2) + "%";

    var note = document.createElement("span");
    note.style.cssText = "font-size:13px;color:" + THEME.text + ";";
    note.textContent = "推算值";

    var date = document.createElement("span");
    date.style.cssText = "font-size:13px;color:" + THEME.text + ";margin-left:auto;";
    date.textContent = latest.time;

    bar.appendChild(value);
    bar.appendChild(note);
    bar.appendChild(date);
    return bar;
  }

  var PROFILES = [
    {
      attribute: "data-fng-chart",
      valueKey: "fngValue",
      lineColor: undefined, // per-point zone colours win over this
      joinsThresholdGroup: true,
      readingBar: buildReadingBar,
      legend: buildLegend,
      point: function (point) {
        return {
          time: point.time,
          value: point.fngValue,
          color: fngColor(point.fngValue),
        };
      },
    },
    {
      attribute: "data-ratio-chart",
      valueKey: "value",
      lineColor: RATIO_LINE_COLOR,
      // The margin ratio belongs to 台股大盤; the threshold group is 美股大盤.
      joinsThresholdGroup: false,
      readingBar: buildRatioReadingBar,
      legend: null,
      point: function (point) {
        return { time: point.time, value: point.value };
      },
    },
  ];

  function getBaseUrl() {
    var match = window.location.href.match(/^(https?:\/\/[^\/]+\/popostock)/);
    return match ? match[1] : "";
  }

  var libraryPromise = null;

  function loadLibrary() {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    if (libraryPromise) return libraryPromise;

    libraryPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = getBaseUrl() + "/" + LIBRARY_FILE;
      script.onload = function () {
        if (window.LightweightCharts) resolve(window.LightweightCharts);
        else reject(new Error("LightweightCharts global missing"));
      };
      script.onerror = function () {
        reject(new Error("failed to load " + LIBRARY_FILE));
      };
      document.head.appendChild(script);
    });
    return libraryPromise;
  }

  function message(container, text) {
    container.innerHTML = "";
    var wrapper = document.createElement("div");
    wrapper.className = "empty-state";
    var paragraph = document.createElement("p");
    paragraph.textContent = text;
    wrapper.appendChild(paragraph);
    container.appendChild(wrapper);
  }

  function buildReadingBar(latest) {
    var bar = document.createElement("div");
    bar.className = "fng-reading-bar";
    bar.style.cssText =
      "display:flex;align-items:baseline;gap:10px;padding:10px 0;" +
      "border-bottom:1px solid #e5eaf0;margin-bottom:10px;";

    var value = document.createElement("span");
    value.style.cssText =
      "font-size:28px;font-weight:700;color:" + fngColor(latest.fngValue);
    value.textContent = latest.fngValue.toFixed(0);

    var label = document.createElement("span");
    label.style.cssText = "font-size:16px;color:" + fngColor(latest.fngValue);
    label.textContent = fngLabel(latest.fngValue);

    var date = document.createElement("span");
    date.style.cssText = "font-size:13px;color:" + THEME.text + ";margin-left:auto;";
    date.textContent = latest.time;

    bar.appendChild(value);
    bar.appendChild(label);
    bar.appendChild(date);
    return bar;
  }

  function buildLegend() {
    var legend = document.createElement("div");
    legend.style.cssText = "display:flex;gap:14px;padding:8px 0;flex-wrap:wrap;";
    ZONES.forEach(function (zone) {
      var item = document.createElement("span");
      item.style.cssText =
        "display:flex;align-items:center;gap:4px;font-size:12px;color:" + THEME.text + ";";
      var dot = document.createElement("span");
      dot.style.cssText =
        "width:10px;height:10px;border-radius:2px;background:" + zone.color;
      item.appendChild(dot);
      item.appendChild(document.createTextNode(zone.label));
      legend.appendChild(item);
    });
    return legend;
  }

  function renderChart(container, lc, values, profile) {
    var chartDiv = document.createElement("div");
    // position:relative anchors the absolutely positioned threshold overlay.
    chartDiv.style.cssText = "width:100%;height:220px;position:relative;";

    container.innerHTML = "";
    container.appendChild(profile.readingBar(values[values.length - 1]));
    container.appendChild(chartDiv);
    if (profile.legend) container.appendChild(profile.legend());

    var chart = lc.createChart(chartDiv, {
      layout: {
        background: { type: lc.ColorType.Solid, color: THEME.background },
        textColor: THEME.text,
        fontFamily: THEME.fontFamily,
        fontSize: 12,
      },
      width: chartDiv.clientWidth,
      height: 220,
      crosshairMode: lc.CrosshairMode.Normal,
      grid: {
        vertLines: { color: THEME.grid },
        horzLines: { color: THEME.grid },
      },
      rightPriceScale: {
        borderColor: THEME.border,
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: THEME.border,
        timeVisible: false,
        rightOffset: 2,
      },
    });

    var series = chart.addSeries(lc.LineSeries, {
      color: profile.lineColor,
      lineWidth: 2,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: THEME.background,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    series.setData(values.map(profile.point));

    // The zone boundaries are stated in the panel description instead of drawn
    // on the chart, which kept four dashed lines and their 25/45/55/75 axis
    // labels competing with the series itself.

    chart.timeScale().fitContent();

    // React mounts this panel before the tab has been laid out, so the chart
    // is often created at zero width. Track the real width instead of
    // guessing with timers, which left the canvas stuck at its default size.
    var lastWidth = 0;
    var synced = false;
    var applyWidth = function () {
      var width = chartDiv.clientWidth;
      if (width > 0 && width !== lastWidth) {
        lastWidth = width;
        chart.applyOptions({ width: width });
        // Once the panels share a window, refitting would fight the sync.
        if (!synced) chart.timeScale().fitContent();
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

    // Join the 美股大盤 group: this chart then shares the candlesticks' date
    // range and carries the same below-threshold shading.
    var highlight = window.__popostockFngHighlight;
    if (profile.joinsThresholdGroup && highlight &&
        typeof highlight.attach === "function") {
      synced = true;
      highlight.attach(chartDiv, chart, values);
    }
  }

  function initChart(container, dataUrl, profile) {
    if (!container || !dataUrl) return;
    // React can re-mount the panel; only ever build one chart per element.
    if (container.dataset.fngChartReady === "1") return;
    container.dataset.fngChartReady = "1";

    message(container, "載入中…");

    Promise.all([
      fetch(dataUrl).then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      }),
      loadLibrary(),
    ])
      .then(function (results) {
        var data = results[0];
        var lc = results[1];
        var values = (data && data.values ? data.values : []).filter(function (point) {
          return point && point.time && typeof point[profile.valueKey] === "number";
        });
        if (!values.length) {
          message(container, "資訊為空");
          return;
        }
        // The feed is published newest-first; the chart requires ascending time.
        values.sort(function (a, b) {
          return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
        });
        renderChart(container, lc, values, profile);
      })
      .catch(function () {
        container.dataset.fngChartReady = "";
        message(container, "資訊載入失敗");
      });
  }

  function scan(root) {
    var scope = root && root.querySelectorAll ? root : document;
    PROFILES.forEach(function (profile) {
      scope
        .querySelectorAll("[" + profile.attribute + "]")
        .forEach(function (element) {
          initChart(element, element.getAttribute(profile.attribute), profile);
        });
    });
  }

  function watch() {
    scan(document);
    // The US market panel is mounted by React after this script executes,
    // so keep watching for the placeholder to appear.
    new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var added = mutations[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var node = added[j];
          if (node.nodeType !== 1) continue;
          PROFILES.forEach(function (profile) {
            if (node.hasAttribute && node.hasAttribute(profile.attribute)) {
              initChart(node, node.getAttribute(profile.attribute), profile);
            }
          });
          scan(node);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }

  // Expose for React to call
  window.__FngLineChart = function (container, url) {
    if (container && url) {
      initChart(container, url);
    }
  };
})();
