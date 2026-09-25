/*
 * PoPoStock 績效排行的兩個額外篩選器：自訂區間與排名篩選。
 *
 * 正式站的表格把八個固定期間並排，點欄位標題決定排序（見
 * scripts/patch-popostock-performance-matrix.mjs）。這支腳本在分類切換旁邊加上
 *
 *   1. 排名篩選：勾選一到多個期間 ＋ 選前 10／20／30／40／50 名，只留下在
 *      「任何一個」勾選期間進入前 N 名的標的。勾兩個期間是聯集不是交集──
 *      交集通常只剩兩三檔，看不出東西。
 *   2. 自訂區間：一組起訖日，算出來的報酬成為最前面的一欄。
 *
 * 只要其中一個生效，就把 React 那張表與摘要藏起來，改畫一張欄位相同的表；
 * 兩個都清掉才還給 React。這樣做是因為 React 的表格是 bundle 裡的元件，沒辦法
 * 從外面塞欄位或改它的篩選條件，而任何讓 React 重繪的動作都會自然還原它自己的
 * 表──那正是我們要的「回到原狀」行為。上方的橫幅一律標明目前套用了什麼。
 *
 * 排名是在「目前勾選的分類」範圍內算的：只看主動式 ETF 時，前 10 名就是主動式
 * ETF 的前 10 名，跟畫面上看到的順序一致。
 *
 * 自訂區間的報酬與正式站同一套規則：取起訖日當日或之前最近一筆官方值，
 * 來源是 data/performance-series.json，不內插；任一端沒有資料的標的直接排除並
 * 計數，不會偷偷挪到鄰近日期。八個固定期間則直接沿用
 * data/performance-ranking.json 已經算好的數字，確保與原表一致。
 */
