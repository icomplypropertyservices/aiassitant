/**
 * Robust templates screenshot: re-login before route, re-login on bounce,
 * snooze top-up modal, verify me before navigate.
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CREDS = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`

fs.mkdirSync(SHOTS, { recursive: true })
const creds = JSON.parse(fs.readFileSync(CREDS, 'utf8'))

async function pageLogin(page) {
  return page.evaluate(
    async ({ email, password }) => {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const j = await r.json().catch(() => ({}))
      const key = j.api_key || j.token
      if (!r.ok || !key) return { ok: false, status: r.status, detail: j.detail || j }
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      localStorage.setItem(
        'user',
        JSON.stringify(j.user || { email, plan: 'trial', subscription_active: true }),
      )
      localStorage.setItem('topup_modal_snooze_until', String(Date.now() + 7 * 24 * 3600 * 1000))
      return { ok: true, status: r.status, user_id: j.user?.id, key_prefix: key.slice(0, 14) }
    },
    { email: creds.email, password: creds.password },
  )
}

async function meOk(page) {
  return page.evaluate(async () => {
    const key = localStorage.getItem('api_key') || localStorage.getItem('token')
    if (!key) return false
    const r = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key, Accept: 'application/json' },
    })
    return r.ok
  })
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  try {
    await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(1500)

    let login = await pageLogin(page)
    for (let i = 0; i < 4 && !login.ok; i++) {
      console.warn('login fail', login)
      if (login.status === 429) await page.waitForTimeout(50000)
      else await page.waitForTimeout(2000)
      login = await pageLogin(page)
    }
    console.log('login', login)
    if (!login.ok) {
      process.exitCode = 1
      return
    }

    const url = `${APP}/templates`
    let ok = false
    for (let attempt = 1; attempt <= 6; attempt++) {
      if (!(await meOk(page))) {
        login = await pageLogin(page)
        console.log(`attempt ${attempt} re-login`, login)
        if (!login.ok) {
          if (login.status === 429) await page.waitForTimeout(50000)
          continue
        }
      }
      // re-assert snooze right before navigate
      await page.evaluate(() => {
        localStorage.setItem('topup_modal_snooze_until', String(Date.now() + 7 * 24 * 3600 * 1000))
      })
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
      await page.waitForTimeout(3200)
      if (page.url().includes('/login')) {
        console.warn(`attempt ${attempt} bounced to login`)
        continue
      }
      // dismiss any residual modal
      await page.keyboard.press('Escape').catch(() => {})
      const close = page.locator('.ant-modal-close').first()
      if (await close.isVisible().catch(() => false)) {
        await close.click().catch(() => {})
        await page.waitForTimeout(400)
      }
      const body = (await page.locator('body').innerText().catch(() => '')).slice(0, 400)
      const cards = await page.locator('.ant-card').count()
      console.log(`attempt ${attempt} url=${page.url()} cards=${cards}`)
      console.log('body', body.replace(/\s+/g, ' ').slice(0, 250))
      if (cards >= 5 || /Main AI Orchestrator|Templates/i.test(body)) {
        ok = true
        break
      }
    }

    const out = path.join(SHOTS, 'templates_page_live.png')
    await page.screenshot({ path: out, fullPage: true })
    // also copy viewport
    await page.screenshot({ path: path.join(SHOTS, 'a_templates.png'), fullPage: false })
    console.log('screenshot', out, 'ok', ok)
    if (!ok) process.exitCode = 1
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
