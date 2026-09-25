/*
 * PoPoStock 績效排行 custom date range.
 *
 * The release table shows all eight preset periods side by side and sorts by
 * whichever column header you click (see
 * scripts/patch-popostock-performance-matrix.mjs). This adds a date pair next
 * to the 全部／基金／… scope switch and, once applied, rewrites the ranking
 * table and summary in place with one extra column — 自訂區間 — placed first
 * among the return columns, so it reads as the same table rather than a second
 * one.
 *
 * While the custom column is showing, every column is still sortable: this
 * copy owns its own sort state and re-renders itself, so clicking 1 年 sorts
 * by 1 年 without dropping the custom column. Only 清除自訂區間 removes it.
 *
 * The return uses the same rule as the published ranking: the last official
 * value on or before each endpoint, taken from data/performance-series.json
 * (one request covering every instrument). No interpolation, and an instrument
 * without data at either endpoint is excluded and counted, never silently
 * shifted to a nearby date. The eight preset columns are copied from
 * data/performance-ranking.json so they stay identical to the table this one
 * replaces.
 *
 * Rewriting React's own DOM is deliberate here: anything that makes React
 * re-render restores its table, which is exactly the "go back" behaviour we
 * want. A banner marks the table as overridden so the state is never ambiguous.
 */