(function () {
  "use strict";

  var SERIES_FILE = "data/performance-series.json";
  var RANKING_FILE = "data/performance-ranking.json";
  var PANEL_ID = "performance-custom-range";
  var CONTROL_ID = "performance-custom-range-control";
  var RANK_ID = "performance-rank-filter";
  var BANNER_ID = "performance-custom-range-banner";
  var CUSTOM_KEY = "__custom";
  var TOP_CHOICES = [10, 20, 30, 40, 50];

  var seriesPromise = null;
  var rankingPromise = null;
  var activeRange = null;
  var rankPeriods = [];
  var rankTop = 0;
  var sortKey = null;        // null＝沿用 React 目前排序的那一欄
  var sortDescending = true;
  var buildingRankControl = false;

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

  /* 八個固定期間伺服器已經算好；沿用它，數字才會跟被蓋掉的那張表一模一樣。 */
  function loadRanking() {
    if (rankingPromise) return rankingPromise;
    rankingPromise = loadJson(RANKING_FILE).catch(function (error) {
      rankingPromise = null;
      throw error;
    });
    return rankingPromise;
  }

  /* 起訖日當日或之前最近一筆；序列起點比較晚就回 null。 */
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

  function rankFilterOn() {
    return rankTop > 0 && rankPeriods.length > 0;
  }

  function overridden() {
    return !!activeRange || rankFilterOn();
  }

  /* 分類是多選的：回傳目前勾選的 group 陣列，三個都勾（＝全部）時回傳 null
     表示不必過濾。「全部」那顆按鈕的文字不在 GROUP_CLASS 裡，會自然被略過。 */
  function currentScopes() {
    var groups = [];
    var buttons = document.querySelectorAll(".scope-switch button.is-active");
    for (var index = 0; index < buttons.length; index += 1) {
      var key = GROUP_CLASS[buttons[index].textContent.replace(/^✓\s*/, "").trim()];
      if (key && groups.indexOf(key) === -1) groups.push(key);
    }
    return groups.length && groups.length < 3 ? groups : null;
  }

  function sortValue(row, key) {
    if (key === CUSTOM_KEY) {
      return typeof row.returnPct === "number" ? row.returnPct : null;
    }
    var entry = row.presets[key];
    return entry && typeof entry.returnPct === "number" ? entry.returnPct : null;
  }

  /* 接手時沿用 React 目前排序的欄位與方向，畫面不會突然跳掉。 */
  function inheritSort(periodLabels) {
    var head = document.querySelector(
      ".performance-panel .performance-table th.performance-period-col.is-active",
    );
    if (!head || head.closest("#" + PANEL_ID)) return;
    var label = head.textContent.replace(/[↓↑↕]/g, "").trim();
    Object.keys(periodLabels).forEach(function (key) {
      if (periodLabels[key] === label) sortKey = key;
    });
    if (sortKey) sortDescending = head.textContent.indexOf("↑") === -1;
  }

  function buildRows(ranking, series) {
    var rows = [];
    var skipped = [];
    var presets = {};
    ((ranking && ranking.instruments) || []).forEach(function (item) {
      presets[item.code] = item.returns || {};
    });

    if (activeRange && series) {
      (series.instruments || []).forEach(function (item) {
        var values = item.values || [];
        var start = valueAsOf(values, activeRange.from);
        var end = valueAsOf(values, activeRange.to);
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
    } else {
      ((ranking && ranking.instruments) || []).forEach(function (item) {
        rows.push({
          code: item.code,
          name: item.name,
          group: GROUP_LABEL[item.group] || item.group || "",
          groupKey: item.group,
          returnPct: null,
          presets: item.returns || {},
        });
      });
    }
    return { rows: rows, skipped: skipped };
  }

  /* 在勾選的任一期間進入前 N 名就留下（聯集）。排名是在已經套用分類之後的
     範圍內算的，跟畫面上看到的名次一致。 */
  function applyRankFilter(rows) {
    if (!rankFilterOn()) return rows;
    var keep = {};
    rankPeriods.forEach(function (key) {
      rows
        .filter(function (row) {
          return sortValue(row, key) !== null;
        })
        .sort(function (left, right) {
          return sortValue(right, key) - sortValue(left, key);
        })
        .slice(0, rankTop)
        .forEach(function (row) {
          keep[row.code] = true;
        });
    });
    return rows.filter(function (row) {
      return keep[row.code];
    });
  }

  function rank(ranking, series) {
    var built = buildRows(ranking, series);
    var universe = built.rows.length + built.skipped.length;
    var scopes = currentScopes();
    var scoped = scopes
      ? built.rows.filter(function (row) {
          return scopes.indexOf(row.groupKey) !== -1;
        })
      : built.rows;
    var filtered = applyRankFilter(scoped);
    // 排序欄位沒有值的標的固定沉底，兩個方向都是；否則「由低至高」會先看到一片破折號。
    filtered.sort(function (left, right) {
      var a = sortValue(left, sortKey);
      var b = sortValue(right, sortKey);
      if (a === null || b === null) {
        if (a === b) return left.name.localeCompare(right.name, "zh-TW");
        return a === null ? 1 : -1;
      }
      return sortDescending ? b - a : a - b;
    });
    return { rows: filtered, skipped: built.skipped, universe: universe };
  }

  function installStyles() {
    if (document.getElementById("performance-custom-range-styles")) return;
    var style = document.createElement("style");
    style.id = "performance-custom-range-styles";
    style.textContent =
      // 兩個篩選器掛在分類切換那一列；窄螢幕時整組往下折行。
      ".performance-filter-row{flex-wrap:wrap;gap:12px}" +
      "#" + RANK_ID + "{flex:1 1 380px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;" +
      "padding:8px 12px;border:1px solid #d6dee6;border-radius:8px;background:#fff}" +
      "#" + RANK_ID + ">b{color:#06275f;font-size:12.5px;font-weight:900;letter-spacing:.04em}" +
      "#" + RANK_ID + " .prf-periods{display:flex;flex-wrap:wrap;gap:4px 10px}" +
      "#" + RANK_ID + " label{display:inline-flex;align-items:center;gap:4px;color:#3d4d61;" +
      "font-size:13px;font-weight:800;cursor:pointer;white-space:nowrap}" +
      "#" + RANK_ID + " label.is-on{color:#06275f}" +
      "#" + RANK_ID + " input[type=checkbox]{width:15px;height:15px;accent-color:#06275f;cursor:pointer}" +
      "#" + RANK_ID + " select{padding:6px 9px;border:1px solid #d6dee6;border-radius:8px;" +
      "background:#fff;color:#06275f;font-size:13.5px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "body.pcr-ranked #" + RANK_ID + "{border-color:#0c8f74;box-shadow:0 0 0 1px #0c8f74}" +
      "#" + CONTROL_ID + "{flex:0 0 auto;display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px;margin-left:auto}" +
      "#" + CONTROL_ID + " .pcr-field{display:grid;gap:4px}" +
      "#" + CONTROL_ID + " .pcr-field span{color:#667483;font-size:12px;font-weight:800}" +
      "#" + CONTROL_ID + " input[type=date]{padding:7px 9px;border:1px solid #d6dee6;border-radius:8px;background:#fff;color:#06275f;font-size:14px;font-family:inherit}" +
      "#" + CONTROL_ID + " button{padding:8px 16px;border:0;border-radius:8px;background:#06275f;color:#fff;font-size:14px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "#" + CONTROL_ID + " button:disabled{opacity:.5;cursor:default}" +
      "#" + CONTROL_ID + " .pcr-warn{color:#8a4b2a;font-size:12.5px;font-weight:750;align-self:center}" +
      "#" + PANEL_ID + " .pcr-warn-box{margin:12px 20px;padding:9px 12px;border-left:3px solid #d8a13a;border-radius:0 8px 8px 0;background:#fdf6e8;color:#6b5220;font-size:13px}" +
      "body.pcr-custom #" + CONTROL_ID + " .pcr-apply{background:#0c8f74}" +
      "#" + BANNER_ID + "{margin:0 0 12px;padding:9px 12px;border-left:3px solid #06275f;border-radius:0 8px 8px 0;background:#eef2f7;color:#06275f;font-size:13px;font-weight:750;display:grid;gap:6px}" +
      "#" + BANNER_ID + " button{margin-left:6px;padding:4px 10px;border:1px solid #06275f;border-radius:999px;background:#fff;color:#06275f;font-size:12px;font-weight:800;font-family:inherit;cursor:pointer}" +
      "@media(max-width:720px){#" + RANK_ID + "{flex:1 1 100%}" +
      "#" + CONTROL_ID + "{width:100%;margin-left:0}#" + CONTROL_ID + " .pcr-field{flex:1 1 42%}" +
      "#" + CONTROL_ID + " input[type=date]{width:100%}}";
    /*
     * 手機版的欄位收合與橫向捲動由 index.html 的 popostock-performance-matrix
     * 樣式統一處理，兩張表（React 與這裡畫的）用同一組 class。
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

  /* React 自己的節點；我們接手的時候把它們藏起來。 */
  function reactBlocks() {
    var table = document.querySelector(".performance-panel .performance-table");
    var own = document.getElementById(PANEL_ID);
    if (table && own && own.contains(table)) table = null;
    return [
      table ? table.closest(".table-scroll") || table : null,
      document.querySelector(".performance-panel > .performance-summary"),
    ].filter(Boolean);
  }

  function showReact() {
    document.body.classList.remove("pcr-custom", "pcr-ranked");
    reactBlocks().forEach(function (node) {
      node.style.removeProperty("display");
    });
    var mount = document.getElementById(PANEL_ID);
    if (mount) mount.innerHTML = "";
    sortKey = null;
  }

  function clearRange() {
    activeRange = null;
    if (overridden()) apply();
    else showReact();
  }

  function clearRankFilter() {
    rankPeriods = [];
    rankTop = 0;
    syncRankControl();
    if (overridden()) apply();
    else showReact();
  }

  /* 重新取資料並重畫；沒有任何條件時就還給 React。 */
  function apply() {
    if (!overridden()) {
      showReact();
      return;
    }
    var needsSeries = !!activeRange;
    Promise.all([loadRanking(), needsSeries ? loadSeries() : null])
      .then(function (loaded) {
        render(loaded[0], loaded[1]);
      })
      .catch(function () {
        showReact();
      });
  }

  function mountPoint() {
    var host = document.querySelector(".performance-panel");
    if (!host) return null;
    var mount = document.getElementById(PANEL_ID);
    if (!mount) {
      mount = document.createElement("section");
      mount.id = PANEL_ID;
      // 只 append 在最後。曾經插在 React 的子節點之間，它下一次協調時
      // insertBefore 會丟 NotFoundError，整個面板變白。
      host.appendChild(mount);
      // 一次性委派：每次重排都會換掉整批列，綁在列上會愈疊愈多層。
      mount.addEventListener("click", onMountClick);
    }
    return mount;
  }

  function onMountClick(event) {
    if (!event.target.closest) return;
    if (event.target.closest(".pcr-reset")) {
      clearRange();
      return;
    }
    if (event.target.closest(".prf-clear")) {
      clearRankFilter();
      return;
    }
    var sorter = event.target.closest("[data-pcr-sort]");
    if (sorter) {
      var key = sorter.getAttribute("data-pcr-sort");
      // 換一欄就重新從高到低開始；點同一欄才翻轉方向，跟 React 的表頭同規則。
      if (sortKey === key) {
        sortDescending = !sortDescending;
      } else {
        sortKey = key;
        sortDescending = true;
      }
      apply();
      return;
    }
    var instrument = event.target.closest("[data-pcr-code]");
    if (instrument) openInstrument(instrument.getAttribute("data-pcr-code"));
  }

  /* 我們畫的是自己的節點，所以點標的時把 click 轉給 React 那張（被藏起來的）
     表裡對應的按鈕，個股頁就跟從原表點進去一樣會打開。 */
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

  function banner(periodLabels, skipped) {
    var lines = [];
    if (activeRange) {
      lines.push(
        "<div>自訂區間 " + activeRange.from + " ~ " + activeRange.to +
        (skipped.length ? " · " + skipped.length + " 檔資料不足已排除" : "") +
        '<button type="button" class="pcr-reset">清除自訂區間</button></div>',
      );
    }
    if (rankFilterOn()) {
      var names = rankPeriods.map(function (key) {
        return periodLabels[key] || key;
      });
      lines.push(
        "<div>只列出在 " + names.join("、") + " 進入前 " + rankTop + " 名的標的" +
        (names.length > 1 ? "（任一符合即列入）" : "") +
        '<button type="button" class="prf-clear">清除排名篩選</button></div>',
      );
    }
    return '<div id="' + BANNER_ID + '">' + lines.join("") + "</div>";
  }

  function render(ranking, series) {
    var periodLabels = (ranking && ranking.periods) || {};
    var periodKeys = Object.keys(periodLabels);
    if (!sortKey) {
      inheritSort(periodLabels);
      if (!sortKey) sortKey = activeRange ? CUSTOM_KEY : periodKeys[2] || periodKeys[0];
    }

    document.body.classList.toggle("pcr-custom", !!activeRange);
    document.body.classList.toggle("pcr-ranked", rankFilterOn());
    var mount = mountPoint();
    if (!mount) return;
    var result = rank(ranking, series);

    if (!result.rows.length) {
      reactBlocks().forEach(function (node) {
        node.style.display = "none";
      });
      mount.innerHTML =
        banner(periodLabels, result.skipped) +
        '<p class="pcr-warn-box">目前的條件沒有符合的標的。放寬名次、多勾幾個區間，或改一下分類。</p>';
      return;
    }

    // 取代而不是並排：React 的表格與摘要暫時隱藏，我們佔同一個位置。
    reactBlocks().forEach(function (node) {
      node.style.display = "none";
    });

    // 摘要跟著排序中的那一欄走，跟 React 的作法一致，標題數字才會跟畫面順序相符。
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
      "<article><span>符合條件標的</span><strong>" + result.rows.length + " / " +
      result.universe + "</strong></article>" +
      "<article><span>本期第一名</span><strong>" +
      (top ? top.name : "資料不足") + "</strong></article>" +
      '<article><span>第一名報酬</span><strong class="is-' +
      (best !== null && best >= 0 ? "positive" : "negative") + '">' +
      (best === null ? "-" : percent(best)) + "</strong></article>" +
      "<article><span>上漲標的／中位數</span><strong>" + rising + " 支 · " +
      (median === null ? "-" : percent(median)) + "</strong></article></div>" +
      banner(periodLabels, result.skipped) +
      '<div class="table-scroll performance-table-scroll">' +
      '<table class="performance-table"><thead><tr>' +
      "<th>排名</th><th>標的</th><th>類型</th>" +
      (activeRange ? headerCell(CUSTOM_KEY, "自訂區間") : "") +
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
            (activeRange ? returnCell("自訂區間", row.returnPct, CUSTOM_KEY) : "") +
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

  /* ------------------------------------------------------------ 排名篩選器 */

  function syncRankControl() {
    var host = document.getElementById(RANK_ID);
    if (!host) return;
    Array.prototype.forEach.call(host.querySelectorAll("input[type=checkbox]"), function (box) {
      box.checked = rankPeriods.indexOf(box.value) !== -1;
      box.parentElement.classList.toggle("is-on", box.checked);
    });
    var select = host.querySelector("select");
    if (select) select.value = String(rankTop);
  }

  function buildRankControl(periodLabels) {
    var host = document.createElement("div");
    host.id = RANK_ID;
    host.innerHTML =
      "<b>排名篩選</b><div class=\"prf-periods\">" +
      Object.keys(periodLabels)
        .map(function (key) {
          return (
            '<label><input type="checkbox" value="' + key + '">' +
            periodLabels[key] + "</label>"
          );
        })
        .join("") +
      "</div><select aria-label=\"取前幾名\"><option value=\"0\">不限名次</option>" +
      TOP_CHOICES.map(function (n) {
        return '<option value="' + n + '">前 ' + n + " 名</option>";
      }).join("") +
      "</select>";

    host.addEventListener("change", function (event) {
      var target = event.target;
      if (target.type === "checkbox") {
        var key = target.value;
        if (target.checked) {
          if (rankPeriods.indexOf(key) === -1) rankPeriods.push(key);
        } else {
          rankPeriods = rankPeriods.filter(function (item) {
            return item !== key;
          });
        }
        // 維持期間本來的先後順序，橫幅上讀起來才自然。
        rankPeriods = Object.keys(periodLabels).filter(function (item) {
          return rankPeriods.indexOf(item) !== -1;
        });
        target.parentElement.classList.toggle("is-on", target.checked);
      } else if (target.tagName === "SELECT") {
        rankTop = Number(target.value) || 0;
      }
      if (overridden()) apply();
      else showReact();
    });
    return host;
  }

  /* ------------------------------------------------------------ 自訂區間 */

  function buildRangeControl(defaultTo) {
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

    var applyButton = panel.querySelector(".pcr-apply");
    applyButton.addEventListener("click", function () {
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
      applyButton.disabled = true;
      applyButton.textContent = "計算中…";
      activeRange = { from: fromValue, to: toValue };
      sortKey = CUSTOM_KEY;
      sortDescending = true;
      Promise.all([loadRanking(), loadSeries()])
        .then(function (loaded) {
          render(loaded[0], loaded[1]);
        })
        .catch(function () {
          activeRange = null;
          warn(panel, "區間資料載入失敗，請稍後重試。");
        })
        .then(function () {
          applyButton.disabled = false;
          applyButton.textContent = "計算";
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
    var range = buildRangeControl(latestDateOnPage());
    row.appendChild(range);

    // 期間的 key 與標籤只有 ranking 檔裡有，所以排名篩選器要等檔案回來才建得出來。
    if (buildingRankControl) return;
    buildingRankControl = true;
    loadRanking()
      .then(function (ranking) {
        buildingRankControl = false;
        if (document.getElementById(RANK_ID)) return;
        var host = document.querySelector(".performance-panel .performance-filter-row");
        var anchor = document.getElementById(CONTROL_ID);
        if (!host || !anchor) return;
        host.insertBefore(buildRankControl(ranking.periods || {}), anchor);
        syncRankControl();
        if (overridden()) apply();
      })
      .catch(function () {
        buildingRankControl = false;
      });
  }

  function watch() {
    attach();
    document.addEventListener("click", function (event) {
      if (!event.target.closest) return;
      // 分類與期間無關：保留目前的條件，等 React 更新完 is-active 再重算。
      if (overridden() && event.target.closest(".scope-switch button")) {
        setTimeout(apply, 0);
      }
    });
    // 分頁列換頁不會重新載入，面板重新掛上來時要再接一次。
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
