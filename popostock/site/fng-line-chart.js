/*
 * CNN Fear & Greed Index - Line Chart
 * Standalone script: loads lightweight-charts from CDN and renders a line chart.
 * Triggered by elements with data-fng-chart attribute.
 */
(function () {
  "use strict";

  const CLASS_COLORS = {
    "\u6975\u5ea6\u512a\u614c": "#8B0000",
    "\u512a\u614c": "#CC4400",
    "\u4e2d\u6027": "#2E8B57",
    "\u8c50\u5be0": "#228B22",
    "\u6975\u5ea6\u8c50\u5be0": "#006400",
  };

  function fngColor(v) {
    if (v <= 25) return CLASS_COLORS["\u6975\u5ea6\u512a\u614c"];
    if (v <= 45) return CLASS_COLORS["\u512a\u614c"];
    if (v <= 55) return CLASS_COLORS["\u4e2d\u6027"];
    if (v <= 75) return CLASS_COLORS["\u8c50\u5be0"];
    return CLASS_COLORS["\u6975\u5ea6\u8c50\u5be0"];
  }

  function fngLabel(v) {
    if (v <= 25) return "\u6975\u5ea6\u512a\u614c";
    if (v <= 45) return "\u512a\u614c";
    if (v <= 55) return "\u4e2d\u6027";
    if (v <= 75) return "\u8c50\u5be0";
    return "\u6975\u5ea6\u8c50\u5be0";
  }

  function getBaseUrl() {
    // Determine base path from current location
    const href = window.location.href;
    const match = href.match(/^(https?:\/\/[^\/]+\/popostock)/);
    return match ? match[1] : "";
  }

  function initChart(container, dataUrl) {
    if (!container || !dataUrl) return;

    container.innerHTML = '<div class="empty-state"><p>\u8f09\u5165\u4e2d...</p></div>';

    fetch(dataUrl)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || !data.values || data.values.length === 0) {
          container.innerHTML = '<div class="empty-state"><p>\u8cc7\u8a0a\u4e3a\u7a7a</p></div>';
          return;
        }

        var values = data.values;
        var latest = values[0];

        // Reading bar
        var readingDiv = document.createElement("div");
        readingDiv.className = "fng-reading-bar";
        readingDiv.style.cssText =
          "display:flex;align-items:baseline;gap:10px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:10px;";

        var valueSpan = document.createElement("span");
        valueSpan.style.cssText =
          "font-size:28px;font-weight:700;color:" + fngColor(latest.fngValue);
        valueSpan.textContent = latest.fngValue.toFixed(0);

        var labelSpan = document.createElement("span");
        labelSpan.style.cssText =
          "font-size:16px;color:" + fngColor(latest.fngValue);
        labelSpan.textContent = fngLabel(latest.fngValue);

        var dateSpan = document.createElement("span");
        dateSpan.style.cssText = "font-size:13px;color:#6b7280;margin-left:auto;";
        dateSpan.textContent = latest.time;

        readingDiv.appendChild(valueSpan);
        readingDiv.appendChild(labelSpan);
        readingDiv.appendChild(dateSpan);

        // Chart container
        var chartDiv = document.createElement("div");
        chartDiv.style.cssText = "width:100%;height:220px;";

        // Legend
        var legendDiv = document.createElement("div");
        legendDiv.style.cssText =
          "display:flex;gap:14px;padding:8px 0;flex-wrap:wrap;";
        for (var i = 0; i < Object.keys(CLASS_COLORS).length; i++) {
          var label = Object.keys(CLASS_COLORS)[i];
          var color = CLASS_COLORS[label];
          var item = document.createElement("span");
          item.style.cssText =
            "display:flex;align-items:center;gap:4px;font-size:12px;color:#6b7280;";
          var dot = document.createElement("span");
          dot.style.cssText =
            "width:10px;height:10px;border-radius:2px;background:" + color;
          item.appendChild(dot);
          item.appendChild(document.createTextNode(label));
          legendDiv.appendChild(item);
        }

        // Load lightweight-charts from CDN
        var script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js";
        script.onload = function () {
          var lc = window.LightweightCharts;

          var chart = lc.createChart(chartDiv, {
            layout: {
              background: { type: lc.ColorType.Solid, color: "transparent" },
              textColor: "#6b7280",
            },
            width: chartDiv.clientWidth,
            height: 220,
            crosshairMode: lc.CrosshairMode.Normal,
            grid: {
              vertLines: { color: "rgba(255,255,255,0.06)" },
              horzLines: { color: "rgba(255,255,255,0.06)" },
            },
            rightPriceScale: {
              borderColor: "rgba(255,255,255,0.1)",
              scaleMargins: { top: 0.15, bottom: 0.15 },
            },
            timeScale: {
              borderColor: "rgba(255,255,255,0.1)",
              timeVisible: false,
              rightOffset: 2,
            },
          });

          var series = chart.addSeries(lc.LineSeries, {
            lineWidth: 2,
            crosshairMarkerRadius: 4,
            crosshairMarkerBackgroundColor: "#fff",
            priceLineVisible: false,
            lastValueVisible: false,
          });

          series.setData(
            values.map(function (p) {
              return {
                time: p.time,
                value: p.fngValue,
                color: fngColor(p.fngValue),
              };
            })
          );

          // Zone boundary lines
          [
            { v: 25, l: "\u6975\u5ea6\u512a\u614c/\u512a\u614c" },
            { v: 45, l: "\u512a\u614c/\u4e2d\u6027" },
            { v: 55, l: "\u4e2d\u6027/\u8c50\u5be0" },
            { v: 75, l: "\u8c50\u5be0/\u6975\u5ea6\u8c50\u5be0" },
          ].forEach(function (z) {
            series.createPriceLine({
              price: z.v,
              color: "rgba(255,255,255,0.15)",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: z.l,
            });
          });

          chart.timeScale().fitContent();

          var resize = function () {
            if (chartDiv.clientWidth > 0) {
              chart.applyOptions({ width: chartDiv.clientWidth });
            }
          };
          window.addEventListener("resize", resize);
          setTimeout(resize, 200);
          setTimeout(resize, 1000);

          container.innerHTML = "";
          container.appendChild(readingDiv);
          container.appendChild(chartDiv);
          container.appendChild(legendDiv);
        };

        script.onerror = function () {
          container.innerHTML =
            '<div class="empty-state"><p>\u5716\u8868\u52a0\u8f09\u5931\u6557</p></div>';
        };

        document.head.appendChild(script);
      })
      .catch(function () {
        container.innerHTML =
          '<div class="empty-state"><p>\u8cc7\u8a0a\u8f09\u5165\u5931\u6557</p></div>';
      });
  }

  // Auto-init on DOM ready
  function init() {
    document.querySelectorAll("[data-fng-chart]").forEach(function (el) {
      var url = el.getAttribute("data-fng-chart");
      initChart(el, url);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Expose for React to call
  window.__FngLineChart = function (container, url) {
    if (container && url) {
      initChart(container, url);
    }
  };
})();
