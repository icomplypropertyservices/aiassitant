/**
 * Login + screenshot templates page (with re-login recovery for key rotation).
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
        return { ok: false, status: r.status, detail: j.detail || j }
      }
      localStorage.setItem('api_key', key)
      localStorage.setItem('token', key)
      localStorage.setItem(
        'user',
        JSON.stringify(j.user || { email, plan: 'trial', subscription_active: true }),
      )
      return { ok: true, status: r.status, user_id: j.user?.id, key_prefix: key.slice(0, 16) }
    },
    { email: creds.email, password: creds.password },
  )
}

async function main() {
  const creds = loadCreds()
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  try {
    await page.goto(`${APP}/login`, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(1500)
    let login = await pageLogin(page, creds)
    if (!login.ok && login.status === 429) {
      console.warn('Login 429 — wait 25s retry')
      await page.waitForTimeout(25000)
      login = await pageLogin(page, creds)
    }
    console.log('login', JSON.stringify(login))
    if (!login.ok) {
      const failPath = path.join(SHOTS, 'templates_page_fail.png')
      await page.screenshot({ path: failPath, fullPage: true })
      console.log('FAIL screenshot', failPath)
      process.exitCode = 1
      return
    }

    const url = `${APP}/templates`
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
    await page.waitForTimeout(3000)

    if (page.url().includes('/login')) {
      console.warn('bounced to login — re-login')
      const again = await pageLogin(page, creds)
      console.log('re-login', JSON.stringify(again))
      if (again.ok) {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
        await page.waitForTimeout(3500)
      }
    }

    // one more recovery if still on login
    if (page.url().includes('/login')) {
      const again = await pageLogin(page, creds)
      console.log('re-login2', JSON.stringify(again))
      if (again.ok) {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 })
        await page.waitForTimeout(4000)
      }
    }

    try {
      const key = await page.evaluate(() => localStorage.getItem('api_key'))
      if (key) {
        creds.api_key = key
        fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
        fs.writeFileSync(path.join(__dirname, '.demo_token'), key)
      }
    } catch {
      /* ignore */
    }

    await page
      .waitForSelector('.ant-card, .aba-page-shell, text=/template/i', { timeout: 15000 })
      .catch(() => {})

    const out = path.join(SHOTS, 'templates_page_live.png')
    await page.screenshot({ path: out, fullPage: true })
    const title = await page.title()
    const finalUrl = page.url()
    const bodyText = await page.evaluate(() => (document.body?.innerText || '').slice(0, 800))
    const cards = await page.locator('.ant-card').count()
    console.log('url', finalUrl)
    console.log('title', title)
    console.log('cards', cards)
    console.log('body_preview', bodyText.replace(/\s+/g, ' ').slice(0, 400))
    console.log('screenshot', out)
    if (finalUrl.includes('/login')) process.exitCode = 1
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
