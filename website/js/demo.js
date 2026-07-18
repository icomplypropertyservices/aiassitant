/**
 * Interactive product demo — guided walkthrough of the AI Business Agent console.
 * Pure client-side mock: no API keys, no auth.
 */
(function () {
  const STEPS = [
    {
      id: "dashboard",
      view: "dashboard",
      kicker: "Step 1 of 5",
      title: "Your ops HQ at a glance",
      body:
        "One login for multiple companies. See agents online, open tasks, and how much of your included token pool you’ve used this month.",
      bullets: [
        "Multi-company workspace under one account",
        "Live agent status and recent activity",
        "Token meter always visible — no surprise bills",
      ],
      nextLabel: "Next: Workspace →",
      screenTitle: "Dashboard · Fire Alarms Dublin",
    },
    {
      id: "workspace",
      view: "workspace",
      kicker: "Step 2 of 5",
      title: "Company → Projects → Tasks",
      body:
        "Run several businesses or client brands under one account. Projects keep work streams separated; agents attach where they belong.",
      bullets: [
        "Switch companies without new logins",
        "Projects for compliance, sales, ops, and more",
        "Ideal for agencies and multi-brand operators",
      ],
      nextLabel: "Next: Agents →",
      screenTitle: "Workspace · Companies & projects",
    },
    {
      id: "agents",
      view: "agents",
      kicker: "Step 3 of 5",
      title: "A real AI team, not one chatbot",
      body:
        "Main AI Orchestrator sits on top. Leads own domains. Specialists do focused work. Training files and AgentBay skills attach per agent.",
      bullets: [
        "Clear hierarchy and ownership",
        "Training library access per agent",
        "Hire skills from AgentBay when you need them",
      ],
      nextLabel: "Next: Chat →",
      screenTitle: "Agents · Hierarchy & skills",
    },
    {
      id: "chat",
      view: "chat",
      kicker: "Step 4 of 5",
      title: "Chat that creates real work",
      body:
        "Talk to a lead agent. It can draft checklists, queue tasks, and report token use — the same flow operators use in the live console.",
      bullets: [
        "Try a suggested prompt or type your own",
        "Simulated replies (no API call in this demo)",
        "Turn cost estimate shown in the header",
      ],
      nextLabel: "Next: Billing →",
      screenTitle: "Chat · Ops Lead",
    },
    {
      id: "billing",
      view: "billing",
      kicker: "Step 5 of 5",
      title: "Tokens you can explain to a client",
      body:
        "Plans include a monthly token pool. Premium models and overage draw from wallet credits. Pay with card or crypto.",
      bullets: [
        "Included pool first, then credits",
        "Live meter matches the console sidebar",
        "Stripe + ETH / SOL / XRP",
      ],
      nextLabel: "Start free trial →",
      screenTitle: "Billing · Pro plan",
      final: true,
    },
  ];

  const CHAT_SCRIPT = [
    {
      role: "bot",
      text: "I reviewed the training folder for Fire Alarms Dublin. Want a site visit checklist for commercial clients?",
    },
  ];

  const PROMPT_REPLIES = {
    checklist: {
      user: "Yes — draft one for multi-storey offices and flag any compliance gaps.",
      bot: "Here’s a 12-item site visit checklist for multi-storey offices (access control, panel location, sounder coverage, logbooks, extinguisher pairing…). I flagged 3 compliance gaps vs IS 3218 guidance and assigned Field specialist a task under Project: Compliance 2026.",
    },
    tokens: {
      user: "Summarize token usage for this project this week.",
      bot: "Compliance 2026 this week: ~184k tokens — mostly from the included Pro pool. Premium overage: $0. Live meter is always under Billing and in the sidebar.",
    },
    hire: {
      user: "Could we hire a sales closer skill from AgentBay?",
      bot: "Yes. Open AgentBay (browse free, no login), install a Sales closer skill on Sales Lead, then attach it to Project: Commercial quotes Q3. Want me to outline the install steps?",
    },
    default: {
      bot: "In the live product I’d use your training files and company context to answer that. Create a free trial to chat with real agents — this demo stays offline so anyone can explore safely.",
    },
  };

  const SUGGESTED = [
    { id: "checklist", label: "Draft site visit checklist" },
    { id: "tokens", label: "Token usage this week" },
    { id: "hire", label: "Hire skill from AgentBay" },
  ];

  let step = 0;
  let chatSeeded = false;

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function setStep(n, opts = {}) {
    const next = Math.max(0, Math.min(STEPS.length - 1, n));
    step = next;
    const s = STEPS[step];

    // Tour tabs
    $$("[data-demo-step]").forEach((btn) => {
      const i = Number(btn.getAttribute("data-demo-step"));
      const on = i === step;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });

    // Narration
    $("#demo-kicker").textContent = s.kicker;
    $("#demo-title").textContent = s.title;
    $("#demo-body").textContent = s.body;
    const ul = $("#demo-bullets");
    ul.innerHTML = s.bullets.map((b) => `<li>${b}</li>`).join("");

    const prev = $("#demo-prev");
    const nextBtn = $("#demo-next");
    prev.disabled = step === 0;
    nextBtn.textContent = s.nextLabel;
    nextBtn.dataset.final = s.final ? "1" : "0";

    // App shell
    showView(s.view);
    $("#demo-screen-title").textContent = s.screenTitle;

    if (s.view === "chat" && !chatSeeded) {
      seedChat();
      chatSeeded = true;
    }

    if (!opts.skipScroll && window.matchMedia("(max-width: 900px)").matches) {
      $(".demo-frame")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function showView(view) {
    $$(".demo-nav-item").forEach((el) => {
      el.classList.toggle("is-active", el.getAttribute("data-demo-view") === view);
    });
    $$(".demo-view").forEach((el) => {
      const on = el.getAttribute("data-view") === view;
      el.classList.toggle("is-active", on);
      if (on) el.removeAttribute("hidden");
      else el.setAttribute("hidden", "");
    });
  }

  function viewToStep(view) {
    const i = STEPS.findIndex((s) => s.view === view);
    return i >= 0 ? i : 0;
  }

  function seedChat() {
    const box = $("#demo-msgs");
    box.innerHTML = "";
    CHAT_SCRIPT.forEach((m) => appendMsg(m.role, m.text));
    const prompts = $("#demo-prompts");
    prompts.innerHTML = SUGGESTED.map(
      (p) =>
        `<button type="button" class="demo-prompt-chip" data-prompt="${p.id}">${p.label}</button>`,
    ).join("");
  }

  function appendMsg(role, text) {
    const box = $("#demo-msgs");
    const div = document.createElement("div");
    div.className = `demo-bubble ${role === "user" ? "user" : "bot"}`;
    div.textContent = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function appendTypingThen(botText) {
    const box = $("#demo-msgs");
    const typing = document.createElement("div");
    typing.className = "demo-bubble bot typing";
    typing.innerHTML = "<span></span><span></span><span></span>";
    box.appendChild(typing);
    box.scrollTop = box.scrollHeight;
    window.setTimeout(() => {
      typing.remove();
      appendMsg("bot", botText);
    }, 700 + Math.random() * 400);
  }

  function handlePrompt(id) {
    const pack = PROMPT_REPLIES[id] || PROMPT_REPLIES.default;
    if (pack.user) appendMsg("user", pack.user);
    appendTypingThen(pack.bot);
  }

  function handleFreeText(raw) {
    const t = (raw || "").trim();
    if (!t) return;
    appendMsg("user", t);
    const lower = t.toLowerCase();
    let bot = PROMPT_REPLIES.default.bot;
    if (/check|visit|compliance|office|gap/.test(lower)) bot = PROMPT_REPLIES.checklist.bot;
    else if (/token|usage|cost|bill|meter/.test(lower)) bot = PROMPT_REPLIES.tokens.bot;
    else if (/agentbay|hire|skill|sales|closer/.test(lower)) bot = PROMPT_REPLIES.hire.bot;
    else if (/price|plan|pro|starter/.test(lower)) {
      bot =
        "Plans: Trial $0 (50k tokens), Starter $39, Pro $99, Business $249. Full detail on the Pricing page — or start a free trial in the real console.";
    }
    appendTypingThen(bot);
  }

  function bind() {
    if (!$(".demo-section")) return;

    $$("[data-demo-step]").forEach((btn) => {
      btn.addEventListener("click", () => setStep(Number(btn.getAttribute("data-demo-step"))));
    });

    $$("[data-demo-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const view = btn.getAttribute("data-demo-view");
        setStep(viewToStep(view));
      });
    });

    $$("[data-demo-goto]").forEach((btn) => {
      btn.addEventListener("click", () => setStep(Number(btn.getAttribute("data-demo-goto"))));
    });

    $("#demo-prev")?.addEventListener("click", () => setStep(step - 1));
    $("#demo-next")?.addEventListener("click", () => {
      const s = STEPS[step];
      if (s.final) {
        const app = document.querySelector("[data-app-href]")?.getAttribute("href") || "/agents/login";
        window.location.href = app.includes("login") ? app : "/agents/login";
        return;
      }
      setStep(step + 1);
    });

    $("#demo-prompts")?.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-prompt]");
      if (!chip) return;
      handlePrompt(chip.getAttribute("data-prompt"));
    });

    $("#demo-compose")?.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("#demo-input");
      handleFreeText(input.value);
      input.value = "";
    });

    // Keyboard: left/right when focus is not in an input
    document.addEventListener("keydown", (e) => {
      if (e.target.matches("input, textarea, select")) return;
      if (e.key === "ArrowRight") setStep(step + 1);
      if (e.key === "ArrowLeft") setStep(step - 1);
    });

    setStep(0, { skipScroll: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
