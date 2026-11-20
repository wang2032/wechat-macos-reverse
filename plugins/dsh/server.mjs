/**
 * 微信聊天记录服务：只用 Node 标准库 + 自带的 bin/wxq（静态 SQLCipher）。
 * 不依赖 Python，也不碰微信运行中的文件（先 clone 一份快照再读）。
 */
import { createServer } from 'node:http'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import zlib from 'node:zlib'

const HERE = path.dirname(new URL(import.meta.url).pathname)
const WXQ = path.join(HERE, 'bin', 'wxq')
const HOME = os.homedir()
const BASE = path.join(HOME, 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files')
const PORT = Number(process.env.WX_BROWSER_PORT || 8778)

const TYPE = { 1: '文本', 3: '图片', 34: '语音', 43: '视频', 47: '表情', 48: '位置', 49: '卡片', 50: '通话', 10000: '系统' }

/* ---------------- 配置：账号与密钥 ---------------- */

function configPath() {
  return process.env.WX_BROWSER_CONFIG || path.join(HOME, '.dsh-wx-browser', 'config.json')
}

function loadConfig() {
  const out = { account: process.env.WX_ACCOUNT || '', key: process.env.WX_KEY || '' }
  try {
    const c = JSON.parse(fs.readFileSync(configPath(), 'utf8'))
    if (c.account) out.account = c.account
    if (c.key) out.key = c.key
  } catch {}
  if (!out.key) {
    // 本机老工具链留下的密钥文件，省一次手动配置
    for (const p of [path.join(HOME, '10x_warehome/tmp/agent/wechat-dump/account_key.json')]) {
      try {
        const c = JSON.parse(fs.readFileSync(p, 'utf8'))
        if (c.account && c.key) { out.account = c.account; out.key = c.key; break }
      } catch {}
    }
  }
  if (!out.account) {
    const dirs = fs.existsSync(BASE)
      ? fs.readdirSync(BASE).filter((d) => d.startsWith('wxid_') && fs.existsSync(path.join(BASE, d, 'db_storage')))
      : []
    if (dirs.length === 1) out.account = dirs[0]
  }
  return out
}

let CONFIG = loadConfig()
const dbdir = () => path.join(BASE, CONFIG.account, 'db_storage')

export function status() {
  const ready = Boolean(CONFIG.account && CONFIG.key && fs.existsSync(dbdir()))
  return { ready, account: CONFIG.account, account_dir: dbdir(), has_key: Boolean(CONFIG.key) }
}

/* ---------------- 快照 + 查询 ---------------- */

const snaps = new Map() // name -> { at, dir }

function snapshot(name, files, maxAgeMs) {
  const hit = snaps.get(name)
  const now = Date.now()
  if (hit && now - hit.at < maxAgeMs && fs.existsSync(hit.dir)) return hit.dir
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wxb-' + name + '-'))
  for (const f of files) {
    const src = path.join(dbdir(), f)
    if (!fs.existsSync(src)) continue
    const dst = path.join(dir, path.basename(f))
    try {
      fs.copyFileSync(src, dst, fs.constants.COPYFILE_FICLONE)
    } catch {
      fs.copyFileSync(src, dst)
    }
  }
  if (hit) { try { fs.rmSync(hit.dir, { recursive: true, force: true }) } catch {} }
  snaps.set(name, { at: now, dir })
  return dir
}

const msgDir = () => snapshot('msg', ['message/message_0.db', 'message/message_0.db-wal', 'message/message_0.db-shm'], 4000)
const sessionDir = () => snapshot('session', ['session/session.db', 'session/session.db-wal', 'session/session.db-shm'], 30000)
const contactDir = () => snapshot('contact', ['contact/contact.db', 'contact/contact.db-wal', 'contact/contact.db-shm'], 120000)

function q(db, sql) {
  const out = execFileSync(WXQ, [db, CONFIG.key, sql], { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 })
  const rows = []
  for (const line of out.split('\n')) {
    if (!line) continue
    rows.push(line.split('\t').map((c) => (c === '\\N' ? null : unesc(c))))
  }
  return rows
}

function unesc(s) {
  if (!s.includes('\\')) return s
  return s.replace(/\\(.)/g, (_, c) => ({ t: '\t', n: '\n', r: '\r', '\\': '\\' }[c] ?? c))
}

function textOf(content, ctype) {
  if (content == null || content === '') return ''
  let buf = Buffer.isBuffer(content) ? content : Buffer.from(String(content), 'utf8')
  if (ctype && ctype !== '0') {
    try { buf = zlib.zstdDecompressSync(buf) } catch { return '' }
  }
  return buf.toString('utf8')
}

function splitSender(text) {
  if (!text || text.startsWith('<')) return ['', text]
  const i = text.indexOf(':\n')
  if (i < 0 || i > 80) return ['', text]
  return [text.slice(0, i), text.slice(i + 2)]
}

function clean(body) {
  if (!body) return ''
  const s = body.trim()
  if (!s.startsWith('<')) return s
  for (const tag of ['title', 'des']) {
    const m = s.match(new RegExp('<' + tag + '>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?</' + tag + '>'))
    if (m) return decode(m[1].trim()).slice(0, 120)
  }
  return ''
}

function decode(s) {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
}

let cache = { tables: null, id2user: null, names: null, namesAt: 0 }

function tables() {
  if (!cache.tables) {
    const rows = q(path.join(msgDir(), 'message_0.db'), "select name from sqlite_master where type='table' and name like 'Msg_%'")
    cache.tables = new Set(rows.map((r) => r[0]))
  }
  return cache.tables
}

function tableOf(username) {
  const t = 'Msg_' + createHash('md5').update(username).digest('hex')
  return tables().has(t) ? t : null
}

function id2user() {
  if (!cache.id2user) {
    const m = new Map()
    for (const [rowid, uname] of q(path.join(msgDir(), 'message_0.db'), 'select rowid,user_name from Name2Id')) m.set(Number(rowid), uname)
    cache.id2user = m
  }
  return cache.id2user
}

function names() {
  if (!cache.names || Date.now() - cache.namesAt > 120000) {
    const m = new Map()
    try {
      for (const [u, remark, nick, alias] of q(path.join(contactDir(), 'contact.db'), 'select username,remark,nick_name,alias from contact')) {
        m.set(u, remark || nick || alias || u)
      }
    } catch {}
    cache = { ...cache, names: m, namesAt: Date.now() }
  }
  return cache.names
}

function me() { return (CONFIG.account || '').replace(/_[0-9a-f]+$/, '') }
function label(lt) { return TYPE[Number(lt || 0) & 0xffffffff] || 'type' + (Number(lt || 0) & 0xffffffff) }

/* ---------------- 业务 ---------------- */

export function chats() {
  const rows = q(path.join(sessionDir(), 'session.db'), 'select username,last_timestamp,unread_count,summary from SessionTable')
  const nm = names()
  const out = []
  for (const [u, ts, un, summary] of rows) {
    if (!u || u.startsWith('gh_') || u === 'brandsessionholder') continue
    const t = tableOf(u)
    if (!t) continue
    out.push({
      username: u,
      name: nm.get(u) || summary || u,
      kind: u.endsWith('@chatroom') ? 'group' : u === 'filehelper' ? 'filehelper' : 'person',
      last_ts: Number(ts || 0),
      unread: Number(un || 0),
      summary: summary || '',
    })
  }
  out.sort((a, b) => b.last_ts - a.last_ts)
  return out
}

export function messages(username, { limit = 60, before_ts = 0, after_ts = 0 } = {}) {
  const t = tableOf(username)
  if (!t) return []
  const where = []
  if (before_ts) where.push('create_time < ' + Number(before_ts))
  if (after_ts) where.push('create_time > ' + Number(after_ts))
  const w = where.length ? 'where ' + where.join(' and ') : ''
  const rows = q(path.join(msgDir(), 'message_0.db'),
    `select local_id,local_type,create_time,real_sender_id,message_content,WCDB_CT_message_content from ${t} ${w} order by local_id desc limit ${Number(limit)}`)
  const i2u = id2user()
  const nm = names()
  const mine = me()
  const out = []
  for (const [lid, lt, ts, sid, content, ctype] of rows.reverse()) {
    let body = textOf(content, ctype)
    let snd
    ;[snd, body] = splitSender(body)
    snd = snd || i2u.get(Number(sid || 0)) || ''
    const isMine = snd === mine
    out.push({
      id: Number(lid), ts: Number(ts || 0), type: label(lt),
      from: isMine ? 'me' : nm.get(snd) || snd || '对方',
      sender: snd, mine: isMine, text: clean(body),
    })
  }
  return out
}

export function senders(username) {
  const t = tableOf(username)
  if (!t) return { senders: [], total: 0 }
  const rows = q(path.join(msgDir(), 'message_0.db'),
    `select real_sender_id,count(*) from ${t} group by real_sender_id order by count(*) desc`)
  const i2u = id2user()
  const nm = names()
  const out = rows.map(([sid, n]) => {
    const wxid = i2u.get(Number(sid || 0)) || ''
    return { wxid, name: nm.get(wxid) || wxid || '未知', count: Number(n) }
  })
  return { senders: out, total: out.reduce((a, b) => a + b.count, 0) }
}

export function summary(username, days = 7) {
  const cut = Math.floor(Date.now() / 1000) - days * 86400
  const msgs = messages(username, { limit: 5000 }).filter((m) => m.ts >= cut)
  if (!msgs.length) return { text: '这段时间没有消息。' }
  const mine = msgs.filter((m) => m.mine)
  const who = new Map()
  for (const m of msgs) if (!m.mine) who.set(m.from, (who.get(m.from) || 0) + 1)
  const top = [...who.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)
  const last = msgs[msgs.length - 1]
  const lines = [
    `近 ${days} 天 ${msgs.length} 条，你发了 ${mine.length} 条（${Math.round((mine.length / msgs.length) * 100)}%）。`,
    top.length ? '说话最多：' + top.map(([n, c]) => `${n} ${c} 条`).join('、') : '',
    `最后一条：${last.mine ? '你' : last.from}「${(last.text || '').slice(0, 40)}」`,
  ]
  return { text: lines.filter(Boolean).join('\n') }
}

export async function search(keyword, { days = 90, limit = 200, chat = '' } = {}) {
  const cut = Math.floor(Date.now() / 1000) - days * 86400
  const lit = "'%" + String(keyword).replace(/'/g, "''") + "%'"
  const list = chats().filter((c) => !chat || c.username === chat)
  const db = path.join(msgDir(), 'message_0.db')
  const i2u = id2user()

  // 一次进程里查一批会话（UNION ALL），否则 180 次进程启动就是十几秒
  const CHUNK = 12
  const chunks = []
  for (let i = 0; i < list.length; i += CHUNK) chunks.push(list.slice(i, i + CHUNK))

  const hits = []
  const run = async (group) => {
    const parts = group
      .map((c) => {
        const t = tableOf(c.username)
        if (!t) return null
        const inner = `select '${c.username.replace(/'/g, "''")}' as ch, local_id, create_time, real_sender_id, message_content, WCDB_CT_message_content from ${t} where create_time >= ${cut} and message_content like ${lit} order by create_time desc limit 20`
        return `select * from (${inner})`
      })
      .filter(Boolean)
    if (!parts.length) return
    let rows = []
    try {
      rows = q(db, parts.join(' union all '))
    } catch {
      return
    }
    const byChat = new Map(group.map((c) => [c.username, c]))
    for (const [ch, lid, ts, sid, content, ctype] of rows) {
      let body = textOf(content, ctype)
      body = clean(splitSender(body)[1])
      if (!body) continue
      const c = byChat.get(ch)
      hits.push({
        chat: ch, chat_name: c ? c.name : ch, id: Number(lid), ts: Number(ts || 0),
        wxid: i2u.get(Number(sid || 0)) || '', text: body.slice(0, 200),
      })
    }
  }
  let i = 0
  const workers = 4
  await Promise.all(Array.from({ length: workers }, async () => {
    while (i < chunks.length) await run(chunks[i++])
  }))
  hits.sort((a, b) => b.ts - a.ts)
  return hits.slice(0, limit)
}

/* ---------------- HTTP ---------------- */

function json(res, obj, code = 200) {
  const body = Buffer.from(JSON.stringify(obj))
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': body.length,
    'access-control-allow-origin': '*',
    'access-control-allow-headers': 'content-type',
    'cache-control': 'no-store',
  })
  res.end(body)
}

