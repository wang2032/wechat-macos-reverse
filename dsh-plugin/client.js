window.__ModuleLoader__.load({
  id: '@local/dsh-wx-browser',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const { useCallback, useEffect, useMemo, useRef, useState } = React;

    // 插件自带服务在 8778；8777 是早期 Python 版服务，作为兜底
    const ORIGINS = [localStorage.getItem('wxBrowserApi'), 'http://127.0.0.1:8778', 'http://127.0.0.1:8777'].filter(Boolean);
    let activeOrigin = ORIGINS[0];
    const PAGE_ID = 'wx-records';

    /* ---------------- 小工具 ---------------- */

    async function get(path) {
      let last = null;
      for (const origin of ORIGINS) {
        try {
          const r = await fetch(origin + path, { cache: 'no-store' });
          if (!r.ok) { last = new Error('HTTP ' + r.status); continue; }
          activeOrigin = origin;
          return await r.json();
        } catch (e) { last = e; }
      }
      throw last || new Error('连不上本地服务');
    }

    const pad = n => String(n).padStart(2, '0');
    function fmtTime(ts) {
      const d = new Date(ts * 1000);
      return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    function dayKey(ts) {
      const d = new Date(ts * 1000);
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }
    function dayLabel(ts) {
      const d = new Date(ts * 1000);
      const now = new Date();
      const same = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
      if (same(d, now)) return '今天';
      const y = new Date(now.getTime() - 86400000);
      if (same(d, y)) return '昨天';
      return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' 周' + '日一二三四五六'[d.getDay()];
    }
    function ago(ts) {
      if (!ts) return '';
      const s = Date.now() / 1000 - ts;
      if (s < 60) return '刚刚';
      if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
      if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
      if (s < 86400 * 7) return Math.floor(s / 86400) + ' 天前';
      return fmtTime(ts).slice(0, 5);
    }

    /* ---------------- 样式 ---------------- */

    const CSS = `
.wxb{display:flex;height:100%;min-height:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:var(--dsw-alias-label-primary,#1b1b1b);background:var(--dsw-alias-bg-base,transparent)}
.wxb *{box-sizing:border-box}
.wxb-left{width:268px;flex:none;display:flex;flex-direction:column;min-height:0;border-right:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.18))}
.wxb-search{padding:10px 10px 8px;display:flex;flex-direction:column;gap:6px}
.wxb-search input{width:100%;padding:7px 10px;border-radius:var(--dsw-radius-sm,6px);border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.25));background:transparent;color:inherit;font:inherit;outline:none}
.wxb-search input:focus{border-color:var(--dsw-focus-ring-color,#0a84ff)}
.wxb-hint{font-size:11px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.9))}
.wxb-list{flex:1;overflow:auto;padding:2px 6px 12px}
.wxb-row{display:flex;gap:8px;align-items:baseline;padding:7px 9px;border-radius:var(--dsw-radius-sm,6px);cursor:pointer;overflow:hidden}
.wxb-row:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12))}
.wxb-row.on{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.16))}
.wxb-row .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wxb-row .t{flex:none;font-size:11px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.9))}
.wxb-badge{flex:none;min-width:16px;height:16px;padding:0 4px;border-radius:8px;background:var(--dsw-alias-state-error-primary,#e5484d);color:#fff;font-size:10px;line-height:16px;text-align:center}
.wxb-right{flex:1;min-width:0;display:flex;flex-direction:column;min-height:0;position:relative}
.wxb-head{flex:none;padding:12px 16px 10px;border-bottom:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.18));display:flex;flex-direction:column;gap:8px}
.wxb-head h1{margin:0;font-size:15px;font-weight:600;display:flex;align-items:center;gap:8px}
.wxb-meta{font-size:11px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.9));display:flex;gap:10px;flex-wrap:wrap}
.wxb-chips{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.wxb-chip{border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.25));background:transparent;color:inherit;border-radius:999px;padding:2px 9px;font-size:12px;cursor:pointer;display:inline-flex;gap:5px;align-items:center}
.wxb-chip.on{background:var(--dsw-alias-label-primary,#1b1b1b);color:var(--dsw-alias-bg-base,#fff);border-color:transparent}
.wxb-chip em{font-style:normal;opacity:.6}
.wxb-btn{border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.25));background:transparent;color:inherit;border-radius:var(--dsw-radius-sm,6px);padding:3px 10px;font-size:12px;cursor:pointer}
.wxb-btn:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12))}
.wxb-btn:disabled{opacity:.45;cursor:default}
.wxb-btn.primary{background:var(--dsw-alias-label-primary,#1b1b1b);color:var(--dsw-alias-bg-base,#fff);border-color:transparent}
.wxb-body{flex:1;overflow:auto;padding:10px 16px 24px;min-height:0}
.wxb-day{position:sticky;top:0;z-index:1;display:flex;justify-content:center;padding:6px 0;background:linear-gradient(var(--dsw-alias-bg-base,#fff) 70%,transparent)}
.wxb-day span{font-size:11px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.9));background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.1));border-radius:999px;padding:1px 9px}
.wxb-msg{display:grid;grid-template-columns:38px 1fr auto;gap:8px;padding:3px 0;align-items:start}
.wxb-msg .who{font-size:11px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.95));text-align:right;padding-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wxb-msg .txt{min-width:0;white-space:pre-wrap;word-break:break-word}
.wxb-msg .txt.card{color:var(--dsw-alias-label-secondary,rgba(70,70,70,.9))}
.wxb-msg .tag{display:inline-block;font-size:10px;padding:0 5px;border-radius:4px;border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.3));color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.95));margin-right:6px}
.wxb-msg.me .who{color:var(--dsw-alias-state-business-primary,#0a7d3f);font-weight:600}
.wxb-msg .tm{font-size:10px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.65));padding-top:4px;font-variant-numeric:tabular-nums}
.wxb-empty{padding:40px 20px;text-align:center;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.9));font-size:13px}
.wxb-err{margin:24px;padding:18px;border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.25));border-radius:var(--dsw-radius-lg,10px);font-size:13px;line-height:1.7}
.wxb-err code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12));padding:2px 6px;border-radius:4px}
.wxb-drawer{position:absolute;top:0;right:0;bottom:0;width:min(420px,60%);background:var(--dsw-alias-bg-base,#fff);border-left:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.2));box-shadow:-12px 0 30px rgba(0,0,0,.12);display:flex;flex-direction:column;z-index:5}
.wxb-drawer header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.18));font-size:13px;font-weight:600}
.wxb-drawer .body{flex:1;overflow:auto;padding:12px 14px;white-space:pre-wrap;font-size:13px;line-height:1.75}
.wxb-hit{padding:8px 9px;border-radius:var(--dsw-radius-sm,6px);cursor:pointer}
.wxb-hit:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12))}
.wxb-hit .h{font-size:11px;color:var(--dsw-alias-label-tertiary,rgba(127,127,127,.9));display:flex;gap:8px}
.wxb-hit .x{margin-top:2px;font-size:13px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
`;

    function StyleOnce() {
      useEffect(() => {
        const id = 'wxb-style';
        if (!document.getElementById(id)) {
          const el = document.createElement('style');
          el.id = id; el.textContent = CSS;
          document.head.appendChild(el);
        }
      }, []);
      return null;
    }

    /* ---------------- 页面 ---------------- */

    function Page() {
      const [chats, setChats] = useState([]);
      const [sel, setSel] = useState(null);
      const [msgs, setMsgs] = useState([]);
      const [senders, setSenders] = useState([]);
      const [filter, setFilter] = useState('');
      const [q, setQ] = useState('');
      const [hits, setHits] = useState(null);
      const [loading, setLoading] = useState(false);
      const [err, setErr] = useState('');
      const [summary, setSummary] = useState(null);
      const [busy, setBusy] = useState(false);
      const bodyRef = useRef(null);
      const stuckBottom = useRef(true);

      const loadChats = useCallback(async () => {
        try {
          const d = await get('/api/chats');
          setChats(d.chats || []);
          setErr('');
          setSel(s => s || (d.chats && d.chats[0] ? d.chats[0] : null));
        } catch (e) {
          setErr(String(e.message || e));
        }
      }, []);

      useEffect(() => { loadChats(); const t = setInterval(loadChats, 15000); return () => clearInterval(t); }, [loadChats]);

      const loadMsgs = useCallback(async (chat, before) => {
        if (!chat) return;
        setLoading(true);
        try {
          const d = await get('/api/messages?chat=' + encodeURIComponent(chat.username) + '&limit=200' + (before ? '&before_ts=' + before : ''));
          const got = d.messages || [];
          setMsgs(prev => before ? got.concat(prev) : got);
          setErr('');
        } catch (e) { setErr(String(e.message || e)); }
        setLoading(false);
      }, []);

      useEffect(() => {
        if (!sel) return;
        setSenders([]); setFilter('');
        loadMsgs(sel, null).then(() => { stuckBottom.current = true; });
        get('/api/senders?chat=' + encodeURIComponent(sel.username)).then(d => setSenders(d.senders || [])).catch(() => {});
      }, [sel, loadMsgs]);

      // 全局搜索（防抖）
      useEffect(() => {
        const text = q.trim();
        if (text.length < 2) { setHits(null); return; }
        const t = setTimeout(async () => {
          try {
            const d = await get('/api/search?q=' + encodeURIComponent(text) + '&limit=120');
            setHits(d.hits || []);
          } catch (e) { setHits([]); }
        }, 420);
        return () => clearTimeout(t);
      }, [q]);

      useEffect(() => {
        const el = bodyRef.current;
        if (el && stuckBottom.current) el.scrollTop = el.scrollHeight;
      }, [msgs]);

      const filteredChats = useMemo(() => {
        const text = q.trim().toLowerCase();
        if (!text || hits) return chats;
        return chats.filter(c => (c.name || '').toLowerCase().includes(text));
      }, [chats, q, hits]);

      const visible = useMemo(() => filter ? msgs.filter(m => m.sender === filter) : msgs, [msgs, filter]);

      const groups = useMemo(() => {
        const out = [];
        let day = null;
        for (const m of visible) {
          const k = dayKey(m.ts);
          if (k !== day) { day = k; out.push({ kind: 'day', key: k, ts: m.ts }); }
          out.push({ kind: 'msg', m });
        }
        return out;
      }, [visible]);

      const summarize = async (ai) => {
        if (!sel) return;
        setBusy(true);
        try {
          const d = await get('/api/summary?chat=' + encodeURIComponent(sel.username) + '&days=14&ai=' + (ai ? 1 : 0));
          setSummary({ text: d.text || '(空)', ai: !!d.ai });
        } catch (e) { setSummary({ text: '总结失败：' + e.message, ai: false }); }
        setBusy(false);
      };

      const openHit = (hit) => {
        const c = chats.find(x => x.username === hit.chat);
        if (c) { setSel(c); setQ(''); }
      };

      if (err && chats.length === 0) {
        return h('div', { className: 'wxb' }, h(StyleOnce),
          h('div', { className: 'wxb-err' },
            h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '连不上本地微信服务'),
            h('div', null, '这个页面读的是本机的 ', h('code', null, API), '，请先把服务跑起来：'),
            h('pre', { style: { margin: '10px 0', padding: '10px 12px', background: 'rgba(127,127,127,.12)', borderRadius: 6, overflow: 'auto' } },
              'cd ~/10x_warehome/tmp/agent/wechat-dump/assistant\npython3 server.py'),
            h('div', null, '或者直接双击 ', h('code', null, '启动微信助手.command'), '。'),
            h('div', { style: { marginTop: 10, display: 'flex', gap: 8 } },
              h('button', { className: 'wxb-btn primary', onClick: loadChats }, '重试'),
              h('button', { className: 'wxb-btn', onClick: () => { setErr(''); loadChats(); } }, '我已启动')),
            h('div', { style: { marginTop: 8, fontSize: 12, opacity: .7 } }, '错误：' + err)));
      }

      return h('div', { className: 'wxb' }, h(StyleOnce),
        /* 左栏 */
        h('div', { className: 'wxb-left' },
          h('div', { className: 'wxb-search' },
            h('input', {
              value: q, placeholder: '搜会话，或直接搜消息内容…',
              onChange: e => setQ(e.target.value),
            }),
            hits ? h('div', { className: 'wxb-hint' }, '全局搜索：' + hits.length + ' 条命中')
              : h('div', { className: 'wxb-hint' }, chats.length + ' 个会话 · 每 15 秒刷新')),
          h('div', { className: 'wxb-list' },
            hits ? hits.map((hit, i) => h('div', {
              key: i, className: 'wxb-hit', onClick: () => openHit(hit),
            },
              h('div', { className: 'h' }, h('span', null, hit.chat_name), h('span', null, fmtTime(hit.ts))),
              h('div', { className: 'x' }, hit.text)))
              : filteredChats.map(c => h('div', {
                key: c.username, className: 'wxb-row' + (sel && sel.username === c.username ? ' on' : ''),
                onClick: () => setSel(c), title: c.summary || '',
              },
                h('span', { className: 'n' }, c.name || c.username),
                c.unread > 0 ? h('span', { className: 'wxb-badge' }, c.unread > 99 ? '99+' : c.unread) : null,
                h('span', { className: 't' }, ago(c.last_ts)))),
            (!hits && filteredChats.length === 0) ? h('div', { className: 'wxb-empty' }, '没有匹配的会话') : null)),
        /* 右栏 */
        h('div', { className: 'wxb-right' },
          h('div', { className: 'wxb-head' },
            h('h1', null, sel ? (sel.name || sel.username) : '选一个会话',
              h('span', { style: { marginLeft: 'auto', display: 'flex', gap: 6 } },
                h('button', { className: 'wxb-btn', disabled: busy, onClick: () => summarize(false) }, busy ? '…' : '快速总结'),
                h('button', { className: 'wxb-btn primary', disabled: busy, onClick: () => summarize(true) }, busy ? '…' : 'AI 总结'))),
            h('div', { className: 'wxb-meta' },
              h('span', null, (visible.length) + ' 条' + (filter ? '（已筛选）' : '')),
              sel && sel.kind === 'group' ? h('span', null, '群聊') : h('span', null, '单聊'),
              h('span', null, '本地解密读取 · 不外传')),
            senders.length > 1 ? h('div', { className: 'wxb-chips' },
              h('button', { className: 'wxb-chip' + (filter ? '' : ' on'), onClick: () => setFilter('') },
                '全部 ', h('em', null, msgs.length)),
              senders.slice(0, 8).map(s => h('button', {
                key: s.wxid, className: 'wxb-chip' + (filter === s.wxid ? ' on' : ''),
                onClick: () => setFilter(filter === s.wxid ? '' : s.wxid),
              }, s.name || s.wxid, ' ', h('em', null, s.count)))) : null),
          h('div', {
            className: 'wxb-body', ref: bodyRef,
            onScroll: e => {
              const el = e.currentTarget;
              stuckBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
            },
          },
            msgs.length >= 200 && !filter ? h('div', { style: { textAlign: 'center', paddingBottom: 8 } },
              h('button', {
                className: 'wxb-btn', disabled: loading,
                onClick: () => loadMsgs(sel, msgs[0] && msgs[0].ts),
              }, loading ? '载入中…' : '载入更早')) : null,
            groups.length === 0 && !loading ? h('div', { className: 'wxb-empty' }, '这个会话没有可显示的消息') : null,
            groups.map((g, i) => g.kind === 'day'
              ? h('div', { className: 'wxb-day', key: 'd' + g.key }, h('span', null, dayLabel(g.ts)))
              : h('div', { className: 'wxb-msg' + (g.m.mine ? ' me' : ''), key: 'm' + g.m.id },
                h('span', { className: 'who' }, g.m.mine ? '我' : (g.m.from || '')),
                h('span', { className: 'txt' + (g.m.type === '文本' ? '' : ' card') },
                  g.m.type === '文本' ? null : h('span', { className: 'tag' }, g.m.type),
                  g.m.text || ''),
                h('span', { className: 'tm' }, fmtTime(g.m.ts).slice(6)))),
          ),
          summary ? h('div', { className: 'wxb-drawer' },
            h('header', null,
              h('span', null, summary.ai ? 'AI 总结' : '快速总结'),
              h('span', { style: { display: 'flex', gap: 6 } },
                h('button', { className: 'wxb-btn', onClick: () => setSummary(null) }, '关闭'))),
            h('div', { className: 'body' }, summary.text)) : null));
    }

    function Icon() {
      return h('svg', {
        viewBox: '0 0 16 16', width: 16, height: 16, fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.3, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': true, style: { display: 'block' },
      },
        h('path', { d: 'M2.5 3.5h11v7.2h-6.1L4.2 13.4v-2.7H2.5z' }),
        h('path', { d: 'M5.6 6.2h4.8M5.6 8.3h3' }));
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('main', () => ctx.slots.register({
          name: 'main', key: PAGE_ID, label: () => '微信记录',
        }, Page));
        ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist', id: PAGE_ID, order: 60, label: () => '微信记录',
        }, Icon));
      },
    };
  },
});
