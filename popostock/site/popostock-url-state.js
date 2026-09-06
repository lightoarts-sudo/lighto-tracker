(() => {
  "use strict";

  const tabLabels = {
    "active-changes": "主動式 ETF 加減碼",
    "active-etfs": "主動式 ETF",
    "passive-etfs": "被動式 ETF",
    funds: "基金",
    performance: "績效排行",
    "common-holdings": "共同持股統計",
    "buy-consensus": "共識加碼",
    "taiwan-market": "台股加權指數大盤",
    "us-market": "美股大盤",
    "election-trend": "台灣選前走勢",
    "weight-gap": "權值股回前高",
    dividends: "配息資訊",
  };
  const labelTabs = new Map(
    Object.entries(tabLabels).map(([tab, label]) => [label, tab]),
  );
  const instrumentTabs = new Set(["active-etfs", "passive-etfs", "funds"]);
  let defaultTab = null;
  let applyingLocation = false;
  let initialized = false;

  function cleanText(element) {
    return element?.textContent?.replace(/\s+/g, " ").trim() || "";
  }

  function workspaceTabs() {
    return Array.from(
      document.querySelectorAll('.workspace-tabs [role="tab"]'),
    );
  }

  /*
   * 把「共識加碼」排到第二個位置。
   *
   * 用 CSS order 而不是搬 DOM：這排按鈕是 React 畫的，重排它的子節點會跟
   * reconciliation 打架（這個站已經有過 NotFoundError 的教訓）。.workspace-tabs
   * 是 flex，order 純視覺、不動樹狀結構，React 重繪也不會踩到。
   *
   * 每顆都給明確 order（索引 ×10），共識加碼給 5——落在第一顆的 0 與第二顆的
   * 10 之間。沒有明確 order 的元素預設 0，會全部擠到最前面，所以不能只設一顆。
   */
  const SECOND_TAB_LABEL = "共識加碼";

  function applyTabOrder() {
    const buttons = workspaceTabs();
    if (buttons.length < 3) return;
    let moved = null;
    buttons.forEach((button, index) => {
      if (cleanText(button) === SECOND_TAB_LABEL) moved = button;
      else button.style.order = String(index * 10);
    });
    if (moved) moved.style.order = "5";
  }

  function watchTabOrder() {
    const strip = document.querySelector(".workspace-tabs");
    if (!strip) return;
    applyTabOrder();
    // 只看子節點增減：覆蓋層之後才把自己的分頁掛上來，順序要跟著重算。
    // 不觀察 attributes，否則自己設 style 會把 observer 叫回來變成迴圈。
    new MutationObserver(applyTabOrder).observe(strip, { childList: true });
  }

  function selectedWorkspaceTab() {
    return (
      workspaceTabs().find(
        (element) =>
          element.getAttribute("aria-selected") === "true" ||
          element.classList.contains("is-active"),
      ) || null
    );
  }

  function tabForButton(button) {
    return labelTabs.get(cleanText(button)) || null;
  }

  function buttonForTab(tab) {
    const label = tabLabels[tab];
    if (!label) return null;
    return workspaceTabs().find((button) => cleanText(button) === label) || null;
  }

  function activeItemCode() {
    const item = document.querySelector(".item-row.is-active");
    return cleanText(item?.querySelector(".code-chip")) || null;
  }

  function itemForCode(code) {
    const normalized = code.trim().toUpperCase();
    return (
      Array.from(document.querySelectorAll(".item-row")).find(
        (item) =>
          cleanText(item.querySelector(".code-chip")).toUpperCase() ===
          normalized,
      ) || null
    );
  }

  function groupButtonForTab(tab) {
    const label = tabLabels[tab];
    if (!label) return null;
    return (
      Array.from(document.querySelectorAll(".group-switch button")).find(
        (button) => cleanText(button.querySelector("span") || button) === label,
      ) || null
    );
  }

  function waitFor(find, attempts = 50) {
    return new Promise((resolve) => {
      function poll(remaining) {
        const result = find();
        if (result || remaining <= 0) {
          resolve(result || null);
          return;
        }
        window.setTimeout(() => poll(remaining - 1), 40);
      }
      poll(attempts);
    });
  }

  function updateLocation(tab, code, mode = "push") {
    if (!tab || !tabLabels[tab]) return;
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    if (instrumentTabs.has(tab) && code) {
      url.searchParams.set("code", code.toUpperCase());
    } else {
      url.searchParams.delete("code");
    }
    // view 是配息資訊的子分頁參數（dividend-schedule.js 自己維護）。切到別的
    // 主分頁時要清掉，否則網址會殘留一個對該頁毫無意義的參數。
    if (tab !== "dividends") url.searchParams.delete("view");
    if (url.href === window.location.href) return;
    window.history[mode === "replace" ? "replaceState" : "pushState"](
      { popostock: true },
      "",
      url,
    );
    window.dispatchEvent(
      new CustomEvent("popostock:urlchange", {
        detail: { tab, code: url.searchParams.get("code") },
      }),
    );
  }

  function syncLocationFromPage(mode = "push") {
    if (applyingLocation) return;
    const selected = selectedWorkspaceTab();
    const tab = tabForButton(selected);
    if (!tab) return;
    updateLocation(tab, instrumentTabs.has(tab) ? activeItemCode() : null, mode);
  }

  async function applyLocation({ restoreDefault = false } = {}) {
    const url = new URL(window.location.href);
    let tab = url.searchParams.get("tab");
    const code = url.searchParams.get("code");
    if (!tab && restoreDefault) tab = defaultTab;
    if (!tab || !tabLabels[tab]) return;

    applyingLocation = true;
    try {
      let tabButton = await waitFor(() => buttonForTab(tab));
      if (!tabButton && instrumentTabs.has(tab)) {
        tabButton = await waitFor(() =>
          workspaceTabs().find((button) => cleanText(button) === "投資清單"),
        );
      }
      if (tabButton && tabButton.getAttribute("aria-selected") !== "true") {
        tabButton.click();
      }

      if (instrumentTabs.has(tab)) {
        // 只有在分頁列沒有這一組的按鈕時，才需要退回去按版面裡的 .group-switch。
        // 兩者都在時原本仍會空等 10 輪（400ms）才確定用不到——條件已經寫在下面
        // 的 if 裡，先判斷一次就能省掉那段等待。
        if (!buttonForTab(tab)) {
          const groupButton = await waitFor(() => groupButtonForTab(tab), 10);
          if (groupButton && !groupButton.classList.contains("is-active")) {
            groupButton.click();
          }
        }
        if (code) {
          const item = await waitFor(() => itemForCode(code));
          if (item && !item.classList.contains("is-active")) {
            item.click();
            await waitFor(() => {
              const selected = itemForCode(code);
              return selected?.classList.contains("is-active") ? selected : null;
            });
          }
        }
      }
    } finally {
      applyingLocation = false;
    }

    const selected = selectedWorkspaceTab();
    const actualTab = tabForButton(selected) || tab;
    const actualCode = instrumentTabs.has(actualTab) ? activeItemCode() : null;
    if (
      actualTab !== url.searchParams.get("tab") ||
      (instrumentTabs.has(actualTab) &&
        actualCode !== code?.trim().toUpperCase())
    ) {
      updateLocation(actualTab, actualCode, "replace");
    }
  }

  function clickChangesLocation(event) {
    if (applyingLocation) return;
    const target =
      event.target instanceof Element ? event.target : event.target?.parentElement;
    if (!target) return;
    if (
      !target.closest('.workspace-tabs [role="tab"]') &&
      !target.closest(".group-switch button") &&
      !target.closest(".item-row")
    ) {
      return;
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => syncLocationFromPage("push"));
    });
  }

  async function initialize() {
    if (initialized) return;
    const tabs = await waitFor(() => {
      const values = workspaceTabs();
      return values.length ? values : null;
    });
    if (!tabs) return;
    initialized = true;
    watchTabOrder();
    defaultTab = tabForButton(selectedWorkspaceTab());
    document.addEventListener("click", clickChangesLocation);
    window.addEventListener("popstate", () =>
      applyLocation({ restoreDefault: true }),
    );
    await applyLocation();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
