/**
 * Shared nav/footer + mobile menu for marketing site.
 *
 * Apex path layout (aibusinessagent.xyz — no subdomains):
 *   /           this marketing site
 *   /agents/*   product app SPA
 *   /bay/*      AgentBay marketplace SPA
 *   /api/*      product API
 */
(function () {
  const APEX = "https://aibusinessagent.xyz";

  function publicOrigin() {
    try {
      const h = location.hostname || "";
      if (h === "localhost" || h === "127.0.0.1") return location.origin;
      // Prefer apex so deep links stay on the canonical host
      if (h === "aibusinessagent.xyz" || h === "www.aibusinessagent.xyz") return APEX;
      return location.origin;
    } catch (_) {
      return APEX;
    }
  }

  const ORIGIN = publicOrigin();
  const APP_URL = ORIGIN + "/agents";
  const BAY_URL = ORIGIN + "/bay";
  // Same-origin path form (works even if host flips www↔apex mid-session)
  const APP_PATH = "/agents";
  const BAY_PATH = "/bay";
  // Must match Google OAuth consent screen app name exactly (verification).
  const SITE_NAME = "Ai Business Agent";

  const path = (location.pathname.split("/").pop() || "index.html").toLowerCase();

  function navLink(href, label) {
    const file = href.split("/").pop().toLowerCase();
    const active = path === file || (path === "" && file === "index.html");
    return `<a href="${href}"${active ? ' aria-current="page" style="color:#0f172a;font-weight:650"' : ""}>${label}</a>`;
  }

  function injectChrome() {
    const header = document.querySelector("[data-site-header]");
    if (header) {
      header.innerHTML = `
        <div class="container nav-inner">
          <a class="brand" href="/">
            <span class="brand-mark" aria-hidden="true"><img src="/images/logo.png" alt="" width="36" height="36" /></span>
            <span>${SITE_NAME}</span>
          </a>
          <button class="nav-toggle" type="button" aria-label="Menu" data-nav-toggle>Menu</button>
          <nav class="nav-links" data-nav-links>
            ${navLink("/features.html", "Features")}
            ${navLink("/demo.html", "Demo")}
            ${navLink("/pricing.html", "Pricing")}
            <a href="${BAY_PATH}/browse" data-bay-href="/browse">AgentBay</a>
            ${navLink("/about.html", "About")}
            ${navLink("/support.html", "Support")}
          </nav>
          <div class="nav-cta" data-nav-cta>
            <a class="btn btn-ghost" href="${BAY_PATH}/browse" data-bay-href="/browse">AgentBay</a>
            <a class="btn btn-primary" href="${APP_PATH}/login" data-app-href="/login">Open app</a>
          </div>
        </div>`;
    }

    const footer = document.querySelector("[data-site-footer]");
    if (footer) {
      footer.innerHTML = `
        <div class="container">
          <div class="footer-grid">
            <div>
              <strong>${SITE_NAME}</strong>
              Landing site, agent console, and AgentBay marketplace — one apex domain.
            </div>
            <div>
              <strong>Product</strong>
              <a href="/features.html">Features</a>
              <a href="/demo.html">Product demo</a>
              <a href="/pricing.html">Pricing</a>
              <a href="${APP_PATH}/login" data-app-href="/login">Open app (/agents)</a>
              <a href="${BAY_PATH}/browse" data-bay-href="/browse">AgentBay (/bay)</a>
            </div>
            <div>
              <strong>Company</strong>
              <a href="/about.html">About</a>
              <a href="/support.html">Support</a>
              <a href="mailto:firealarmsdublin@gmail.com">Contact</a>
            </div>
            <div>
              <strong>Legal</strong>
              <a href="/privacy.html">Privacy</a>
              <a href="/terms.html">Terms</a>
              <a href="/support.html">Support</a>
            </div>
          </div>
          <div class="footer-bottom">
            <span>© ${new Date().getFullYear()} ${SITE_NAME}. All rights reserved.</span>
            <span>
              <a href="/">Landing</a>
              ·
              <a href="${APP_PATH}" data-app-href="">App</a>
              ·
              <a href="${BAY_PATH}" data-bay-href="">AgentBay</a>
            </span>
          </div>
        </div>`;
    }

    // App CTAs: data-app-href="/login") → /agents/login (path layout; works on apex + www)
    document.querySelectorAll("[data-app-href]").forEach((el) => {
      const pathSuffix = el.getAttribute("data-app-href");
      if (pathSuffix === null) return;
      el.setAttribute("href", APP_PATH + (pathSuffix || ""));
    });
    // Bay CTAs: data-bay-href="/browse") → /bay/browse
    document.querySelectorAll("[data-bay-href]").forEach((el) => {
      const pathSuffix = el.getAttribute("data-bay-href");
      if (pathSuffix === null) return;
      el.setAttribute("href", BAY_PATH + (pathSuffix || ""));
    });

    const toggle = document.querySelector("[data-nav-toggle]");
    const nav = document.querySelector(".nav");
    if (toggle && nav) {
      toggle.addEventListener("click", () => nav.classList.toggle("open"));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectChrome);
  } else {
    injectChrome();
  }
})();
