/*
 * PoPoStock 績效排行 custom date range.
 *
 * The release table shows all eight preset periods side by side (see
 * scripts/patch-popostock-performance-matrix.mjs). This adds a date pair next
 * to the preset buttons and, once applied, rewrites the ranking table and
 * summary in place with one extra column — 自訂區間 — placed first among the
 * return columns and used as the sort key, so it reads as the same table
 * rather than a second one.
 *
 * The return uses the same rule as the published ranking: the last official
 * value on or before each endpoint, taken from data/performance-series.json
 * (one request covering all 76 instruments). No interpolation, and an
 * instrument without data at either endpoint is excluded and counted, never
 * silently shifted to a nearby date.
 *
 * Rewriting React's own DOM is deliberate here: clicking any preset re-renders
 * the table and restores it, which is exactly the "go back" behaviour we want.
 * A banner marks the table as overridden so the state is never ambiguous.
 */
(function () {
  "use strict";


  var SERIES_FILE = "data/performance-series.json";
  var RANKING_FILE = "data/performance-ranking.json";
  var PANEL_ID = "performance-custom-range";
  var CONTROL_ID = "performance-custom-range-control";
  var BANNER_ID = "performance-custom-range-banner";
  var seriesPromise = null;
  var rankingPromise = null;
  var activeRange = null;

  function baseUrl() {
    var base = document.querySelector("base[href]");
    if (base) return new URL(base.getAttribute("href"), window.location.href).href.replace(/\/$/, "");
    var match = window.location.href.match(/^(https?:\/\/[^/]+\/popostock)/);
    return match ? match[1] : "";
  }

  function loadSeries() {
    if (seriesPromise) return seriesPromise;
    seriesPromise = fetch(baseUrl() + "/" + SERIES_FILE, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .catch(function (error) {
        seriesPromise = null;
        throw error;
      });
    return seriesPromise;
  }

  /* The eight preset columns are already computed on the server; reusing them
     keeps every number identical to the table this one replaces. */
  function loadRanking() {
    if (rankingPromise) return rankingPromise;
    rankingPromise = fetch(baseUrl() + "/" + RANKING_FILE, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .catch(function (error) {
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
        valueType: item.valueType === "nav" ? "淨值" : "收盤",
        startDate: start[0],
        startValue: start[1],
        endDate: end[0],
        endValue: end[1],
        returnPct: (end[1] / start[1] - 1) * 100,
        presets: presets[item.code] || {},
      });
    });
    var scope = currentScope();
    var scoped = scope
      ? rows.filter(function (row) {
          return row.groupKey === scope;
        })
      : rows;
    var descending = sortDescending();
    scoped.sort(function (left, right) {
      return descending
        ? right.returnPct - left.returnPct
        : left.returnPct - right.returnPct;
    });
    return { rows: scoped, skipped: skipped, total: rows.length };
  }

  function installStyles() {
    if (document.getElementById("performance-custom-range-styles")) return;
    var style = document.createElement("style");
    style.id = "performance-custom-range-styles";
    style.textContent =
      ".pcr-row{display:flex;flex-wrap:wrap;align-items:stretch;gap:12px}" +
      // The preset grid is repeat(8,minmax(82px,1fr)), so as a flex item it
      // would stretch across the whole row and push this control onto the
      // next line. Sizing it to content leaves room beside 3 年.
      ".pcr-row>.performance-periods{flex:0 1 auto;min-width:0;max-width:100%}" +
      // 手機上預設區間是 4 欄的格線（最小 92px），整列 388px 寬；不夾住寬度
      // 它會把整個績效面板撐寬，右邊的「基金」「被動式 ETF」就被裁掉。
      ".pcr-row{max-width:100%}" +
      "#" + CONTROL_ID + "{flex:0 0 auto;display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px}" +
      "#" + CONTROL_ID + " .pcr-field{display:grid;gap:4px}" +
      "#" + CONTROL_ID + " .pcr-field span{color:#667483;font-size:12px;font-weight:800}" +
      "#" + CONTROL_ID + " input[type=date]{padding:7px 9px;border:1px solid #d6dee6;border-radius:8px;background:#fff;color:#06275f;font-size:14px;font-family:inherit}" +
      "#" + CONTROL_ID + " button{padding:8px 16px;border:0;border-radius:8px;background:#06275f;color:#fff;font-size:14px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "#" + CONTROL_ID + " button:disabled{opacity:.5;cursor:default}" +
      "#" + CONTROL_ID + " .pcr-warn{color:#8a4b2a;font-size:12.5px;font-weight:750;align-self:center}" +
      "#" + PANEL_ID + " .pcr-warn-box{margin:12px 20px;padding:9px 12px;border-left:3px solid #d8a13a;border-radius:0 8px 8px 0;background:#fdf6e8;color:#6b5220;font-size:13px}" +
      "body.pcr-custom .performance-periods button.is-active{background:transparent;color:var(--muted)}" +
      "body.pcr-custom #" + CONTROL_ID + " .pcr-apply{background:#0c8f74}" +
      "#" + BANNER_ID + "{margin:0 0 12px;padding:9px 12px;border-left:3px solid #06275f;border-radius:0 8px 8px 0;background:#eef2f7;color:#06275f;font-size:13px;font-weight:750}" +
      "#" + BANNER_ID + " .pcr-reset{margin-left:4px;padding:4px 10px;border:1px solid #06275f;border-radius:999px;background:#fff;color:#06275f;font-size:12px;font-weight:800;font-family:inherit;cursor:pointer}" +











      "@media(max-width:720px){.pcr-row{gap:9px}#" + CONTROL_ID + "{width:100%}#" + CONTROL_ID + " .pcr-field{flex:1 1 42%}#" + CONTROL_ID + " input[type=date]{width:100%}}" +
      /*
       * 手機版的欄位收合與橫向捲動改由 index.html 的
       * popostock-performance-matrix 樣式統一處理，兩張表（React 與本檔自訂
       * 區間）用同一組 class，不再需要在這裡用 nth-child 各自對齊。
       */
      "";
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

  var GROUP_CLASS = {
    基金: "funds",
    "主動式 ETF": "activeEtfs",
    "被動式 ETF": "passiveEtfs",
  };

  /* React's own nodes, hidden while a custom range is showing. */
  var SCOPE_GROUP = {
    基金: "funds",
    "主動式 ETF": "activeEtfs",
    "被動式 ETF": "passiveEtfs",
  };

  function currentScope() {
    var active = document.querySelector(".scope-switch button.is-active");
    return active ? SCOPE_GROUP[active.textContent.trim()] || null : null;
  }

  function sortDescending() {
    var button = document.querySelector(".performance-sort");
    return button ? button.textContent.indexOf("由低至高") === -1 : true;
  }

  function reactBlocks() {
    var table = document.querySelector(".performance-table");
    return [
      table ? table.closest(".table-scroll") || table : null,
      document.querySelector(".performance-summary"),
    ].filter(Boolean);
  }

  function restore() {
    activeRange = null;
    document.body.classList.remove("pcr-custom");
    reactBlocks().forEach(function (node) {
      node.style.removeProperty("display");
    });
    var mount = document.getElementById(PANEL_ID);
    if (mount) mount.innerHTML = "";
  }

  /* Re-run the stored range, e.g. after the scope or sort changed. */
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
    }
    return mount;
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

  function returnCell(label, value, extra) {
    if (value === null || value === undefined) {
      return (
        '<td data-label="' + label + '" class="performance-period-col' +
        (extra || "") + ' performance-return is-blank">–</td>'
      );
    }
    return (
      '<td data-label="' + label + '" class="performance-period-col' +
      (extra || "") + " performance-return is-" +
      (value >= 0 ? "positive" : "negative") + '">' + percent(value) + "</td>"
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

    var periodKeys = (ranking && ranking.periods)
      ? Object.keys(ranking.periods)
      : [];
    var periodLabels = (ranking && ranking.periods) || {};

    var top = result.rows[0];
    var rising = result.rows.filter(function (row) {
      return row.returnPct > 0;
    }).length;
    var middle = result.rows[Math.floor(result.rows.length / 2)];

    mount.innerHTML =
      '<div class="performance-summary" aria-label="排行摘要">' +
      "<article><span>可比較標的</span><strong>" + result.rows.length + " / " +
      (result.total + result.skipped.length) + "</strong></article>" +
      "<article><span>本期第一名</span><strong>" + top.name + "</strong></article>" +
      '<article><span>第一名報酬</span><strong class="is-' +
      (top.returnPct >= 0 ? "positive" : "negative") + '">' +
      percent(top.returnPct) + "</strong></article>" +
      "<article><span>上漲標的／中位數</span><strong>" + rising + " 支 · " +
      percent(middle.returnPct) + "</strong></article></div>" +
      '<div id="' + BANNER_ID + '">自訂區間 ' + from + " ~ " + to +
      (result.skipped.length ? " · " + result.skipped.length + " 檔資料不足已排除" : "") +
      '　<button type="button" class="pcr-reset">回到預設區間</button></div>' +
      '<div class="table-scroll performance-table-scroll">' +
      '<table class="performance-table"><thead><tr>' +
      "<th>排名</th><th>標的</th><th>類型</th>" +
      '<th class="performance-period-col is-active">自訂區間</th>' +
      periodKeys
        .map(function (key) {
          return '<th class="performance-period-col">' + periodLabels[key] + "</th>";
        })
        .join("") +
      "</tr></thead><tbody>" +
      result.rows
        .map(function (row, index) {
          return (
            "<tr>" +
            '<td data-label="排名" class="performance-rank">' + (index + 1) + "</td>" +
            '<td data-label="標的"><button type="button" class="performance-instrument" ' +
            'data-pcr-code="' + row.code + '">' +
            "<strong>" + row.name + "</strong><small>" + row.code + "</small></button></td>" +
            '<td data-label="類型"><span class="performance-group is-' +
            (GROUP_CLASS[row.group] || "funds") + '">' + row.group + "</span></td>" +
            returnCell("自訂區間", row.returnPct, " is-active") +
            periodKeys
              .map(function (key) {
                var entry = row.presets[key];
                return returnCell(
                  periodLabels[key],
                  entry ? entry.returnPct : null,
                  "",
                );
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody></table></div>";

    mount.querySelector(".pcr-reset").addEventListener("click", restore);
    mount.addEventListener("click", function (event) {
      var button = event.target.closest
        ? event.target.closest("[data-pcr-code]")
        : null;
      if (button) openInstrument(button.getAttribute("data-pcr-code"));
    });
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
      var result = null;
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
    var cells = document.querySelectorAll(".performance-panel td, .performance-panel strong");
    for (var index = 0; index < cells.length; index += 1) {
      var match = cells[index].textContent.match(/\b(20\d{2}-\d{2}-\d{2})\b/);
      if (match) return match[1];
    }
    return new Date(Date.now() + 288e5).toISOString().slice(0, 10);
  }

  function attach() {
    var host = document.querySelector(".performance-panel");
    var periods = document.querySelector(".performance-periods");
    if (!periods || document.getElementById(CONTROL_ID)) return;
    installStyles();

    // Wrap the preset grid so the custom range sits to its right on wide
    // screens and wraps underneath on narrow ones, without disturbing the
    // grid that .performance-controls uses for its own rows.
    var row = document.createElement("div");
    row.className = "pcr-row";
    periods.parentElement.insertBefore(row, periods);
    row.appendChild(periods);
    row.appendChild(buildControl(latestDateOnPage()));
  }

  function watch() {
    attach();
    document.addEventListener("click", function (event) {
      if (!event.target.closest) return;
      // A preset is the other half of the same either/or choice, so picking one
      // drops the custom range.
      if (event.target.closest(".performance-periods button")) {
        restore();
        return;
      }
      // Scope and sort are independent of the period: keep the custom range and
      // recompute it once React has updated its own active classes.
      if (
        activeRange &&
        event.target.closest(".scope-switch button, .performance-sort")
      ) {
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
