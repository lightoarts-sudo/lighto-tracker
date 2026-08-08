/*
 * PoPoStock 績效排行 custom date range.
 *
 * The release page offers fixed presets only (1 週 … 3 年). This appends a
 * 自訂區間 panel that computes a ranking for any two dates from
 * data/performance-series.json — one request covering all 76 instruments
 * rather than 76 separate history files.
 *
 * The return uses the same rule as the published ranking: the last official
 * value on or before each endpoint. No interpolation, and a date with no prior
 * data is reported as unavailable rather than silently shifted.
 *
 * The panel is our own DOM appended after React's table, never a mutation of
 * it, so a re-render cannot fight us; the observer only re-attaches it when the
 * page swaps tabs.
 */
(function () {
  "use strict";

  var SERIES_FILE = "data/performance-series.json";
  var PANEL_ID = "performance-custom-range";
  var CONTROL_ID = "performance-custom-range-control";
  var seriesPromise = null;

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

  function rank(payload, from, to) {
    var rows = [];
    var skipped = [];
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
        valueType: item.valueType === "nav" ? "淨值" : "收盤",
        startDate: start[0],
        startValue: start[1],
        endDate: end[0],
        endValue: end[1],
        returnPct: (end[1] / start[1] - 1) * 100,
      });
    });
    rows.sort(function (left, right) {
      return right.returnPct - left.returnPct;
    });
    return { rows: rows, skipped: skipped };
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
      ".pcr-row>.performance-periods{flex:0 1 auto;min-width:0}" +
      "#" + CONTROL_ID + "{flex:0 0 auto;display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px}" +
      "#" + CONTROL_ID + " .pcr-field{display:grid;gap:4px}" +
      "#" + CONTROL_ID + " .pcr-field span{color:#667483;font-size:12px;font-weight:800}" +
      "#" + CONTROL_ID + " input[type=date]{padding:7px 9px;border:1px solid #d6dee6;border-radius:8px;background:#fff;color:#06275f;font-size:14px;font-family:inherit}" +
      "#" + CONTROL_ID + " button{padding:8px 16px;border:0;border-radius:8px;background:#06275f;color:#fff;font-size:14px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "#" + CONTROL_ID + " button:disabled{opacity:.5;cursor:default}" +
      "#" + PANEL_ID + "{margin-top:18px;padding-top:16px;border-top:1px solid #d6dee6}" +
      "#" + PANEL_ID + " h3{margin:0 0 4px;color:#06275f;font-size:17px}" +
      "#" + PANEL_ID + " .pcr-note{margin:0 0 10px;color:#667483;font-size:12.5px;line-height:1.6}" +
      "#" + PANEL_ID + " .pcr-warn{margin:0 0 10px;padding:9px 12px;border-left:3px solid #d8a13a;border-radius:0 8px 8px 0;background:#fdf6e8;color:#6b5220;font-size:12.5px}" +
      "#" + PANEL_ID + " .pcr-scroll{overflow-x:auto}" +
      "#" + PANEL_ID + " table{width:100%;min-width:0;border-collapse:collapse;background:#fff;font-size:13px}" +
      "#" + PANEL_ID + " th{padding:7px 8px;border-bottom:1px solid #d6dee6;background:#fff;color:#667483;font-size:11.5px;font-weight:800;text-align:right;white-space:nowrap}" +
      "#" + PANEL_ID + " th:nth-child(-n+3),#" + PANEL_ID + " td:nth-child(-n+3){text-align:left}" +
      "#" + PANEL_ID + " td{padding:7px 8px;border-bottom:1px solid #edf1f4;background:#fff;color:#06275f;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}" +
      "#" + PANEL_ID + " td.is-up{color:#c23d4b;font-weight:800}" +
      "#" + PANEL_ID + " td.is-down{color:#16845b;font-weight:800}" +
      "#" + PANEL_ID + " td small{display:block;color:#8794a3;font-size:11px}" +
      "@media(max-width:720px){.pcr-row{gap:9px}#" + CONTROL_ID + "{width:100%}#" + CONTROL_ID + " .pcr-field{flex:1 1 42%}#" + CONTROL_ID + " input[type=date]{width:100%}}";
    document.head.appendChild(style);
  }

  function percent(value) {
    return (value >= 0 ? "+" : "−") + Math.abs(value).toFixed(2) + "%";
  }

  function render(results, payload, from, to) {
    var result = rank(payload, from, to);
    var body = results.querySelector(".pcr-result");
    if (!result.rows.length) {
      body.innerHTML =
        '<p class="pcr-warn">這個區間沒有任何標的同時具備起訖兩端的官方資料。</p>';
      return;
    }
    var top = result.rows[0];
    var rising = result.rows.filter(function (row) {
      return row.returnPct > 0;
    }).length;
    var middle = result.rows[Math.floor(result.rows.length / 2)];

    body.innerHTML =
      '<p class="pcr-note">' +
      "區間 " + from + " ~ " + to + " · 可比較 " + result.rows.length + " 檔 · " +
      "第一名 " + top.name + " " + percent(top.returnPct) + " · " +
      "上漲 " + rising + " 檔 · 中位數 " + percent(middle.returnPct) +
      "</p>" +
      (result.skipped.length
        ? '<p class="pcr-warn">' + result.skipped.length +
          " 檔在此區間資料不足，未列入：" + result.skipped.slice(0, 6).join("、") +
          (result.skipped.length > 6 ? " 等" : "") + "</p>"
        : "") +
      '<div class="pcr-scroll"><table><thead><tr>' +
      "<th>排名</th><th>標的</th><th>類型</th><th>區間報酬</th>" +
      "<th>起算值</th><th>結束值</th></tr></thead><tbody>" +
      result.rows
        .map(function (row, index) {
          return (
            "<tr><td>" + (index + 1) + "</td>" +
            "<td>" + row.name + "<small>" + row.code + "</small></td>" +
            "<td>" + row.group + "</td>" +
            '<td class="' + (row.returnPct >= 0 ? "is-up" : "is-down") + '">' +
            percent(row.returnPct) + "</td>" +
            "<td>" + row.startValue + "<small>" + row.startDate + "</small></td>" +
            "<td>" + row.endValue + "<small>" + row.endDate + "</small></td></tr>"
          );
        })
        .join("") +
      "</tbody></table></div>";
  }

  function buildControl(defaultTo, results) {
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
      var result = results.querySelector(".pcr-result");
      if (!fromValue || !toValue) {
        result.innerHTML = '<p class="pcr-warn">請選擇起始日與結束日。</p>';
        return;
      }
      if (fromValue >= toValue) {
        result.innerHTML = '<p class="pcr-warn">起始日必須早於結束日。</p>';
        return;
      }
      apply.disabled = true;
      result.innerHTML = '<p class="pcr-note">計算中…</p>';
      loadSeries()
        .then(function (payload) {
          render(results, payload, fromValue, toValue);
          results.scrollIntoView({ behavior: "smooth", block: "start" });
        })
        .catch(function () {
          result.innerHTML = '<p class="pcr-warn">區間資料載入失敗，請稍後重試。</p>';
        })
        .then(function () {
          apply.disabled = false;
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
    if (!host || !periods || document.getElementById(CONTROL_ID)) return;
    installStyles();

    var results = document.createElement("section");
    results.id = PANEL_ID;
    results.innerHTML =
      '<h3>自訂區間績效</h3>' +
      '<p class="pcr-note">與上方排行採用相同取值規則：起訖兩端各取當日或之前最近一筆官方淨值／收盤價，未含配息還原。</p>' +
      '<div class="pcr-result"></div>';
    host.appendChild(results);

    // Wrap the preset grid so the custom range sits to its right on wide
    // screens and wraps underneath on narrow ones, without disturbing the
    // grid that .performance-controls uses for its own rows.
    var row = document.createElement("div");
    row.className = "pcr-row";
    periods.parentElement.insertBefore(row, periods);
    row.appendChild(periods);
    row.appendChild(buildControl(latestDateOnPage(), results));
  }

  function watch() {
    attach();
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
