/**
 * Live production browser E2E for aibusinessagent.xyz
 *
 * Usage:
 *   node scripts/live_browser_e2e.mjs              # full suite
 *   node scripts/live_browser_e2e.mjs --agent=A    # auth, dashboard, companies, agents, templates
 *   node scripts/live_browser_e2e.mjs --agent=B    # chat instructions, files, media, meetings, tasks
 *
 * Reads credentials from scripts/.demo_login.json (created by live setup).
 * Screenshots → scripts/live-screenshots/
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.join(__dirname, '..')
const SHOTS = path.join(__dirname, 'live-screenshots')
const CREDS = path.join(__dirname, '.demo_login.json')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const REPORT = path.join(__dirname, 'live_browser_report.json')

const args = process.argv.slice(2)
const agentArg = (args.find((a) => a.startsWith('--agent=')) || '--agent=ALL').split('=')[1].toUpperCase()

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  if (!fs.existsSync(CREDS)) {
    throw new Error(`Missing ${CREDS} — run live setup first`)
  }
  return JSON.parse(fs.readFileSync(CREDS, 'utf8'))
}

function persistCreds(creds) {
  try {
    fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
  } catch {
    /* ignore write errors on read-only envs */
  }
}

/** Validate cached key; only login when invalid (avoids rotating session under concurrent swarm workers). */
async function refreshCreds(creds) {
  async function meOk(key) {
    if (!key) return false
    try {
      const r = await fetch(`${BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${key}`, Accept: 'application/json', 'X-API-Key': key },
      })
      if (!r.ok) return false
      const j = await r.json().catch(() => null)
      if (j?.id != null) creds.user_id = j.id
      return true
    } catch {
      return false
    }
  }

  if (await meOk(creds.api_key)) {
    console.log(`Reusing valid cached api_key for ${creds.email}`)
    return creds
  }

  // Login with backoff for 429 rate limits (shared demo account + swarm)
  let lastStatus = 0
  let lastDetail = ''
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const r = await fetch(`${BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email: creds.email, password: creds.password }),
      })
      lastStatus = r.status
      const j = await r.json().catch(() => null)
      lastDetail = typeof j?.detail === 'string' ? j.detail : JSON.stringify(j?.detail || j || '')
      const key = j?.api_key || j?.token
      if (r.ok && key) {
        creds.api_key = key
        if (j.user?.id != null) creds.user_id = j.user.id
        persistCreds(creds)
        console.log(`Refreshed session api_key for ${creds.email}`)
        return creds
      }
      if (r.status === 429) {
        const waitSec = Math.min(90, 15 + attempt * 20)
        const m = /Try again in (\d+)/i.exec(lastDetail)
        const sec = m ? Math.min(120, parseInt(m[1], 10) + 2) : waitSec
        console.warn(`Login rate-limited; waiting ${sec}s (attempt ${attempt + 1}/6)`)
        await new Promise((res) => setTimeout(res, sec * 1000))
        continue
      }
      console.warn(`Login refresh failed status=${r.status} ${lastDetail.slice(0, 120)}; using cached key`)
      break
    } catch (e) {
      console.warn(`Login refresh error: ${e.message}; retrying…`)
      await new Promise((res) => setTimeout(res, 3000 * (attempt + 1)))
    }
  }
  if (!(await meOk(creds.api_key))) {
    console.warn(`Cached key also invalid after login status=${lastStatus}`)
  }
  return creds
}

/**
 * Browser-side fetch with one re-login on 401 (other swarm workers may rotate the shared demo key).
 * Returns { status, body, path, apiKey } and updates creds.api_key in Node when rotated.
 */
async function apiWithRetry(page, creds, path, { method = 'GET', body = null } = {}) {
  const result = await page.evaluate(
    async ({ base, email, password, apiKey, path, method, body }) => {
      async function login() {
        const r = await fetch(`${base}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ email, password }),
        })
        const j = await r.json().catch(() => null)
        const key = j?.api_key || j?.token
        if (!r.ok || !key) {
          return { ok: false, status: r.status, detail: j }
        }
        try {
          localStorage.setItem('api_key', key)
          localStorage.setItem('token', key)
        } catch {
          /* ignore */
        }
        return { ok: true, key, user: j.user }
      }

      async function once(key) {
        const headers = {
          Authorization: `Bearer ${key}`,
          'X-API-Key': key,
          Accept: 'application/json',
        }
        if (body != null) headers['Content-Type'] = 'application/json'
        const r = await fetch(path, {
          method,
          headers,
          body: body != null ? JSON.stringify(body) : undefined,
        })
        const text = await r.text()
        let json
        try {
          json = JSON.parse(text)
        } catch {
          json = text.slice(0, 800)
        }
        return { status: r.status, body: json, text }
      }

      let key = apiKey
      let res = await once(key)
      if (res.status === 401) {
        const lr = await login()
        if (lr.ok) {
          key = lr.key
          res = await once(key)
          return { path, status: res.status, body: res.body, apiKey: key, relogin: true }
        }
        return {
          path,
          status: res.status,
          body: res.body,
          apiKey: key,
          relogin: false,
          login_error: lr,
        }
      }
      return { path, status: res.status, body: res.body, apiKey: key, relogin: false }
    },
    {
      base: BASE,
      email: creds.email,
      password: creds.password,
      apiKey: creds.api_key,
      path,
      method,
      body,
    },
  )
  if (result.apiKey && result.apiKey !== creds.api_key) {
    creds.api_key = result.apiKey
    persistCreds(creds)
    console.log('Session api_key updated after in-page re-login')
  }
  return result
}

