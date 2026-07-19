/**
 * One-shot: login with .demo_login.json, open orchestrator chat, screenshot b02_chat.png
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.env.BASE_URL || 'https://www.aibusinessagent.xyz'
const APP = `${BASE}/agents`
const CREDS = path.join(__dirname, '.demo_login.json')
const SHOTS = path.join(__dirname, 'live-screenshots')
const OUT = path.join(SHOTS, 'b02_chat.png')

fs.mkdirSync(SHOTS, { recursive: true })
const creds = JSON.parse(fs.readFileSync(CREDS, 'utf8'))
const agentId = creds.agent_id || 27

async function pageLogin(page) {
  return page.evaluate(
    async ({ email, password, api_key }) => {
      if (api_key) {
        const me = await fetch('/api/auth/me', {
          headers: {
            Authorization: `Bearer ${api_key}`,
            'X-API-Key': api_key,
            Accept: 'application/json',
          },
        })
        if (me.ok) {
          const u = await me.json()
          localStorage.setItem('api_key', api_key)
          localStorage.setItem('token', api_key)
          localStorage.setItem('user', JSON.stringify(u))
          return { ok: true, mode: 'cached', user_id: u.id }
        }
      }
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
      localStorage.setItem('user', JSON.stringify(j.user || { email }))
      return { ok: true, mode: 'login', user_id: j.user?.id, key_prefix: String(key).slice(0, 16) }
    },
    { email: creds.email, password: creds.password, api_key: creds.api_key },
  )
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })

  await page.goto(`${APP}/login`, { waitUntil: 'commit', timeout: 120000 })
  await page.waitForTimeout(1500)

  let login = await pageLogin(page)
  console.log('login1', JSON.stringify(login))
  if (!login.ok && login.status === 429) {
    await page.waitForTimeout(25000)
    login = await pageLogin(page)
    console.log('login2', JSON.stringify(login))
  }
  if (!login.ok) {
    await page.waitForTimeout(4000)
    login = await pageLogin(page)
    console.log('login3', JSON.stringify(login))
  }

  try {
    const key = await page.evaluate(() => localStorage.getItem('api_key'))
    if (key) {
      creds.api_key = key
      fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2))
    }
  } catch {
    /* ignore */
  }

  const chatUrl = `${APP}/agents/${agentId}`
  console.log('goto', chatUrl)
  await page.goto(chatUrl, { waitUntil: 'commit', timeout: 120000 })
  await page.waitForTimeout(4500)

  let url = page.url()
  console.log('url1', url)
  if (url.includes('/login')) {
    login = await pageLogin(page)
    console.log('relogin', JSON.stringify(login))
    await page.goto(chatUrl, { waitUntil: 'commit', timeout: 120000 })
    await page.waitForTimeout(4500)
    url = page.url()
  }

  // Prefer waiting for chat composer
  try {
    await page
      .locator(
        'textarea.agent-chat-textarea, .agent-chat-input-wrap textarea, textarea[placeholder*="Message" i], textarea',
      )
      .first()
      .waitFor({ timeout: 15000 })
  } catch {
    console.warn('composer not found in time')
  }

  await page.waitForTimeout(1500)
  const bodyText = await page.locator('body').innerText().catch(() => '')
  console.log('body_snip', bodyText.slice(0, 500).replace(/\n/g, ' | '))
  console.log('final_url', page.url())

  await page.screenshot({ path: OUT, fullPage: true })
  const st = fs.statSync(OUT)
  console.log('SHOT', OUT, st.size)
  await browser.close()
  if (st.size < 1000) process.exit(2)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
