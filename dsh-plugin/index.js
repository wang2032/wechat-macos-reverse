/**
 * Host half: starts the local record service (127.0.0.1:8778) on plugin load.
 * The service reads WeChat's encrypted DBs through the bundled static `bin/wxq`.
 */
import { start, stop } from './server.mjs'

export function apply(ctx) {
  try {
    start()
  } catch (error) {
    console.error('[wx-browser] 本地记录服务启动失败：', error && error.message)
  }
  if (ctx && typeof ctx.effect === 'function') {
    ctx.effect(() => () => {
      try { stop() } catch {}
    })
  }
}