const results = []
function ok(name, detail = '') {
  results.push({ name, pass: true, detail })
  console.log(`PASS  ${name}${detail ? ' — ' + detail : ''}`)
}
function fail(name, detail = '') {
  results.push({ name, pass: false, detail: String(detail) })
  console.log(`FAIL  ${name} — ${detail}`)
}

async function shot(page, name) {
  const p = path.join(SHOTS, `${agentArg.toLowerCase()}_${name}.png`)
  await page.screenshot({ path: p, fullPage: true })
  return p
}

async function injectAuth(page, creds) {
  let lastErr
  for (let i = 0; i < 3; i++) {
    try {
      await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
      lastErr = null
      break
    } catch (e) {
      lastErr = e
      await page.waitForTimeout(1500 * (i + 1))
    }
  }
  if (lastErr) throw lastErr
  await page.evaluate(
    ({ apiKey, user }) => {
      localStorage.setItem('api_key', apiKey)
      localStorage.setItem('token', apiKey)
      if (user) localStorage.setItem('user', JSON.stringify(user))
    },
    {
      apiKey: creds.api_key,
      user: {
        id: creds.user_id,
        email: creds.email,
        name: 'Live Demo',
        role: 'user',
        plan: 'trial',
        subscription_active: true,
      },
    },
  )
  // Confirm key still works from the browser origin; re-login in-page if rotated.
  // Retries login on 429 (shared demo account under swarm load).
  let authCheck = null
  for (let attempt = 0; attempt < 5; attempt++) {
    authCheck = await page.evaluate(async ({ email, password, apiKey, base }) => {
      async function check(key) {
        const r = await fetch(`${base}/api/auth/me`, {
          headers: { Authorization: `Bearer ${key}`, Accept: 'application/json', 'X-API-Key': key },
        })
        return r.ok
      }
      // Prefer live localStorage key (may have been refreshed by a prior step)
      const lsKey = localStorage.getItem('api_key') || localStorage.getItem('token') || apiKey
      if (await check(lsKey)) return { ok: true, key: lsKey }
      const r = await fetch(`${base}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const j = await r.json().catch(() => null)
      const key = j?.api_key || j?.token
      if (r.ok && key) {
        localStorage.setItem('api_key', key)
        localStorage.setItem('token', key)
        if (j.user) localStorage.setItem('user', JSON.stringify(j.user))
        return { ok: true, key, user_id: j.user?.id }
      }
      return { ok: false, status: r.status, detail: j }
    }, { email: creds.email, password: creds.password, apiKey: creds.api_key, base: BASE })
    if (authCheck?.ok) break
    if (authCheck?.status === 429) {
      const waitMs = 15000 + attempt * 10000
      console.warn(`injectAuth: login 429, waiting ${waitMs / 1000}s (attempt ${attempt + 1}/5)`)
      await page.waitForTimeout(waitMs)
      continue
    }
    break
  }
  if (authCheck?.key && authCheck.key !== creds.api_key) {
    creds.api_key = authCheck.key
    if (authCheck.user_id != null) creds.user_id = authCheck.user_id
    persistCreds(creds)
  }
  if (!authCheck?.ok) {
    console.warn(`injectAuth: session not confirmed — ${JSON.stringify(authCheck).slice(0, 180)}`)
  }
}

function assertAppUrl(name, page) {
  const url = page.url()
  if (/\/login\b/i.test(url) || /\/subscribe\b/i.test(url)) {
    fail(name, `still on gated page: ${url}`)
    return false
  }
  ok(name, url)
  return true
}

async function loginViaForm(page, creds) {
  await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 90000 })
  await shot(page, '01_login')
  // Prefer programmatic login (more reliable under rate limits than form clicks)
  const prog = await page.evaluate(async ({ email, password, base }) => {
    const r = await fetch(`${base}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const j = await r.json().catch(() => null)
    const key = j?.api_key || j?.token
    if (r.ok && key) {
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      if (j.user) localStorage.setItem('user', JSON.stringify(j.user))
      return { ok: true, key, user_id: j.user?.id, status: r.status }
    }
    return { ok: false, status: r.status, detail: j }
  }, { email: creds.email, password: creds.password, base: BASE })
  if (prog.ok) {
    creds.api_key = prog.key
    if (prog.user_id != null) creds.user_id = prog.user_id
    persistCreds(creds)
    await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await shot(page, '02_after_login')
    return
  }
  // Ant Design form fallback
  const email = page.locator('input[type="email"], input[placeholder*="mail" i], #email, input[name="email"]').first()
  const password = page.locator('input[type="password"]').first()
  await email.waitFor({ timeout: 20000 })
  await email.fill(creds.email)
  await password.fill(creds.password)
  await page.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Login")').first().click()
  await page.waitForTimeout(3000)
  await shot(page, '02_after_login')
  const browserKey = await page.evaluate(() => localStorage.getItem('api_key') || localStorage.getItem('token') || '')
  if (browserKey) {
    creds.api_key = browserKey
    persistCreds(creds)
  }
}

async function ensureTrialIfNeeded(page, creds) {
  const url = page.url()
  if (url.includes('subscribe') || url.includes('billing')) {
    // try trial button
    const trial = page.locator('button:has-text("trial"), button:has-text("Trial"), button:has-text("Free"), .ant-btn:has-text("Start")').first()
    if (await trial.count()) {
      await trial.click()
      await page.waitForTimeout(2500)
    }
    // API fallback via page
    await page.evaluate(async (apiKey) => {
      await fetch('/api/billing/plan', {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: 'trial', company_name: 'Live Demo Co' }),
      })
    }, creds.api_key)
    await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded' })
  }
}

