/**
 * Shared nav/footer + mobile menu for marketing site.
 * Single domain: aibusinessagent.xyz
 *   /           marketing
 *   /agents     product app
 *   /bay        AgentBay marketplace
 */
(function () {
  const ORIGIN = typeof location !== "undefined" ? location.origin : "https://aibusinessagent.xyz";
  const APP_URL = ORIGIN + "/agents";
  const BAY_URL = ORIGIN + "/bay";
  const SITE_NAME = "AI Business Agent";

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
            <a href="${BAY_URL}/browse">AgentBay</a>
            ${navLink("/about.html", "About")}
            ${navLink("/support.html", "Support")}
          </nav>
          <div class="nav-cta" data-nav-cta>
            <a class="btn btn-ghost" href="/demo.html">Demo</a>
            <a class="btn btn-primary" href="${APP_URL}/console">Console</a>
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
              AI workspaces, agent console, AgentBay marketplace, and clear billing for teams.
            </div>
            <div>
              <strong>Product</strong>
              <a href="/features.html">Features</a>
              <a href="/demo.html">Product demo</a>
              <a href="/pricing.html">Pricing</a>
              <a href="${APP_URL}">App</a>
              <a href="${BAY_URL}/browse">AgentBay (browse free)</a>
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
              <a href="${APP_URL}">/agents</a>
              ·
              <a href="${BAY_URL}">/bay</a>
            </span>
          </div>
        </div>`;
    }

    // App CTAs: data-app-href="/login") → /agents/login
    document.querySelectorAll("[data-app-href]").forEach((el) => {
      const pathSuffix = el.getAttribute("data-app-href") || "";
      el.setAttribute("href", APP_URL + pathSuffix);
    });
    // Bay CTAs: data-bay-href="/" → /bay/
    document.querySelectorAll("[data-bay-href]").forEach((el) => {
      const pathSuffix = el.getAttribute("data-bay-href") || "";
      el.setAttribute("href", BAY_URL + pathSuffix);
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