export function createWxServer() {
  return createServer(async (req, res) => {
    if (req.method === 'OPTIONS') { json(res, {}, 204); return }
    const u = new URL(req.url, 'http://127.0.0.1')
    try {
      if (u.pathname === '/api/health') return json(res, status())
      if (!CONFIG.key) return json(res, { error: 'no key', ...status() }, 409)
      if (u.pathname === '/api/chats') return json(res, { chats: chats() })
      if (u.pathname === '/api/messages') {
        const chat = u.searchParams.get('chat')
        if (!chat) return json(res, { error: 'missing chat' }, 400)
        return json(res, { messages: messages(chat, {
          limit: Number(u.searchParams.get('limit') || 60),
          before_ts: Number(u.searchParams.get('before_ts') || 0),
          after_ts: Number(u.searchParams.get('after_ts') || 0),
        }) })
      }
      if (u.pathname === '/api/senders') {
        const chat = u.searchParams.get('chat')
        if (!chat) return json(res, { error: 'missing chat' }, 400)
        return json(res, senders(chat))
      }
      if (u.pathname === '/api/summary') {
        const chat = u.searchParams.get('chat')
        if (!chat) return json(res, { error: 'missing chat' }, 400)
        return json(res, summary(chat, Number(u.searchParams.get('days') || 7)))
      }
      if (u.pathname === '/api/search') {
        const keyword = u.searchParams.get('q')
        if (!keyword) return json(res, { error: 'missing q' }, 400)
        return json(res, { hits: await search(keyword, {
          days: Number(u.searchParams.get('days') || 90),
          limit: Number(u.searchParams.get('limit') || 200),
          chat: u.searchParams.get('chat') || '',
        }) })
      }
      json(res, { error: 'not found' }, 404)
    } catch (e) {
      json(res, { error: String(e && e.message || e) }, 500)
    }
  })
}

let server = null

export function start(port = PORT) {
  if (server) return server
  server = createWxServer()
  server.listen(port, '127.0.0.1')
  server.on('error', () => { server = null })
  return server
}

export function stop() {
  if (server) { server.close(); server = null }
}
