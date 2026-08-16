(() => {
  "use strict";

  // Appended as the LAST child of the header and moved into place with flex
  // `order`, so React's own children are never re-parented. Inserting between
  // them throws NotFoundError on the next render.
  const HREF = "https://www.facebook.com/popo.stock/subscribe/";
  const FLAG = "data-popo-sponsor";

  function style() {
    if (document.getElementById("popo-sponsor-style")) return;
    const element = document.createElement("style");
    element.id = "popo-sponsor-style";
    element.textContent = [
      ".workspace-header{flex-wrap:wrap;gap:10px 14px}",
      // The logo is last in the DOM; order puts the button to its left.
      ".workspace-header .brand-logo{order:3}",
      ".popo-sponsor{order:2;margin-left:auto;display:inline-flex;align-items:center;gap:7px;",
      "background:#ffd43b;color:#12295c;font-size:14px;font-weight:800;line-height:1;",
      "padding:10px 18px;border-radius:999px;text-decoration:none;white-space:nowrap;",
      "border:1px solid #e8bd22;transition:filter .15s ease,transform .15s ease}",
      ".popo-sponsor:hover{filter:brightness(1.05);transform:translateY(-1px)}",
      ".popo-sponsor:active{transform:translateY(0)}",
      ".popo-sponsor:focus-visible{outline:2px solid #fff;outline-offset:2px}",
      ".popo-sponsor .heart{font-size:15px;line-height:1}",
      // Narrow screens can't fit title + button + logo on one row. Dropping
      // margin-left:auto and ordering the button last puts it beside the logo
      // on the wrapped row instead of stranding it past the right edge.
      "@media (max-width:640px){.popo-sponsor{order:4;margin-left:0;font-size:13px;",
      "padding:9px 16px}.workspace-header{align-items:flex-start}}",
    ].join("");
    document.head.appendChild(element);
  }

  function ensure() {
    const header = document.querySelector(".workspace-header");
    if (!header) return;
    style();
    if (header.querySelector("[" + FLAG + "]")) return;
    const link = document.createElement("a");
    link.className = "popo-sponsor";
    link.setAttribute(FLAG, "");
    link.href = HREF;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", "前往 Facebook 訂閱贊助波波流（另開新視窗）");
    link.innerHTML = '<span class="heart" aria-hidden="true">♥</span>贊助支持';
    header.appendChild(link);
  }

  function boot() {
    ensure();
    // React re-renders the header; re-attach whenever it does.
    new MutationObserver(() => {
      ensure();
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
