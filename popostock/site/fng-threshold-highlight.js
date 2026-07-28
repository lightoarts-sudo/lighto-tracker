/*
 * CNN Fear & Greed threshold highlights for the 美股大盤 charts.
 *
 * Mirrors the TAIEX/VIX volatility-threshold feature: sessions whose Fear &
 * Greed reading sits at or below the threshold are shaded red across the SPY,
 * QQQ and SMH candlestick charts.
 *
 * The candlestick charts belong to the React bundle, so the bundle patch calls
 * window.__popostockFngHighlight.attach(container, chart, points) for each one
 * and this script owns everything else.
 */
(function () {
  "use strict";

  var DATA_URL = "data/market/CNN-FNG.json";
  var DEFAULT_THRESHOLD = 20;
  var MIN_THRESHOLD = 0;
  var MAX_THRESHOLD = 100;
  // Every 美股大盤 panel, including the index's own chart; TAIEX keeps its
  // separate volatility highlight and must not be picked up here.
  var INSTRUMENTS = /^(SPY|QQQ|SMH|CNN-FNG)\b/;

  var threshold = DEFAULT_THRESHOLD;
  var showHighlights = true;
  var readings = null; // sorted ascending [{time, value}]
  var overlays = [];
  var controls = [];
  var syncingRange = false;

  function getBaseUrl() {
    var match = window.location.href.match(/^(https?:\/\/[^\/]+\/popostock)/);
    return match ? match[1] : "";
  }

  /*
   * Each chart sits in its own "<name>歷史市場 K 線圖" section, nested inside the
   * instrument section labelled "SPY SPDR S&P 500 ETF Trust". Walk the whole
   * ancestor chain rather than stopping at the nearest section.
   */
  function isUsMarketChart(container) {
    for (var node = container; node; node = node.parentElement) {
      if (node.tagName === "SECTION") {
        if (INSTRUMENTS.test(node.getAttribute("aria-label") || "")) return true;
      }
    }
    return false;
  }

  /*
   * The charts may be aggregated by day, week or month, so a bar is shaded when
   * any Fear & Greed session inside that bar's span meets the threshold. Bar
   * spans come from the chart's own points, which keeps every interval correct.
   */
  function highlightedTimes(points) {
    var flagged = new Set();
    if (!readings || !points.length) return flagged;

    var index = 0;
    for (var i = 0; i < points.length; i++) {
      var from = points[i].time;
      var to = i + 1 < points.length ? points[i + 1].time : null;
      while (index < readings.length && readings[index].time < from) index++;
      for (var j = index; j < readings.length; j++) {
        if (readings[j].time < from) continue;
        if (to !== null && readings[j].time >= to) break;
        if (readings[j].value <= threshold) {
          flagged.add(from);
          break;
        }
      }
    }
    return flagged;
  }

  function createOverlay(container, chart, points) {
    var layer = document.createElement("div");
    layer.className = "threshold-highlight-layer";
    layer.dataset.fngLayer = "1";
    layer.setAttribute("aria-hidden", "true");
    container.appendChild(layer);

    var frame = 0;
    var render = function () {
      window.cancelAnimationFrame(frame);
      if (!showHighlights) {
        layer.replaceChildren();
        return;
      }
      frame = window.requestAnimationFrame(function () {
        var flagged = highlightedTimes(points);
        var placed = points.flatMap(function (point) {
          var x = chart.timeScale().timeToCoordinate(point.time);
          return x === null ? [] : [{ point: point, x: Number(x) }];
        });
        var fragment = document.createDocumentFragment();
        placed.forEach(function (entry, i) {
          if (!flagged.has(entry.point.time)) return;
          var previous = placed[i - 1] ? placed[i - 1].x : undefined;
          var next = placed[i + 1] ? placed[i + 1].x : undefined;
          var leftSpan =
            previous === undefined
              ? next === undefined
                ? 8
                : next - entry.x
              : entry.x - previous;
          var rightSpan = next === undefined ? leftSpan : next - entry.x;
          var left = entry.x - leftSpan / 2;
          var right = entry.x + rightSpan / 2;
          if (right < 0 || left > container.clientWidth) return;
          var band = document.createElement("span");
          band.dataset.thresholdDate = entry.point.time;
          band.style.left = left + "px";
          band.style.width = Math.max(1, right - left) + "px";
          fragment.appendChild(band);
        });
        layer.replaceChildren(fragment);
      });
    };

    var onRangeChange = function (range) {
      render();
      // Dragging or zooming any 美股大盤 chart moves the rest with it.
      if (range) shareRange(overlay, range);
    };

    chart.timeScale().subscribeVisibleTimeRangeChange(onRangeChange);
    var observer = new ResizeObserver(render);
    observer.observe(container);

    var destroy = function () {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      // The bundle removes the chart on interval changes, which already drops
      // its subscriptions; guard so a late teardown cannot throw.
      try {
        chart.timeScale().unsubscribeVisibleTimeRangeChange(onRangeChange);
      } catch (error) {
        /* chart already disposed */
      }
      layer.remove();
    };

    var overlay = {
      render: render,
      destroy: destroy,
      container: container,
      chart: chart,
    };
    return overlay;
  }

  function visibleRange(overlay) {
    try {
      return overlay.chart.timeScale().getVisibleRange();
    } catch (error) {
      return null;
    }
  }

  function applyRange(overlay, range) {
    try {
      overlay.chart.timeScale().setVisibleRange(range);
    } catch (error) {
      // Ranges outside a chart's own data are rejected; leave that chart put.
    }
  }

  /*
   * lightweight-charts fires the same event for programmatic changes, so a
   * naive propagation would ping-pong between charts. One flag keeps a user
   * gesture to a single pass over the peers.
   */
  function shareRange(source, range) {
    if (syncingRange) return;
    syncingRange = true;
    try {
      overlays.forEach(function (peer) {
        if (peer === source || !peer.container.isConnected) return;
        applyRange(peer, range);
        peer.render();
      });
    } finally {
      syncingRange = false;
    }
  }

  function countFlagged() {
    if (!readings) return 0;
    return readings.filter(function (r) {
      return r.value <= threshold;
    }).length;
  }

  function dropOverlays(match) {
    overlays = overlays.filter(function (overlay) {
      if (!match(overlay)) return true;
      overlay.destroy();
      return false;
    });
  }

  function renderAll() {
    dropOverlays(function (overlay) {
      return !overlay.container.isConnected;
    });
    overlays.forEach(function (overlay) {
      overlay.render();
    });
    controls.forEach(function (control) {
      control.sync();
    });
  }

  function buildControl(host) {
    host.innerHTML = "";
    var wrapper = document.createElement("div");
    wrapper.className = "volatility-threshold-control";

    var label = document.createElement("label");
    label.htmlFor = "fng-threshold";
    var labelText = document.createElement("span");
    labelText.textContent = "恐懼貪婪指數閥值";
    var labelValue = document.createElement("strong");
    label.appendChild(labelText);
    label.appendChild(labelValue);

    var slider = document.createElement("input");
    slider.type = "range";
    slider.id = "fng-threshold";
    slider.min = String(MIN_THRESHOLD);
    slider.max = String(MAX_THRESHOLD);
    slider.step = "1";
    slider.value = String(threshold);
    slider.setAttribute("aria-label", "調整恐懼貪婪指數閥值");

    var summary = document.createElement("span");

    var toggleLabel = document.createElement("label");
    toggleLabel.style.cssText =
      "display:inline-flex;align-items:center;gap:6px;white-space:nowrap;cursor:pointer;";
    var toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = showHighlights;
    toggle.style.cssText = "cursor:pointer;";
    toggle.setAttribute("aria-label", "顯示或隱藏閥值紅色區塊");
    var toggleText = document.createElement("span");
    toggleText.textContent = "顯示紅色區塊";
    toggleLabel.appendChild(toggle);
    toggleLabel.appendChild(toggleText);

    var sync = function () {
      labelValue.textContent = String(threshold);
      slider.value = String(threshold);
      slider.disabled = !showHighlights;
      toggle.checked = showHighlights;
      summary.textContent =
        countFlagged().toLocaleString("zh-TW") + " 個交易日不高於閥值";
    };

    var onChange = function (event) {
      var next = Number(event.currentTarget.value);
      if (Number.isNaN(next) || next === threshold) return;
      threshold = next;
      renderAll();
    };
    slider.addEventListener("input", onChange);
    slider.addEventListener("change", onChange);

    toggle.addEventListener("change", function (event) {
      showHighlights = !!event.currentTarget.checked;
      renderAll();
    });

    // The shared stylesheet lays this control out as three columns; the
    // toggle adds a fourth.
    wrapper.style.gridTemplateColumns = "auto minmax(180px,1fr) auto auto";
    wrapper.appendChild(label);
    wrapper.appendChild(slider);
    wrapper.appendChild(summary);
    wrapper.appendChild(toggleLabel);
    host.appendChild(wrapper);

    controls.push({ sync: sync });
    sync();
  }

  function scanControls(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-fng-threshold]").forEach(function (host) {
      if (host.dataset.fngThresholdReady === "1") return;
      host.dataset.fngThresholdReady = "1";
      buildControl(host);
    });
  }

  window.__popostockFngHighlight = {
    attach: function (container, chart, points) {
      try {
        if (!container || !chart || !points || !points.length) return;
        if (!isUsMarketChart(container)) return;
        // Switching 日K/週K/月K rebuilds the chart in the same container, so
        // retire the previous overlay instead of stacking a second one.
        dropOverlays(function (overlay) {
          return overlay.container === container;
        });

        // Adopt whatever window the panels already show, so a chart that
        // mounts late (the index fetches its own data) lines up instead of
        // sitting on its full history.
        var peerRange = null;
        for (var i = 0; i < overlays.length; i++) {
          if (!overlays[i].container.isConnected) continue;
          peerRange = visibleRange(overlays[i]);
          if (peerRange) break;
        }

        var overlay = createOverlay(container, chart, points);
        overlays.push(overlay);
        if (peerRange) {
          syncingRange = true;
          try {
            applyRange(overlay, peerRange);
          } finally {
            syncingRange = false;
          }
        }
        renderAll();
      } catch (error) {
        // A highlight failure must never take the chart itself down.
      }
    },
  };

  fetch(getBaseUrl() + "/" + DATA_URL)
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(function (data) {
      readings = (data && data.values ? data.values : [])
        .filter(function (point) {
          return point && point.time && typeof point.fngValue === "number";
        })
        .map(function (point) {
          return { time: point.time, value: point.fngValue };
        })
        .sort(function (a, b) {
          return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
        });
      renderAll();
    })
    .catch(function () {
      readings = [];
    });

  function watch() {
    scanControls(document);
    new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var added = mutations[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          if (added[j].nodeType === 1) scanControls(added[j]);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