(function () {
  "use strict";

  var SERIES_FILE = "data/performance-series.json";
  var RANKING_FILE = "data/performance-ranking.json";
  var PANEL_ID = "performance-custom-range";
  var CONTROL_ID = "performance-custom-range-control";
  var BANNER_ID = "performance-custom-range-banner";
  var CUSTOM_KEY = "__custom";
  var seriesPromise = null;
  var rankingPromise = null;
  var activeRange = null;
  var sortKey = CUSTOM_KEY;
  var sortDescending = true;

  function baseUrl() {
    var base = document.querySelector("base[href]");
    if (base) return new URL(base.getAttribute("href"), window.location.href).href.replace(/\/$/, "");
    var match = window.location.href.match(/^(https?:\/\/[^/]+\/popostock)/);
    return match ? match[1] : "";
  }

  function loadJson(file) {
    return fetch(baseUrl() + "/" + file, { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  function loadSeries() {
    if (seriesPromise) return seriesPromise;
    seriesPromise = loadJson(SERIES_FILE).catch(function (error) {
      seriesPromise = null;
      throw error;
    });
    return seriesPromise;
  }

  /* The eight preset columns are already computed on the server; reusing them
     keeps every number identical to the table this one replaces. */
  function loadRanking() {
    if (rankingPromise) return rankingPromise;
    rankingPromise = loadJson(RANKING_FILE).catch(function (error) {
      rankingPromise = null;
      throw error;
    });
    return rankingPromise;
  }

  /* Last official value on or before the date; null when the series starts later. */
  function valueAsOf(values, date) {
    var low = 0;
    var high = values.length - 1;
    var found = null;
    while (low <= high) {
      var mid = (low + high) >> 1;
      if (values[mid][0] <= date) {
        found = values[mid];
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return found;
  }

  var GROUP_LABEL = {
    funds: "基金",
    activeEtfs: "主動式 ETF",
    passiveEtfs: "被動式 ETF",
  };

  var GROUP_CLASS = {
    基金: "funds",
    "主動式 ETF": "activeEtfs",
    "被動式 ETF": "passiveEtfs",
  };

  var SCOPE_GROUP = GROUP_CLASS;

  /* 分類是多選的：回傳目前勾選的 group 陣列，三個都勾（＝全部）時回傳 null
     表示不必過濾。「全部」那顆按鈕的文字不在 SCOPE_GROUP 裡，會自然被略過。 */
  function currentScopes() {
    var groups = [];
    var buttons = document.querySelectorAll(".scope-switch button.is-active");
    for (var index = 0; index < buttons.length; index += 1) {
      var key = SCOPE_GROUP[buttons[index].textContent.replace(/^✓\s*/, "").trim()];
      if (key && groups.indexOf(key) === -1) groups.push(key);
    }
    return groups.length && groups.length < 3 ? groups : null;
  }

  function sortValue(row, key) {
    if (key === CUSTOM_KEY) return row.returnPct;
    var entry = row.presets[key];
    return entry && typeof entry.returnPct === "number" ? entry.returnPct : null;
  }

  function rank(payload, ranking, from, to) {
    var rows = [];
    var skipped = [];
    var presets = {};
    ((ranking && ranking.instruments) || []).forEach(function (item) {
      presets[item.code] = item.returns || {};
    });
    (payload.instruments || []).forEach(function (item) {
      var values = item.values || [];
      var start = valueAsOf(values, from);
      var end = valueAsOf(values, to);
      if (!start || !end || start[0] === end[0] || !start[1]) {
        skipped.push(item.name + " " + item.code);
        return;
      }
      rows.push({
        code: item.code,
        name: item.name,
        group: GROUP_LABEL[item.group] || item.group || "",
        groupKey: item.group,
        returnPct: (end[1] / start[1] - 1) * 100,
        presets: presets[item.code] || {},
      });
    });
    var scopes = currentScopes();
    var scoped = scopes
      ? rows.filter(function (row) {
          return scopes.indexOf(row.groupKey) !== -1;
        })
      : rows;
    // Instruments without a value for the sorted column always go last, in
    // both directions — otherwise "由低至高" would open with a wall of dashes.
    scoped.sort(function (left, right) {
      var a = sortValue(left, sortKey);
      var b = sortValue(right, sortKey);
      if (a === null || b === null) {
        if (a === b) return left.name.localeCompare(right.name, "zh-TW");
        return a === null ? 1 : -1;
      }
      return sortDescending ? b - a : a - b;
    });
    return { rows: scoped, skipped: skipped, total: rows.length };
  }

  function installStyles() {
    if (document.getElementById("performance-custom-range-styles")) return;
    var style = document.createElement("style");
    style.id = "performance-custom-range-styles";
    style.textContent =
      // 掛在分類切換那一列的右側；窄螢幕時整組往下折行。
      ".performance-filter-row{flex-wrap:wrap;gap:12px}" +
      "#" + CONTROL_ID + "{flex:0 0 auto;display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px;margin-left:auto}" +
      "#" + CONTROL_ID + " .pcr-field{display:grid;gap:4px}" +
      "#" + CONTROL_ID + " .pcr-field span{color:#667483;font-size:12px;font-weight:800}" +
      "#" + CONTROL_ID + " input[type=date]{padding:7px 9px;border:1px solid #d6dee6;border-radius:8px;background:#fff;color:#06275f;font-size:14px;font-family:inherit}" +
      "#" + CONTROL_ID + " button{padding:8px 16px;border:0;border-radius:8px;background:#06275f;color:#fff;font-size:14px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "#" + CONTROL_ID + " button:disabled{opacity:.5;cursor:default}" +
      "#" + CONTROL_ID + " .pcr-warn{color:#8a4b2a;font-size:12.5px;font-weight:750;align-self:center}" +
      "#" + PANEL_ID + " .pcr-warn-box{margin:12px 20px;padding:9px 12px;border-left:3px solid #d8a13a;border-radius:0 8px 8px 0;background:#fdf6e8;color:#6b5220;font-size:13px}" +
      "body.pcr-custom #" + CONTROL_ID + " .pcr-apply{background:#0c8f74}" +
      "#" + BANNER_ID + "{margin:0 0 12px;padding:9px 12px;border-left:3px solid #06275f;border-radius:0 8px 8px 0;background:#eef2f7;color:#06275f;font-size:13px;font-weight:750}" +
      "#" + BANNER_ID + " .pcr-reset{margin-left:4px;padding:4px 10px;border:1px solid #06275f;border-radius:999px;background:#fff;color:#06275f;font-size:12px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "@media(max-width:720px){#" + CONTROL_ID + "{width:100%;margin-left:0}#" + CONTROL_ID + " .pcr-field{flex:1 1 42%}#" + CONTROL_ID + " input[type=date]{width:100%}}";
    /*
     * 手機版的欄位收合與橫向捲動由 index.html 的 popostock-performance-matrix
     * 樣式統一處理，兩張表（React 與本檔自訂區間）用同一組 class。
     */
    document.head.appendChild(style);
  }

  function warn(panel, message) {
    var existing = panel.querySelector(".pcr-warn");
    if (existing) existing.remove();
    var note = document.createElement("span");
    note.className = "pcr-warn";
    note.textContent = message;
    panel.appendChild(note);
    setTimeout(function () {
      note.remove();
    }, 6000);
  }

  function percent(value) {
    return (value >= 0 ? "+" : "−") + Math.abs(value).toFixed(2) + "%";
  }

  /* React's own nodes, hidden while a custom range is showing. */
  function reactBlocks() {
    var table = document.querySelector(
      ".performance-panel .performance-table",
    );
    var own = document.getElementById(PANEL_ID);
    if (table && own && own.contains(table)) table = null;
    return [
      table ? table.closest(".table-scroll") || table : null,
      document.querySelector(".performance-panel > .performance-summary"),
    ].filter(Boolean);
  }

  function restore() {
    activeRange = null;
    sortKey = CUSTOM_KEY;
    sortDescending = true;
    document.body.classList.remove("pcr-custom");
    reactBlocks().forEach(function (node) {
      node.style.removeProperty("display");
    });
    var mount = document.getElementById(PANEL_ID);
    if (mount) mount.innerHTML = "";
  }

  /* Re-run the stored range, e.g. after the scope or the sort column changed. */
  function reapply() {
    if (!activeRange) return;
    var range = activeRange;
    Promise.all([loadSeries(), loadRanking()])
      .then(function (loaded) {
        render(loaded[0], loaded[1], range.from, range.to);
      })
      .catch(function () {
        restore();
      });
  }

  function mountPoint() {
    var host = document.querySelector(".performance-panel");
    if (!host) return null;
    var mount = document.getElementById(PANEL_ID);
    if (!mount) {
      mount = document.createElement("section");
      mount.id = PANEL_ID;
      // Appended as the last child only. Inserting between React's children
      // made its next reconciliation throw NotFoundError on insertBefore and
      // blanked the whole panel.
      host.appendChild(mount);
      // Delegated once, on the container that survives every re-render — the
      // rows themselves are replaced each time we sort, and binding per render
      // would stack a fresh handler onto every later click.
      mount.addEventListener("click", onMountClick);
    }
    return mount;
  }

  function onMountClick(event) {
    if (!event.target.closest) return;
    if (event.target.closest(".pcr-reset")) {
      restore();
      return;
    }
    var sorter = event.target.closest("[data-pcr-sort]");
    if (sorter) {
      var key = sorter.getAttribute("data-pcr-sort");
      // Picking a different column restarts at 由高至低; clicking the column
      // already sorted flips the direction. Same rule as React's headers.
      if (sortKey === key) {
        sortDescending = !sortDescending;
      } else {
        sortKey = key;
        sortDescending = true;
      }
      reapply();
      return;
    }
    var instrument = event.target.closest("[data-pcr-code]");
    if (instrument) openInstrument(instrument.getAttribute("data-pcr-code"));
  }

  /* Our rows are our own nodes, so clicking an instrument forwards the click
     to React's matching button in the table we hid — the detail view opens
     exactly as it does from the preset table. */
  function openInstrument(code) {
    var buttons = document.querySelectorAll(
      ".performance-panel .performance-table .performance-instrument",
    );
    for (var index = 0; index < buttons.length; index += 1) {
      if (buttons[index].closest("#" + PANEL_ID)) continue;
      var small = buttons[index].querySelector("small");
      if (small && small.textContent.trim() === code) {
        buttons[index].click();
        return;
      }
    }
  }

  function headerCell(key, label) {
    var active = sortKey === key;
    var arrow = active ? (sortDescending ? "↓" : "↑") : "↕";
    return (
      '<th class="performance-period-col' + (active ? " is-active" : "") + '">' +
      '<button type="button" class="performance-period-sort" data-pcr-sort="' + key + '" ' +
      'title="' + (active
        ? (sortDescending ? "改為由低至高" : "改為由高至低")
        : "以" + label + "報酬排序") + '">' + label +
      '<span class="performance-sort-arrow" aria-hidden="true">' + arrow + "</span>" +
      "</button></th>"
    );
  }

  function returnCell(label, value, key) {
    var extra = sortKey === key ? " is-active" : "";
    if (value === null || value === undefined) {
      return (
        '<td data-label="' + label + '" class="performance-period-col' + extra +
        ' performance-return is-blank">–</td>'
      );
    }
    return (
      '<td data-label="' + label + '" class="performance-period-col' + extra +
      " performance-return is-" + (value >= 0 ? "positive" : "negative") + '">' +
      percent(value) + "</td>"
    );
  }

  function render(payload, ranking, from, to) {
    activeRange = { from: from, to: to };
    document.body.classList.add("pcr-custom");
    var mount = mountPoint();
    if (!mount) return;
    var result = rank(payload, ranking, from, to);

    if (!result.rows.length) {
      restore();
      mount.innerHTML =
        '<p class="pcr-warn-box">這個區間沒有任何標的同時具備起訖兩端的官方資料。</p>';
      return;
    }

    // Replace rather than duplicate: React's table and summary go dark while
    // ours occupies the same place.
    reactBlocks().forEach(function (node) {
      node.style.display = "none";
    });

    var periodLabels = (ranking && ranking.periods) || {};
    var periodKeys = Object.keys(periodLabels);

    // The summary follows the sorted column, the same way React's does, so the
    // headline number always matches the order on screen.
    var scored = result.rows.filter(function (row) {
      return sortValue(row, sortKey) !== null;
    });
    var values = scored
      .map(function (row) {
        return sortValue(row, sortKey);
      })
      .sort(function (a, b) {
        return a - b;
      });
    var best = values.length ? values[values.length - 1] : null;
    var top = scored.filter(function (row) {
      return sortValue(row, sortKey) === best;
    })[0];
    var rising = values.filter(function (value) {
      return value > 0;
    }).length;
    var median = values.length
      ? values.length % 2
        ? values[(values.length - 1) / 2]
        : (values[values.length / 2 - 1] + values[values.length / 2]) / 2
      : null;

    mount.innerHTML =
      '<div class="performance-summary" aria-label="排行摘要">' +
      "<article><span>可比較標的</span><strong>" + scored.length + " / " +
      (result.total + result.skipped.length) + "</strong></article>" +
      "<article><span>本期第一名</span><strong>" +
      (top ? top.name : "資料不足") + "</strong></article>" +
      '<article><span>第一名報酬</span><strong class="is-' +
      (best !== null && best >= 0 ? "positive" : "negative") + '">' +
      (best === null ? "-" : percent(best)) + "</strong></article>" +
      "<article><span>上漲標的／中位數</span><strong>" + rising + " 支 · " +
      (median === null ? "-" : percent(median)) + "</strong></article></div>" +
      '<div id="' + BANNER_ID + '">自訂區間 ' + from + " ~ " + to +
      (result.skipped.length ? " · " + result.skipped.length + " 檔資料不足已排除" : "") +
      '　<button type="button" class="pcr-reset">清除自訂區間</button></div>' +
      '<div class="table-scroll performance-table-scroll">' +
      '<table class="performance-table"><thead><tr>' +
      "<th>排名</th><th>標的</th><th>類型</th>" +
      headerCell(CUSTOM_KEY, "自訂區間") +
      periodKeys
        .map(function (key) {
          return headerCell(key, periodLabels[key]);
        })
        .join("") +
      "</tr></thead><tbody>" +
      result.rows
        .map(function (row, index) {
          return (
            "<tr>" +
            '<td data-label="排名" class="performance-rank">' +
            (sortValue(row, sortKey) === null ? "-" : index + 1) + "</td>" +
            '<td data-label="標的"><button type="button" class="performance-instrument" ' +
            'data-pcr-code="' + row.code + '">' +
            "<strong>" + row.name + "</strong><small>" + row.code + "</small></button></td>" +
            '<td data-label="類型"><span class="performance-group is-' +
            (GROUP_CLASS[row.group] || "funds") + '">' + row.group + "</span></td>" +
            returnCell("自訂區間", row.returnPct, CUSTOM_KEY) +
            periodKeys
              .map(function (key) {
                var entry = row.presets[key];
                return returnCell(
                  periodLabels[key],
                  entry ? entry.returnPct : null,
                  key,
                );
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody></table></div>";

  }

  function buildControl(defaultTo) {
    var panel = document.createElement("div");
    panel.id = CONTROL_ID;
    var from = new Date(defaultTo + "T00:00:00");
    from.setMonth(from.getMonth() - 1);
    var defaultFrom = from.toISOString().slice(0, 10);
    panel.innerHTML =
      '<label class="pcr-field"><span>自訂起始日</span>' +
      '<input type="date" class="pcr-from" value="' + defaultFrom + '" max="' + defaultTo + '"></label>' +
      '<label class="pcr-field"><span>結束日</span>' +
      '<input type="date" class="pcr-to" value="' + defaultTo + '" max="' + defaultTo + '"></label>' +
      '<button type="button" class="pcr-apply">計算</button>';

    var apply = panel.querySelector(".pcr-apply");
    apply.addEventListener("click", function () {
      var fromValue = panel.querySelector(".pcr-from").value;
      var toValue = panel.querySelector(".pcr-to").value;
      if (!fromValue || !toValue) {
        warn(panel, "請選擇起始日與結束日。");
        return;
      }
      if (fromValue >= toValue) {
        warn(panel, "起始日必須早於結束日。");
        return;
      }
      apply.disabled = true;
      apply.textContent = "計算中…";
      sortKey = CUSTOM_KEY;
      sortDescending = true;
      Promise.all([loadSeries(), loadRanking()])
        .then(function (loaded) {
          render(loaded[0], loaded[1], fromValue, toValue);
        })
        .catch(function () {
          warn(panel, "區間資料載入失敗，請稍後重試。");
        })
        .then(function () {
          apply.disabled = false;
          apply.textContent = "計算";
        });
    });
    return panel;
  }

  function latestDateOnPage() {
    var source = document.querySelector(".performance-asof strong");
    var match = source && source.textContent.match(/\b(20\d{2}-\d{2}-\d{2})\b/);
    if (match) return match[1];
    return new Date(Date.now() + 288e5).toISOString().slice(0, 10);
  }

  function attach() {
    var row = document.querySelector(".performance-panel .performance-filter-row");
    if (!row || document.getElementById(CONTROL_ID)) return;
    installStyles();
    row.appendChild(buildControl(latestDateOnPage()));
  }

  function watch() {
    attach();
    document.addEventListener("click", function (event) {
      if (!event.target.closest) return;
      // Scope is independent of the period: keep the custom range and
      // recompute it once React has updated its own active classes.
      if (activeRange && event.target.closest(".scope-switch button")) {
        setTimeout(reapply, 0);
      }
    });
    // The tab strip swaps panels without a reload, so re-attach when the
    // performance panel mounts again.
    new MutationObserver(function () {
      attach();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
