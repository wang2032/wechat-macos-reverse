/**
 * 换机器后的初始化：写账号与密钥，并当场验证能不能解开库。
 *   node setup.mjs --account wxid_xxx_yyy --key <64位hex>
 *   node setup.mjs                # 只做检测，打印这台机器上看到的账号
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { status, chats } from './server.mjs'

const dir = path.join(os.homedir(), '.dsh-wx-browser')
const file = path.join(dir, 'config.json')

const argv = process.argv.slice(2)
const get = (k) => {
  const i = argv.indexOf('--' + k)
  return i >= 0 ? argv[i + 1] : ''
}
const account = get('account')
const key = get('key')

if (account && key) {
  if (!/^[0-9a-f]{64}$/i.test(key)) {
    console.error('密钥应是 64 位十六进制（32 字节）')
    process.exit(1)
  }
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
  fs.writeFileSync(file, JSON.stringify({ account, key }, null, 2) + '\n', { mode: 0o600 })
  console.log('已写入', file)
}

console.log('状态：', JSON.stringify(status(), null, 2))
try {
  const list = chats()
  console.log('会话数：', list.length)
  console.log('前三个：', list.slice(0, 3).map((c) => c.name).join(' / ') || '（空）')
} catch (e) {
  console.error('读库失败：', e.message)
  console.error('多半是密钥不对，或这台机器还没抓过密钥。')
  process.exit(2)
}
