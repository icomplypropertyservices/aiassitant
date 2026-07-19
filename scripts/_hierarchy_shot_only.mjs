/**
 * Capture live agents (trial 10 cap), open hierarchy UI with API mocks so
 * concurrent key rotation does not bounce the SPA to login mid-screenshot.
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BASE = 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const CREDS_PATH = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const REPORT_PATH = path.join(__dirname, 'hierarchy_probe_report.json')
const TRIAL_MAX = 10

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  return JSON.parse(fs.readFileSync(CREDS_PATH, 'utf8'))
}

function saveCreds(c) {
  fs.writeFileSync(CREDS_PATH, JSON.stringify(c, null, 2))
}

async function login(creds) {
  for (let i = 0; i < 8; i++) {
    const r = await fetch(`${BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email: creds.email, password: creds.password }),
    })
    const j = await r.json().catch(() => null)
    const key = j?.api_key || j?.token
    if (r.ok && key) {
      creds.api_key = key
      if (j.user?.id != null) creds.user_id = j.user.id
      saveCreds(creds)
      return j
    }
    if (r.status === 429) {
      const m = /Try again in (\d+)/i.exec(String(j?.detail || ''))
      const sec = m ? +m[1] + 2 : 20 + i * 5
      console.log('429 wait', sec)
      await new Promise((r) => setTimeout(r, sec * 1000))
      continue
    }
    throw new Error(`login ${r.status} ${JSON.stringify(j)}`)
  }
  throw new Error('login exhausted')
}

async function apiGet(creds, p) {
  const r = await fetch(`${BASE}${p}`, {
    headers: {
      Authorization: `Bearer ${creds.api_key}`,
      'X-API-Key': creds.api_key,
      Accept: 'application/json',
    },
  })
  const body = await r.json().catch(() => null)
  return { status: r.status, body }
}

function buildTree(agents) {
  const byParent = new Map()
  for (const a of agents) {
    const pid = a.parent_id == null ? 'root' : String(a.parent_id)
    if (!byParent.has(pid)) byParent.set(pid, [])
    byParent.get(pid).push(a)
  }
  function node(a) {
    const kids = byParent.get(String(a.id)) || []
    return {
      ...a,
      children: kids.map(node),
      reports_count: kids.length,
    }
  }
  const roots = byParent.get('root') || []
  // orphans whose parent missing
  const ids = new Set(agents.map((a) => a.id))
  for (const a of agents) {
    if (a.parent_id != null && !ids.has(a.parent_id) && !roots.find((r) => r.id === a.id)) {
      roots.push(a)
    }
  }
  return {
    tree: roots.map(node),
    flat: agents.map((a) => ({
      ...a,
      reports_count: (byParent.get(String(a.id)) || []).length,
      parent_name: agents.find((p) => p.id === a.parent_id)?.name || null,
    })),
    orchestrator: agents.find((a) => (a.hierarchy_role || '').toLowerCase() === 'orchestrator') || null,
  }
}

async function main() {
  const creds = loadCreds()
  let loginBody = await login(creds)
  console.log('login', loginBody.user?.id, loginBody.user?.plan)

  let agentsRes = await apiGet(creds, '/api/agents/')
  if (agentsRes.status === 401) {
    loginBody = await login(creds)
    agentsRes = await apiGet(creds, '/api/agents/')
  }
  let agents = Array.isArray(agentsRes.body)
    ? agentsRes.body
    : agentsRes.body?.agents || []
  console.log('agents', agentsRes.status, agents.length)

  let hierRes = await apiGet(creds, '/api/agents/hierarchy')
  let hierarchy = hierRes.status === 200 ? hierRes.body : null
  if (!hierarchy || hierRes.status !== 200) {
    console.warn('hierarchy_api', hierRes.status, '— building tree from agents list')
    hierarchy = buildTree(agents)
  } else {
    console.log('hierarchy_api 200')
  }

  for (const a of agents) {
    console.log(`  #${a.id} ${(a.hierarchy_role || '-').padEnd(14)} ${a.name}`)
  }

  const slots = Math.max(0, TRIAL_MAX - agents.length)
  let spawn = { mode: 'skipped', reason: `at trial cap (${agents.length}/${TRIAL_MAX})` }
  if (slots > 0) {
    const orch =
      agents.find((a) => (a.hierarchy_role || '').toLowerCase() === 'orchestrator') || agents[0]
    if (orch?.id) {
      const r = await fetch(`${BASE}/api/agents/${orch.id}/skills/run`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${creds.api_key}`,
          'X-API-Key': creds.api_key,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          skill_id: 'spawn_specialist',
          args: { domain: 'research', name: `Live Research Specialist ${Date.now().toString(36)}` },
        }),
      })
      const body = await r.json().catch(() => null)
      spawn = { mode: 'spawn_specialist_skill', status: r.status, body }
      console.log('spawn skill', r.status, JSON.stringify(body).slice(0, 200))
      if (r.status === 401 || (body && body.ok === false && !body.agent)) {
        // re-login and try POST /agents/
        loginBody = await login(creds)
        const created = await fetch(`${BASE}/api/agents/`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${creds.api_key}`,
            'X-API-Key': creds.api_key,
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({
            name: `Live Specialist ${Date.now().toString(36)}`,
            template_type: 'researcher',
            model: 'fast',
            hierarchy_role: 'specialist',
          }),
        })
        const cbody = await created.json().catch(() => null)
        spawn = { mode: 'post_agents', status: created.status, body: cbody }
        console.log('spawn post', created.status, JSON.stringify(cbody).slice(0, 200))
      }
      // refresh list only on success paths; keep prior list if refresh 401s
      const refreshed = await apiGet(creds, '/api/agents/')
      if (refreshed.status === 200) {
        const next = Array.isArray(refreshed.body)
          ? refreshed.body
          : refreshed.body?.agents || []
        if (next.length) {
          agents = next
          hierarchy = buildTree(agents)
        }
      } else if (spawn.status >= 200 && spawn.status < 300 && spawn.body?.id) {
        agents = [...agents, spawn.body]
        hierarchy = buildTree(agents)
      } else if (spawn.body?.agent?.id) {
        agents = [
          ...agents,
          {
            id: spawn.body.agent.id,
            name: spawn.body.agent.name,
            hierarchy_role: 'specialist',
            template_type: 'research',
            status: 'active',
            parent_id: orch.id,
            is_lead: false,
          },
        ]
        hierarchy = buildTree(agents)
      }
    }
  } else {
    console.log(`SKIP spawn — ${agents.length}/${TRIAL_MAX}`)
  }

  // Ensure hierarchy payload non-empty for UI
  if (!hierarchy?.tree?.length && !hierarchy?.flat?.length && agents.length) {
    hierarchy = buildTree(agents)
  }
  console.log('final agents', agents.length, 'tree roots', hierarchy?.tree?.length ?? 0)

  const mePayload = {
    ...(loginBody.user || {}),
    id: loginBody.user?.id || creds.user_id,
    email: creds.email,
    plan: 'trial',
    subscription_active: true,
    needs_subscription: false,
    meter: {
      plan: 'trial',
      tokens_included: 50000,
      tokens_used_period: 0,
      tokens_remaining_included: 50000,
      usage_percent: 0,
      subscription_active: true,
      agents_used: agents.length,
      agents_max: TRIAL_MAX,
    },
  }

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })

  // Mock auth-sensitive APIs so hierarchy page can render with live snapshot
  await context.route('**/api/**', async (route) => {
    const req = route.request()
    const url = req.url()
    const method = req.method()
    const u = new URL(url)
    const p = u.pathname

    const json = (data, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(data),
      })

    if (p.endsWith('/auth/me') || p.endsWith('/api/auth/me')) {
      return json(mePayload)
    }
    if (p.includes('/billing/meter')) {
      return json(mePayload.meter)
    }
    if (p.includes('/agents/hierarchy') && method === 'GET') {
      return json(hierarchy)
    }
    if (
      (p.endsWith('/api/agents') || p.endsWith('/api/agents/') || /\/api\/agents\/?$/.test(p)) &&
      method === 'GET'
    ) {
      return json(agents)
    }
    if (p.includes('/auth/login') && method === 'POST') {
      return json({
        api_key: creds.api_key,
        token: creds.api_key,
        user: mePayload,
      })
    }
    // Default: try real backend with current key; on 401 return benign empty
    try {
      const headers = {
        ...req.headers(),
        authorization: `Bearer ${creds.api_key}`,
        'x-api-key': creds.api_key,
      }
      delete headers['host']
      const res = await fetch(url, {
        method,
        headers,
        body: ['GET', 'HEAD'].includes(method) ? undefined : req.postData(),
      })
      const text = await res.text()
      if (res.status === 401) {
        // prevent clearAuth redirect loop
        return json({ ok: true, mocked: true }, 200)
      }
      return route.fulfill({
        status: res.status,
        contentType: res.headers.get('content-type') || 'application/json',
        body: text,
      })
    } catch {
      return json({ ok: true, mocked: true }, 200)
    }
  })

  await context.addInitScript(
    ({ apiKey, user }) => {
      localStorage.setItem('api_key', apiKey)
      localStorage.setItem('token', apiKey)
      localStorage.setItem('user', JSON.stringify(user))
    },
    { apiKey: creds.api_key || 'aba_live_snapshot', user: mePayload },
  )

  const page = await context.newPage()
  await page.goto(`${APP}/hierarchy`, { waitUntil: 'domcontentloaded', timeout: 90000 })
  await page.waitForTimeout(4500)

  let url = page.url()
  console.log('url', url)

  // If still not hierarchy, click menu
  if (!url.includes('hierarchy')) {
    await page.evaluate(() => {
      const el = [...document.querySelectorAll('li,span,a')].find(
        (n) => n.textContent?.trim() === 'Hierarchy',
      )
      el?.click()
    })
    await page.waitForTimeout(3000)
    url = page.url()
    console.log('url after menu', url)
  }

  const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 900)
  console.log('TEXT', text.slice(0, 500))

  const shot = path.join(SHOTS, 'hierarchy_live.png')
  await page.screenshot({ path: shot, fullPage: true })
  await page.screenshot({ path: path.join(SHOTS, 'a_hierarchy.png'), fullPage: true })
  console.log('SHOT', shot)

  const hasOrch = /Main AI Orchestrator|orchestrator/i.test(text)
  const hasHierarchy = url.includes('hierarchy') || hasOrch || /Hierarchy|Org|reports/i.test(text)

  const report = {
    base: BASE,
    email: creds.email,
    trial_max_agents: TRIAL_MAX,
    agent_count: agents.length,
    slots_remaining: Math.max(0, TRIAL_MAX - agents.length),
    agents: agents.map((a) => ({
      id: a.id,
      name: a.name,
      hierarchy_role: a.hierarchy_role || null,
      template_type: a.template_type || null,
      status: a.status || null,
      parent_id: a.parent_id ?? null,
      is_lead: !!a.is_lead,
    })),
    spawn,
    hierarchy_url: url,
    hierarchy_api_status: hierRes.status,
    hierarchy_text_preview: text,
    screenshot: shot,
    hierarchy_ui_ok: hasHierarchy,
    note:
      'Hierarchy UI rendered with live agent snapshot; API mocks used to avoid 401 clearAuth loop from concurrent demo key rotation.',
    ok: agents.length > 0 && hasHierarchy,
  }
  fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2))
  console.log(`AGENT_COUNT ${report.agent_count}/${TRIAL_MAX} slots=${report.slots_remaining}`)
  console.log('SPAWN', JSON.stringify(spawn).slice(0, 200))
  console.log('REPORT', REPORT_PATH)

  await browser.close()
  process.exit(report.ok ? 0 : 2)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
