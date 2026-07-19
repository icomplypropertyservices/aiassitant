/**
 * Lightweight live browser smoke: login → templates / agents / meetings / chat shell.
 * Uses page-side login so session key stays in-browser (avoids race with file overwrites).
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CREDS = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const REPORT = path.join(__dirname, 'live_smoke_browser_report.json')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`

fs.mkdirSync(SHOTS, { recursive: true })

function loadCreds() {
  return JSON.parse(fs.readFileSync(CREDS, 'utf8'))
}

async function pageLogin(page, creds) {
  return page.evaluate(
    async ({ email, password }) => {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const j = await r.json().catch(() => ({}))
      const key = j.api_key || j.token
      if (!r.ok || !key) {
        return {
          ok: false,
          status: r.status,
          detail: j.detail || j,
          keys: Object.keys(j || {}),
        }
      }
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      localStorage.setItem('user', JSON.stringify(j.user || { email, plan: 'trial', subscription_active: true }))
      return {
        ok: true,
        status: r.status,
        user_id: j.user?.id,
        plan: j.user?.plan,
        subscription_active: j.user?.subscription_active,
        needs_subscription: j.user?.needs_subscription,
        key_prefix: key.slice(0, 16),
      }
    },
    { email: creds.email, password: creds.password },
  )
}

async function main() {
  const creds = loadCreds()
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  const results = []

  const pass = (name, detail = '') => {
    results.push({ name, pass: true, detail })
    console.log(`PASS  ${name}${detail ? ' — ' + detail : ''}`)
  }
  const fail = (name, detail = '') => {
    results.push({ name, pass: false, detail: String(detail) })
    console.log(`FAIL  ${name} — ${detail}`)
  }
  const shot = async (name) => {
    const p = path.join(SHOTS, `smoke_${name}.png`)
    await page.screenshot({ path: p, fullPage: true }).catch(() => {})
    return p
  }

  try {
    // commit is more reliable than networkidle on heavy SPAs
    await page.goto(`${APP}/login`, { waitUntil: 'commit', timeout: 120000 })
    await page.waitForTimeout(2000)
    await shot('login')

    let login = await pageLogin(page, creds)
    if (!login.ok && login.status === 429) {
      console.warn('Login 429 — waiting 25s and retrying once')
      await page.waitForTimeout(25000)
      login = await pageLogin(page, creds)
    }
    if (!login.ok) {
      fail('browser_login', JSON.stringify(login).slice(0, 300))
      await shot('login_fail')
    } else {
      pass(
        'browser_login',
        `user=${login.user_id} plan=${login.plan} sub=${login.subscription_active}`,
      )
      // Persist key for API tools (best-effort)
      try {
        const key = await page.evaluate(() => localStorage.getItem('api_key'))
        if (key) {
          creds.api_key = key
          if (login.user_id != null) creds.user_id = login.user_id
          fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
          fs.writeFileSync(path.join(__dirname, '.demo_token'), key)
        }
      } catch {
        /* ignore */
      }
    }

    const routes = [
      ['dashboard', `${APP}/`],
      ['templates', `${APP}/templates`],
      ['agents', `${APP}/agents`],
      ['meetings', `${APP}/meetings`],
      ['chat', `${APP}/agents/${creds.agent_id || ''}`],
    ]

    for (const [name, url] of routes) {
      try {
        // Re-login before each route if key was rotated by other workers
        const meOk = await page.evaluate(async () => {
          const key = localStorage.getItem('api_key') || localStorage.getItem('token')
          if (!key) return false
          const r = await fetch('/api/auth/me', {
            headers: {
              Authorization: `Bearer ${key}`,
              'X-API-Key': key,
              Accept: 'application/json',
            },
          })
          return r.ok
        })
        if (!meOk) {
          const again = await pageLogin(page, creds)
          if (!again.ok) {
            fail(name, `re-login failed: ${JSON.stringify(again).slice(0, 200)}`)
            await shot(`${name}_relogin_fail`)
            continue
          }
        }

        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
        await page.waitForTimeout(2800)

        // One recovery if 401 bounce cleared storage
        if (page.url().includes('/login')) {
          const again = await pageLogin(page, creds)
          if (again.ok) {
            await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
            await page.waitForTimeout(2800)
          }
        }

        await shot(name)
        const body = await page.locator('body').innerText().catch(() => '')
        const cards = await page.locator('.ant-card, .aba-page-shell, .aba-page-center, .aba-box').count()
        const fatal = /TypeError|Cannot read prop|Unexpected Application Error|Something went wrong/i.test(
          body,
        )
        const onLogin = page.url().includes('/login')
        if (onLogin) {
          fail(name, `redirected to login; cards=${cards}`)
        } else if (fatal) {
          fail(name, `fatal UI error; cards=${cards}`)
        } else {
          pass(name, `url=${page.url()} cards=${cards} text_len=${body.length}`)
        }
      } catch (e) {
        fail(name, e.message)
        await shot(`${name}_err`)
      }
    }
  } catch (e) {
    fail('fatal', e.message)
    await shot('fatal')
  }

  await browser.close()
  const report = {
    at: new Date().toISOString(),
    base: BASE,
    email: creds.email,
    results,
    passed: results.filter((r) => r.pass).length,
    failed: results.filter((r) => !r.pass).length,
  }
  fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ passed: report.passed, failed: report.failed }, null, 2))
  console.log(`Wrote ${REPORT}`)
  process.exit(report.failed ? 1 : 0)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