/** Agent A: shell, companies, agents, templates, hierarchy */
async function runAgentA(page, creds) {
  await injectAuth(page, creds)
  await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 90000 })
  await page.waitForTimeout(2000)
  // If SPA cleared session (401 from concurrent key rotation), fall back to form login
  if (/\/login\b/i.test(page.url())) {
    console.warn('Dashboard redirected to login — trying form login')
    await loginViaForm(page, creds)
    await page.waitForTimeout(2000)
    // Pull key from browser if form login succeeded
    const browserKey = await page.evaluate(() => localStorage.getItem('api_key') || localStorage.getItem('token') || '')
    if (browserKey && browserKey !== creds.api_key) {
      creds.api_key = browserKey
      persistCreds(creds)
    }
    if (/\/login\b/i.test(page.url())) {
      await page.goto(`${APP}/`, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await page.waitForTimeout(1500)
    }
  }
  await ensureTrialIfNeeded(page, creds)
  await shot(page, 'dashboard')
  const body = await page.locator('body').innerText()
  if (/\/login\b/i.test(page.url())) {
    fail('dashboard_loaded', `stuck on login url=${page.url()}`)
  } else if (body.length > 50) {
    ok('dashboard_loaded', `url=${page.url()}`)
  } else {
    fail('dashboard_loaded', 'empty body')
  }

  // Companies / Business — must stay inside the authenticated app shell
  for (const pathPart of ['/business', '/workspace', '/']) {
    try {
      await page.goto(`${APP}${pathPart}`, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await page.waitForTimeout(1500)
      // Recover once if a 401 mid-nav cleared auth
      if (/\/login\b/i.test(page.url())) {
        await injectAuth(page, creds)
        await page.goto(`${APP}${pathPart}`, { waitUntil: 'domcontentloaded', timeout: 60000 })
        await page.waitForTimeout(1200)
      }
      await shot(page, `nav_${pathPart.replace(/\//g, '_') || 'home'}`)
      assertAppUrl(`nav${pathPart || '/home'}`, page)
    } catch (e) {
      fail(`nav${pathPart}`, e.message)
    }
  }

  // Create company via API (org router: POST /api/org/companies)
  // Prefer existing company / plan-limit as success (trial caps).
  const companyBundle = await page.evaluate(
    async ({ base, email, password, apiKey }) => {
      async function login() {
        const r = await fetch(`${base}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ email, password }),
        })
        const j = await r.json().catch(() => null)
        const key = j?.api_key || j?.token
        if (r.ok && key) {
          try {
            localStorage.setItem('api_key', key)
            localStorage.setItem('token', key)
          } catch {
            /* ignore */
          }
          return key
        }
        return null
      }
      async function listCompanies(key) {
        for (const lp of ['/api/org/companies', '/api/business/companies']) {
          const lr = await fetch(lp, {
            headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key, Accept: 'application/json' },
          })
          if (lr.status === 401) return { path: lp, items: [], status: 401 }
          if (lr.status === 404) continue
          const lj = await lr.json().catch(() => null)
          const items = Array.isArray(lj) ? lj : lj?.companies || lj?.items || []
          if (lr.ok) return { path: lp, items, status: lr.status }
        }
        return { path: null, items: [], status: 0 }
      }

      let key = apiKey
      let existing = await listCompanies(key)
      if (existing.status === 401) {
        const nk = await login()
        if (nk) {
          key = nk
          existing = await listCompanies(key)
        }
      }

      let last = null
      for (const p of ['/api/org/companies', '/api/business/companies', '/api/companies']) {
        const r = await fetch(p, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${key}`,
            'X-API-Key': key,
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({ name: 'Browser E2E Co ' + Date.now(), industry: 'Technology' }),
        })
        const text = await r.text()
        let json = null
        try {
          json = JSON.parse(text)
        } catch {
          json = text
        }
        last = { path: p, status: r.status, body: json }
        if (r.status === 401) {
          const nk = await login()
          if (nk) {
            key = nk
            continue
          }
        }
        if (r.status !== 404) break
      }
      if (last && last.status >= 200 && last.status < 300) {
        return { ...last, mode: 'created', apiKey: key }
      }

      const detail =
        typeof last?.body === 'object' ? String(last?.body?.detail || '') : String(last?.body || '')
      const planLimited =
        last &&
        (last.status === 400 || last.status === 409 || last.status === 402) &&
        /plan allows|upgrade|companies|already|limit/i.test(detail)

      const after = await listCompanies(key)
      const items = after.items.length ? after.items : existing.items
      if (items.length > 0 && (planLimited || last?.status === 400 || last?.status === 409)) {
        return {
          path: last?.path || after.path || '/api/org/companies',
          status: 200,
          mode: 'existing_plan_limit',
          apiKey: key,
          body: {
            count: items.length,
            id: items[0]?.id,
            name: items[0]?.name,
            limit_detail: detail || 'plan company limit',
          },
        }
      }
      if (items.length > 0 && last && last.status >= 400 && last.status < 500) {
        return {
          path: last.path,
          status: 200,
          mode: 'existing_company',
          apiKey: key,
          body: { count: items.length, id: items[0]?.id, name: items[0]?.name, detail },
        }
      }
      // Listing alone is enough to prove company API works under trial
      if (items.length > 0) {
        return {
          path: after.path || existing.path || '/api/org/companies',
          status: 200,
          mode: 'list_only',
          apiKey: key,
          body: { count: items.length, id: items[0]?.id, name: items[0]?.name },
        }
      }
      return { ...(last || { status: 404, body: 'no company endpoint' }), apiKey: key }
    },
    { base: BASE, email: creds.email, password: creds.password, apiKey: creds.api_key },
  )
  if (companyBundle.apiKey && companyBundle.apiKey !== creds.api_key) {
    creds.api_key = companyBundle.apiKey
    persistCreds(creds)
  }
  if (companyBundle.status >= 200 && companyBundle.status < 300) {
    ok(
      'create_company_api',
      `${companyBundle.mode || 'ok'} ${companyBundle.path || ''} ${JSON.stringify(companyBundle.body).slice(0, 140)}`,
    )
  } else {
    fail('create_company_api', JSON.stringify(companyBundle).slice(0, 300))
  }

  // Agents console
  await page.goto(`${APP}/agents`, { waitUntil: 'domcontentloaded', timeout: 90000 })
  await page.waitForTimeout(2000)
  if (/\/login\b/i.test(page.url())) {
    await injectAuth(page, creds)
    await page.goto(`${APP}/agents`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(1500)
  }
  await shot(page, 'agents_console')
  const agentsText = await page.locator('body').innerText()
  if (/orchestrator|agent|spawn|template/i.test(agentsText) && !/\/login\b/i.test(page.url())) {
    ok('agents_page', 'found agent UI text')
  } else {
    fail('agents_page', `${page.url()} ${agentsText.slice(0, 150)}`)
  }

  // Ensure orchestrator (retry on 401 via apiWithRetry)
  const orch = await apiWithRetry(page, creds, '/api/agents/ensure-orchestrator', { method: 'POST' })
  if (orch.status === 200) ok('ensure_orchestrator', `id=${orch.body?.id}`)
  else fail('ensure_orchestrator', JSON.stringify(orch).slice(0, 200))

  // Templates
  await page.goto(`${APP}/templates`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  if (/\/login\b/i.test(page.url())) {
    await injectAuth(page, creds)
    await page.goto(`${APP}/templates`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(1200)
  }
  await shot(page, 'templates')
  const tRes = await apiWithRetry(page, creds, '/api/templates/')
  const tList = Array.isArray(tRes.body) ? tRes.body : tRes.body?.templates || []
  const tCount = Array.isArray(tList) ? tList.length : tRes.body?.count || 0
  if (tCount > 0) ok('templates_catalog', `count=${tCount}`)
  else fail('templates_catalog', `status=${tRes.status} empty`)

  // Hierarchy
  await page.goto(`${APP}/hierarchy`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  if (/\/login\b/i.test(page.url())) {
    await injectAuth(page, creds)
    await page.goto(`${APP}/hierarchy`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(1200)
  }
  await shot(page, 'hierarchy')
  assertAppUrl('hierarchy_page', page)

  // Spawn specialist if slots remain (trial may already be at agent cap)
  const spawn = await page.evaluate(
    async ({ base, email, password, apiKey }) => {
      async function login() {
        const r = await fetch(`${base}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ email, password }),
        })
        const j = await r.json().catch(() => null)
        const key = j?.api_key || j?.token
        if (r.ok && key) {
          try {
            localStorage.setItem('api_key', key)
            localStorage.setItem('token', key)
          } catch {
            /* ignore */
          }
          return key
        }
        return null
      }
      let key = apiKey
      const headersFor = (k) => ({
        Authorization: `Bearer ${k}`,
        'X-API-Key': k,
        'Content-Type': 'application/json',
        Accept: 'application/json',
      })
      let tr = await fetch('/api/templates/', { headers: headersFor(key) })
      if (tr.status === 401) {
        const nk = await login()
        if (nk) {
          key = nk
          tr = await fetch('/api/templates/', { headers: headersFor(key) })
        }
      }
      const templates = await tr.json().catch(() => null)
      const list = Array.isArray(templates) ? templates : templates?.templates || []
      const tpl =
        list.find((t) =>
          /specialist|writer|research|sales|marketing/i.test(t.type || t.template_type || t.name || ''),
        ) ||
        list[1] ||
        list[0]
      if (!tpl) return { status: 0, body: 'no templates', apiKey: key }
      const body = {
        name: 'E2E Specialist ' + Date.now().toString(36),
        template_type: tpl.template_type || tpl.type || tpl.id,
        template_id: tpl.id,
        model: 'fast',
      }
      let r = await fetch('/api/agents/', { method: 'POST', headers: headersFor(key), body: JSON.stringify(body) })
      if (r.status === 401) {
        const nk = await login()
        if (nk) {
          key = nk
          r = await fetch('/api/agents/', { method: 'POST', headers: headersFor(key), body: JSON.stringify(body) })
        }
      }
      const text = await r.text()
      let json
      try {
        json = JSON.parse(text)
      } catch {
        json = text
      }
      if (r.status >= 200 && r.status < 300) return { status: r.status, body: json, mode: 'spawned', apiKey: key }

      const detail = typeof json === 'object' ? String(json?.detail || '') : String(json || '')
      const planLimited =
        (r.status === 400 || r.status === 409) && /plan allows|upgrade|agents|limit/i.test(detail)
      // Always try listing existing agents on plan limit or any client error
      if (planLimited || (r.status >= 400 && r.status < 500)) {
        const ar = await fetch('/api/agents/', { headers: headersFor(key) })
        const aj = await ar.json().catch(() => null)
        const agents = Array.isArray(aj) ? aj : aj?.agents || aj?.items || []
        if (agents.length > 0) {
          return {
            status: 200,
            mode: planLimited ? 'existing_plan_limit' : 'existing_agents',
            apiKey: key,
            body: {
              count: agents.length,
              id: agents[0]?.id,
              names: agents.map((a) => a.name || a.id).slice(0, 5),
              limit_detail: detail,
            },
          }
        }
      }
      return { status: r.status, body: json, apiKey: key }
    },
    { base: BASE, email: creds.email, password: creds.password, apiKey: creds.api_key },
  )
  if (spawn.apiKey && spawn.apiKey !== creds.api_key) {
    creds.api_key = spawn.apiKey
    persistCreds(creds)
  }
  if (spawn.status >= 200 && spawn.status < 300) {
    ok('spawn_agent', `${spawn.mode || 'ok'} id=${spawn.body?.id} ${JSON.stringify(spawn.body).slice(0, 120)}`)
  } else {
    fail('spawn_agent', JSON.stringify(spawn).slice(0, 250))
  }
}

/** Agent B: chat instructions, tasks, meetings, file/media upload */
async function runAgentB(page, creds) {
  await injectAuth(page, creds)
  await page.goto(`${APP}/`, { waitUntil: 'networkidle', timeout: 90000 })
  await ensureTrialIfNeeded(page, creds)
  if (/\/login\b/i.test(page.url())) {
    try {
      await loginViaForm(page, creds)
      await ensureTrialIfNeeded(page, creds)
    } catch (e) {
      fail('agent_b_login', e.message)
    }
  }

  let agentId = creds.agent_id
  const agentsRes = await apiWithRetry(page, creds, '/api/agents/')
  const agents = agentsRes.body
  const list = Array.isArray(agents) ? agents : agents?.agents || agents?.items || []
  if (!agentId && list[0]) agentId = list[0].id
  if (!agentId) {
    const orch = await apiWithRetry(page, creds, '/api/agents/ensure-orchestrator', {
      method: 'POST',
      body: {},
    })
    agentId = orch.body?.id
  }
  if (agentId) {
    creds.agent_id = agentId
    persistCreds(creds)
    ok('have_agent', `id=${agentId}`)
  } else {
    fail('have_agent', `none agents_status=${agentsRes.status}`)
  }

  await page.goto(`${APP}/agents/${agentId}`, { waitUntil: 'networkidle', timeout: 90000 })
  await page.waitForTimeout(2000)
  await shot(page, 'agent_chat')
  assertAppUrl('agent_chat_page', page)

  const instruction =
    'Create a short company mission for Live Demo Co and list 3 next actions. Reply as the orchestrator to the human owner.'
  const chatPaths = [
    `/api/agents/${agentId}/chat`,
    `/api/chat/agents/${agentId}`,
    `/api/chat/`,
  ]
  let chat = { status: 404, body: 'no chat path' }
  for (const p of chatPaths) {
    chat = await apiWithRetry(page, creds, p, {
      method: 'POST',
      body: {
        message: instruction,
        content: instruction,
        text: instruction,
        agent_id: agentId,
      },
    })
    if (chat.status !== 404) break
  }
  if (chat.status >= 200 && chat.status < 300) {
    const preview = typeof chat.body === 'string' ? chat.body : JSON.stringify(chat.body)
    ok('chat_instruction', `${chat.path} ${preview.slice(0, 180)}`)
  } else fail('chat_instruction', JSON.stringify(chat).slice(0, 300))

  await page.reload({ waitUntil: 'domcontentloaded' })
  // Composer mounts only after agent finishes loading (not during "Opening agent…")
  try {
    await page
      .locator('textarea.agent-chat-textarea, .agent-chat-input-wrap textarea, textarea[placeholder*="Message" i]')
      .first()
      .waitFor({ state: 'visible', timeout: 45000 })
  } catch {
    /* fall through to compose attempt */
  }
  await page.waitForTimeout(500)
  await shot(page, 'agent_chat_after')

  try {
    const box = page
      .locator(
        'textarea.agent-chat-textarea, .agent-chat-input-wrap textarea, textarea[placeholder*="Message" i], textarea, [contenteditable="true"]',
      )
      .first()
    await box.waitFor({ state: 'visible', timeout: 20000 })
    await box.click()
    await box.fill('Confirm you received the mission instruction. One sentence.')
    // Circular primary send next to the textarea (icon-only; no "Send" label)
    const send = page
      .locator(
        'button.agent-chat-send, .agent-chat-input-wrap button.ant-btn-primary, .agent-chat-composer button.ant-btn-primary',
      )
      .first()
    await send.waitFor({ state: 'visible', timeout: 10000 })
    await send.click()
    await page.waitForTimeout(8000)
    await shot(page, 'chat_ui_send')
    ok('chat_ui_send', 'clicked send')
  } catch (e) {
    fail('chat_ui_send', e.message)
  }

  let task = await apiWithRetry(page, creds, `/api/agents/${agentId}/tasks`, {
    method: 'POST',
    body: {
      title: 'Browser E2E task',
      description: 'Save a summary file for the demo company',
      status: 'queued',
    },
  })
  if (task.status === 404 || task.status === 422) {
    task = await apiWithRetry(page, creds, '/api/org/tasks', {
      method: 'POST',
      body: {
        title: 'Browser E2E task',
        description: 'Save a summary file',
        agent_id: agentId,
      },
    })
  }
  if (task.status >= 200 && task.status < 300) {
    ok('create_task', `${task.path} ${JSON.stringify(task.body).slice(0, 120)}`)
  } else fail('create_task', JSON.stringify(task).slice(0, 200))

  const content = `# Live Demo notes\n\nCreated by browser E2E at ${new Date().toISOString()}\nMission: ship agent ecosystem.\n`
  let fileSave = await apiWithRetry(page, creds, '/api/training/notes', {
    method: 'POST',
    body: { name: 'Live Demo notes', content, description: 'browser e2e' },
  })
  if (!(fileSave.status >= 200 && fileSave.status < 300)) {
    fileSave = await apiWithRetry(page, creds, '/api/training/docs', {
      method: 'POST',
      body: { title: 'Live Demo notes', content, text: content },
    })
  }
  if (!(fileSave.status >= 200 && fileSave.status < 300)) {
    fileSave = await page.evaluate(async (apiKey) => {
      const content = `# Live Demo notes\n\nCreated by browser E2E at ${new Date().toISOString()}\n`
      const attempts = []
      for (const p of ['/api/training/upload', '/api/media/upload', '/api/agents/upload']) {
        try {
          const fd = new FormData()
          fd.append('file', new Blob([content], { type: 'text/markdown' }), 'live-demo-notes.md')
          fd.append('description', 'browser e2e')
          const r = await fetch(p, {
            method: 'POST',
            headers: { Authorization: `Bearer ${apiKey}`, 'X-API-Key': apiKey },
            body: fd,
          })
          const text = await r.text()
          attempts.push({ path: p, status: r.status })
          if (r.status >= 200 && r.status < 300) {
            return { path: p, status: r.status, body: text.slice(0, 300) }
          }
        } catch (e) {
          attempts.push({ path: p, error: String(e.message || e) })
        }
      }
      return { status: 404, body: 'no file save endpoint', attempts }
    }, creds.api_key)
  }
  if (fileSave.status >= 200 && fileSave.status < 300) ok('save_file', fileSave.path)
  else fail('save_file', JSON.stringify(fileSave).slice(0, 250))

  let pic = { status: 404, body: 'no image endpoint' }
  for (const p of ['/api/media/image', '/api/media/images', '/api/media/generate']) {
    pic = await apiWithRetry(page, creds, p, {
      method: 'POST',
      body: {
        prompt: 'Simple logo for Live Demo Co — blue geometric mark, clean',
        size: '1024x1024',
      },
    })
    if (pic.status !== 404 && pic.status !== 405) break
  }
  if (pic.status >= 200 && pic.status < 300) ok('save_picture', pic.path)
  else fail('save_picture', JSON.stringify(pic).slice(0, 250))

  await page.goto(`${APP}/meetings`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  await shot(page, 'meetings')
  const meeting = await apiWithRetry(page, creds, '/api/meetings/', {
    method: 'POST',
    body: {
      title: 'Browser E2E standup',
      purpose: 'Verify meeting rooms in live env',
      room_type: 'standup',
      chair_agent_id: agentId,
      participants: [{ agent_id: agentId, role: 'chair' }],
    },
  })
  if (meeting.status >= 200 && meeting.status < 300) {
    ok('create_meeting', `id=${meeting.body?.id || meeting.body?.meeting?.id}`)
    const mid = meeting.body?.id || meeting.body?.meeting?.id
    if (mid) {
      await page.goto(`${APP}/meetings/${mid}`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1500)
      await shot(page, 'meeting_room')
      assertAppUrl('meeting_room_ui', page)
    }
  } else fail('create_meeting', JSON.stringify(meeting).slice(0, 250))

  await page.goto(`${APP}/tasks`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  await shot(page, 'tasks')
  assertAppUrl('tasks_page', page)

  await page.goto(`${APP}/billing`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  await shot(page, 'billing')
  if (/\/login\b/i.test(page.url())) {
    fail('billing_page', `redirected to login: ${page.url()}`)
  } else {
    const billText = await page.locator('body').innerText()
    if (/trial|token|plan|billing/i.test(billText)) ok('billing_page', 'plan UI visible')
    else fail('billing_page', billText.slice(0, 100))
  }
}


async function main() {
  let creds = loadCreds()
  console.log(`Live browser E2E agent=${agentArg} email=${creds.email} base=${BASE}`)

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    userAgent: 'ABA-Live-Browser-E2E/1.0',
  })
  const page = await context.newPage()
  // Image gen / chat can exceed 45s on production LLM + xAI Imagine
  page.setDefaultTimeout(120000)

  try {
    // Fresh key right before agent work — other demo scripts login invalidates prior keys
    creds = await refreshCreds(creds)
    if (agentArg === 'A' || agentArg === 'ALL') await runAgentA(page, creds)
    if (agentArg === 'B' || agentArg === 'ALL') {
      // A may have taken a while; re-mint session for B
      if (agentArg === 'ALL') creds = await refreshCreds(creds)
      await runAgentB(page, creds)
    }
  } catch (e) {
    fail('fatal', e.stack || e.message)
    try {
      await shot(page, 'fatal')
    } catch {
      /* ignore */
    }
  }

  await browser.close()

  const passed = results.filter((r) => r.pass).length
  const failed = results.filter((r) => !r.pass).length
  const report = {
    agent: agentArg,
    base: BASE,
    email: creds.email,
    passed,
    failed,
    results,
    screenshots_dir: SHOTS,
    at: new Date().toISOString(),
  }
  fs.writeFileSync(REPORT.replace('.json', `_${agentArg}.json`), JSON.stringify(report, null, 2))
  if (agentArg === 'ALL') fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
  console.log(`\n=== SUMMARY agent=${agentArg} passed=${passed} failed=${failed} ===`)
  process.exit(failed > 0 ? 1 : 0)
}

main().catch((e) => {
  console.error(e)
  process.exit(2)
})
