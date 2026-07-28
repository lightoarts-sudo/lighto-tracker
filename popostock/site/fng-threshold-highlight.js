/*
 * Fear-threshold highlights for the 美股大盤 charts.
 *
 * Two independent signals shade the same charts:
 *   - CNN Fear & Greed at or BELOW its threshold (low reading = fear)
 *   - CBOE VIX at or ABOVE its threshold (high reading = fear)
 *
 * Each signal owns its own overlay layer per chart. The band colour is
 * translucent, so a session both signals flag composites into a deeper red
 * without any special-casing.
 *
 * The candlestick charts belong to the React bundle, so the bundle patch calls
 * window.__popostockFngHighlight.attach(container, chart, points) for each one
 * and this script owns everything else.
 */
(function () {
  "use strict";

  // Every 美股大盤 panel, including the two index charts; TAIEX keeps its
  // separate volatility highlight and must not be picked up here.
  var INSTRUMENTS = /^(SPY|QQQ|SMH|CNN-FNG|VIX)\b/;

  var SIGNALS = [
    {
      key: "fng",
      dataUrl: "data/market/CNN-FNG.json",
      controlAttribute: "data-fng-threshold",
      inputId: "fng-threshold",
      label: "恐懼貪婪指數閥值",
      toggleLabel: "顯示紅色區塊",
      summarySuffix: " 個交易日不高於閥值",
      readingKey: "fngValue",
      // Fear is a LOW Fear & Greed reading.
      meets: function (value, threshold) {
        return value <= threshold;
      },
      threshold: 20,
      min: 0,
      max: 100,
      step: 1,
      show: true,
      readings: null,
    },
    {
      key: "vix",
      dataUrl: "data/market/VIX.json",
      controlAttribute: "data-vix-threshold",
      inputId: "vix-threshold",
      label: "VIX 閥值",
      toggleLabel: "顯示紅色區塊",
      summarySuffix: " 個交易日不低於閥值",
      readingKey: "close",
      // Fear is a HIGH VIX reading, so the comparison is inverted.
      meets: function (value, threshold) {
        return value >= threshold;
      },
      threshold: 30,
      min: 10,
      max: 90,
      step: 1,
      show: true,
      readings: null,
    },
  ];

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
   * any session inside that bar's span meets the threshold. Bar spans come from
   * the chart's own points, which keeps every interval correct.
   */
  function highlightedTimes(signal, points) {
    var flagged = new Set();
    var readings = signal.readings;
    if (!readings || !points.length) return flagged;

    var index = 0;
    for (var i = 0; i < points.length; i++) {
      var from = points[i].time;
      var to = i + 1 < points.length ? points[i + 1].time : null;
      while (index < readings.length && readings[index].time < from) index++;
      for (var j = index; j < readings.length; j++) {
        if (readings[j].time < from) continue;
        if (to !== null && readings[j].time >= to) break;
        if (signal.meets(readings[j].value, signal.threshold)) {
          flagged.add(from);
          break;
        }
      }
    }
    return flagged;
  }

  function countFlagged(signal) {
    if (!signal.readings) return 0;
    return signal.readings.filter(function (reading) {
      return signal.meets(reading.value, signal.threshold);
    }).length;
  }

  function createOverlay(container, chart, points) {
    // One layer per signal. They stack, so a session both signals flag shows
    // two translucent bands over each other and reads as a deeper red.
    var layers = SIGNALS.map(function (signal) {
      var layer = document.createElement("div");
      layer.className = "threshold-highlight-layer";
      layer.dataset.fngLayer = "1";
      layer.dataset.signal = signal.key;
      layer.setAttribute("aria-hidden", "true");
      container.appendChild(layer);
      return { signal: signal, node: layer };
    });

    var frame = 0;
    var render = function () {
      window.cancelAnimationFrame(frame);

      // Clear hidden signals synchronously: unchecking a toggle should take
      // effect at once rather than waiting for the next animation frame.
      var visible = layers.filter(function (entry) {
        if (entry.signal.show) return true;
        entry.node.replaceChildren();
        return false;
      });
      if (!visible.length) return;

      frame = window.requestAnimationFrame(function () {
        var placed = points.flatMap(function (point) {
          var x = chart.timeScale().timeToCoordinate(point.time);
          return x === null ? [] : [{ point: point, x: Number(x) }];
        });
        visible.forEach(function (entry) {
          var flagged = highlightedTimes(entry.signal, points);
          var fragment = document.createDocumentFragment();
          placed.forEach(function (placedPoint, i) {
            if (!flagged.has(placedPoint.point.time)) return;
            var previous = placed[i - 1] ? placed[i - 1].x : undefined;
            var next = placed[i + 1] ? placed[i + 1].x : undefined;
            var leftSpan =
              previous === undefined
                ? next === undefined
                  ? 8
                  : next - placedPoint.x
                : placedPoint.x - previous;
            var rightSpan =
              next === undefined ? leftSpan : next - placedPoint.x;
            var left = placedPoint.x - leftSpan / 2;
            var right = placedPoint.x + rightSpan / 2;
            if (right < 0 || left > container.clientWidth) return;
            var band = document.createElement("span");
            band.dataset.thresholdDate = placedPoint.point.time;
            band.style.left = left + "px";
            band.style.width = Math.max(1, right - left) + "px";
            fragment.appendChild(band);
          });
          entry.node.replaceChildren(fragment);
        });
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
      layers.forEach(function (entry) {
        entry.node.remove();
      });
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

  function buildControl(host, signal) {
    host.innerHTML = "";
    var wrapper = document.createElement("div");
    wrapper.className = "volatility-threshold-control";

    var label = document.createElement("label");
    label.htmlFor = signal.inputId;
    var labelText = document.createElement("span");
    labelText.textContent = signal.label;
    var labelValue = document.createElement("strong");
    label.appendChild(labelText);
    label.appendChild(labelValue);

    var slider = document.createElement("input");
    slider.type = "range";
    slider.id = signal.inputId;
    slider.min = String(signal.min);
    slider.max = String(signal.max);
    slider.step = String(signal.step);
    slider.value = String(signal.threshold);
    slider.setAttribute("aria-label", "調整" + signal.label);

    var summary = document.createElement("span");

    var toggleLabel = document.createElement("label");
    toggleLabel.style.cssText =
      "display:inline-flex;align-items:center;gap:6px;white-space:nowrap;cursor:pointer;";
    var toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = signal.show;
    toggle.style.cssText = "cursor:pointer;";
    toggle.setAttribute("aria-label", "顯示或隱藏" + signal.label + "紅色區塊");
    var toggleText = document.createElement("span");
    toggleText.textContent = signal.toggleLabel;
    toggleLabel.appendChild(toggle);
    toggleLabel.appendChild(toggleText);

    var sync = function () {
      labelValue.textContent = String(signal.threshold);
      slider.value = String(signal.threshold);
      slider.disabled = !signal.show;
      toggle.checked = signal.show;
      summary.textContent =
        countFlagged(signal).toLocaleString("zh-TW") + signal.summarySuffix;
    };

    var onChange = function (event) {
      var next = Number(event.currentTarget.value);
      if (Number.isNaN(next) || next === signal.threshold) return;
      signal.threshold = next;
      renderAll();
    };
    slider.addEventListener("input", onChange);
    slider.addEventListener("change", onChange);

    toggle.addEventListener("change", function (event) {
      signal.show = !!event.currentTarget.checked;
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
    SIGNALS.forEach(function (signal) {
      scope
        .querySelectorAll("[" + signal.controlAttribute + "]")
        .forEach(function (host) {
          if (host.dataset.thresholdControlReady === "1") return;
          host.dataset.thresholdControlReady = "1";
          buildControl(host, signal);
        });
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

  SIGNALS.forEach(function (signal) {
    fetch(getBaseUrl() + "/" + signal.dataUrl)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        signal.readings = (data && data.values ? data.values : [])
          .filter(function (point) {
            return (
              point &&
              point.time &&
              typeof point[signal.readingKey] === "number"
            );
          })
          .map(function (point) {
            return { time: point.time, value: point[signal.readingKey] };
          })
          .sort(function (a, b) {
            return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
          });
        renderAll();
      })
      .catch(function () {
        // An unavailable feed must not hide the other signal's bands.
        signal.readings = [];
        renderAll();
      });
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
