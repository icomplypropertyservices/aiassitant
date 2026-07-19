/**
 * Screenshot tasks board after B04 goal chain → live-screenshots/b04_goal.png
 * Mirrors injectAuth pattern from live_browser_e2e.mjs
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CREDS = path.join(__dirname, '.demo_login.json')
const REPORT = path.join(__dirname, 'live_b04_goal_report.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const OUT = path.join(SHOTS, 'b04_goal.png')

fs.mkdirSync(SHOTS, { recursive: true })

function persistCreds(creds) {
  try {
    fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
  } catch {
    /* ignore */
  }
}

async function injectAuth(page, creds) {
  await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
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

  let authCheck = null
  for (let attempt = 0; attempt < 6; attempt++) {
    authCheck = await page.evaluate(
      async ({ email, password, apiKey, base }) => {
        async function check(key) {
          const r = await fetch(`${base}/api/auth/me`, {
            headers: {
              Authorization: `Bearer ${key}`,
              Accept: 'application/json',
              'X-API-Key': key,
            },
          })
          return r.ok
        }
        const lsKey =
          localStorage.getItem('api_key') || localStorage.getItem('token') || apiKey
        if (lsKey && (await check(lsKey))) return { ok: true, key: lsKey }
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
      },
      {
        email: creds.email,
        password: creds.password,
        apiKey: creds.api_key,
        base: BASE,
      },
    )
    if (authCheck?.ok) break
    if (authCheck?.status === 429) {
      const waitMs = 18000 + attempt * 10000
      console.warn(`injectAuth 429 wait ${waitMs / 1000}s attempt ${attempt + 1}`)
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
  console.log('injectAuth', authCheck?.ok, authCheck?.status || 'ok')
  return Boolean(authCheck?.ok)
}

async function dismissModals(page) {
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('Escape').catch(() => {})
    const n = await page.locator('.ant-modal-close, button.ant-modal-close').count()
    for (let j = 0; j < n; j++) {
      try {
        const el = page.locator('.ant-modal-close, button.ant-modal-close').nth(j)
        if (await el.isVisible().catch(() => false)) {
          await el.click({ force: true, timeout: 1000 })
        }
      } catch {
        /* ignore */
      }
    }
    await page.waitForTimeout(300)
  }
}

async function main() {
  const creds = JSON.parse(fs.readFileSync(CREDS, 'utf8'))
  let b04 = {}
  try {
    b04 = JSON.parse(fs.readFileSync(REPORT, 'utf8'))
  } catch {
    /* optional */
  }
  const agentId = b04?.summary?.agent_id || creds.agent_id || 27
  const parentId = b04?.summary?.parent_task_id
  const childrenCount = b04?.summary?.children_count

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.setDefaultTimeout(90000)

  try {
    const okAuth = await injectAuth(page, creds)
    if (!okAuth) {
      console.error('auth failed')
      await page.screenshot({ path: OUT, fullPage: true })
      process.exit(1)
    }

    await page.goto(`${APP}/tasks`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(3000)
    await dismissModals(page)

    if (/\/login\b/i.test(page.url())) {
      console.warn('still on login after inject — retry injectAuth')
      await injectAuth(page, creds)
      await page.goto(`${APP}/tasks`, { waitUntil: 'domcontentloaded', timeout: 90000 })
      await page.waitForTimeout(3000)
      await dismissModals(page)
    }

    // Wait for board
    let loaded = false
    for (const re of [/Parent #/i, /weekly sales/i, /Goal:/i, /Auto-chain/i, /To do/i]) {
      try {
        await page.getByText(re).first().waitFor({ state: 'visible', timeout: 12000 })
        loaded = true
        console.log('found', String(re))
        break
      } catch {
        /* next */
      }
    }
    if (!loaded) {
      try {
        await page.locator('.ant-card').first().waitFor({ state: 'visible', timeout: 10000 })
        loaded = true
        console.log('found ant-card')
      } catch {
        console.warn('board still empty')
      }
    }

    await dismissModals(page)
    await page.waitForTimeout(800)
    await dismissModals(page)

    if (parentId) {
      try {
        const p = page
          .getByText(new RegExp(`Parent #${parentId}|#${parentId}`, 'i'))
          .first()
        if (await p.isVisible({ timeout: 2500 }).catch(() => false)) {
          await p.scrollIntoViewIfNeeded()
        }
      } catch {
        /* ignore */
      }
    }

    await page.screenshot({ path: OUT, fullPage: true })
    let body = await page.locator('body').innerText().catch(() => '')
    let url = page.url()

    const good =
      !/\/login\b/i.test(url) &&
      /Parent #|Goal:|weekly sales|Auto-chain|Tasks workflow/i.test(body)

    if (!good) {
      console.log('tasks weak — try agent chat page')
      await injectAuth(page, creds)
      await page.goto(`${APP}/agents/${agentId}`, {
        waitUntil: 'domcontentloaded',
        timeout: 90000,
      })
      await page.waitForTimeout(5000)
      await dismissModals(page)
      try {
        await page
          .getByText(/Auto-chain started|goal task|weekly sales plan|delegated steps/i)
          .first()
          .waitFor({ state: 'visible', timeout: 20000 })
      } catch {
        /* ignore */
      }
      await page.screenshot({ path: OUT, fullPage: true })
      body = await page.locator('body').innerText().catch(() => '')
      url = page.url()
    }

    console.log('WROTE', OUT)
    console.log(
      JSON.stringify(
        {
          screenshot: OUT,
          agent_id: agentId,
          parent_task_id: parentId,
          children_count: childrenCount,
          url,
          board_loaded: loaded,
          body_preview: body.slice(0, 320).replace(/\s+/g, ' '),
        },
        null,
        2,
      ),
    )
    process.exit(good || /Auto-chain|goal task|Parent #|weekly sales/i.test(body) ? 0 : 2)
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
