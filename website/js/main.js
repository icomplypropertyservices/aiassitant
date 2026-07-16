/**
 * Shared nav/footer + mobile menu for marketing site.
 * APP_URL = product app host.
 */
(function () {
  const APP_URL = "https://app.aiassistant.xyz";
  const SITE_NAME = "AI Assistant";

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
            <span class="brand-mark" aria-hidden="true">✦</span>
            <span>${SITE_NAME}</span>
          </a>
          <button class="nav-toggle" type="button" aria-label="Menu" data-nav-toggle>Menu</button>
          <nav class="nav-links" data-nav-links>
            ${navLink("/features.html", "Features")}
            ${navLink("/pricing.html", "Pricing")}
            ${navLink("/about.html", "About")}
            ${navLink("/support.html", "Support")}
          </nav>
          <div class="nav-cta" data-nav-cta>
            <a class="btn btn-ghost" href="${APP_URL}/login">Sign in</a>
            <a class="btn btn-primary" href="${APP_URL}/login">Open app</a>
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
              Multi-company AI workspace for teams — agents, projects, training, and clear billing.
            </div>
            <div>
              <strong>Product</strong>
              <a href="/features.html">Features</a>
              <a href="/pricing.html">Pricing</a>
              <a href="${APP_URL}">Launch app</a>
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
              <a href="${APP_URL}/login">Create account</a>
            </div>
          </div>
          <div class="footer-bottom">
            <span>© ${new Date().getFullYear()} ${SITE_NAME}. All rights reserved.</span>
            <span>App: <a href="${APP_URL}">app.aiassistant.xyz</a></span>
          </div>
        </div>`;
    }

    // App CTAs
    document.querySelectorAll("[data-app-href]").forEach((el) => {
      const pathSuffix = el.getAttribute("data-app-href") || "";
      el.setAttribute("href", APP_URL + pathSuffix);
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
