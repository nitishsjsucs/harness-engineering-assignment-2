/**
 * dsh-second-brain — Client half (runs in the DSH Web UI).
 *
 * Two slot registrations share one tiny store:
 *   conversation.input.right  a brain button in the composer tool row
 *   shell.overlay             a floating panel: browse, search, read, capture
 *
 * This file is shipped as-is (no bundler): the Web UI's module loader calls
 * `factory(require)` lazily and `require('react')` returns the page's own
 * React, so the plugin never bundles a second copy.
 */
window.__ModuleLoader__.load({
  id: 'dsh-second-brain',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useCallback, useSyncExternalStore } = React

    const API = '/second-brain/api/notes'
    const HEADERS = { 'x-second-brain': '1' }

    // ── shared open/closed store (button and panel live in different slots) ──
    let open = false
    const listeners = new Set()
    const store = {
      get: () => open,
      set(next) { open = typeof next === 'function' ? next(open) : next; listeners.forEach(fn => fn()) },
      subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    }
    const useOpen = () => useSyncExternalStore(store.subscribe, store.get, store.get)

    async function api(path = '', init = {}) {
      const res = await fetch(API + path, { ...init, headers: { ...HEADERS, ...(init.headers || {}) } })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`)
      return data
    }

    // ── styles: scoped class names, colours taken from the host theme where it exposes them ──
    const CSS = `
.sb-btn{display:inline-flex;align-items:center;gap:4px;height:28px;padding:0 8px;border-radius:8px;border:1px solid transparent;background:transparent;color:inherit;opacity:.8;cursor:pointer;font:inherit;font-size:12px}
.sb-btn:hover,.sb-btn[aria-pressed=true]{opacity:1;background:rgba(127,127,127,.16)}
.sb-panel{position:fixed;right:20px;bottom:20px;width:400px;max-width:calc(100vw - 40px);height:min(620px,calc(100vh - 40px));z-index:60;display:flex;flex-direction:column;border-radius:14px;border:1px solid rgba(127,127,127,.28);background:var(--dsh-sb-bg,#1c1c1f);color:var(--dsh-sb-fg,#e8e8ea);box-shadow:0 18px 48px rgba(0,0,0,.45);font:13px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;overflow:hidden}
@media (prefers-color-scheme: light){.sb-panel{--dsh-sb-bg:#fff;--dsh-sb-fg:#1d1d1f}}
.sb-head{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid rgba(127,127,127,.2)}
.sb-head b{flex:1;font-size:14px}
.sb-x{border:0;background:transparent;color:inherit;font-size:18px;line-height:1;cursor:pointer;opacity:.7}
.sb-tabs{display:flex;gap:4px;padding:8px 14px 0}
.sb-tab{flex:1;padding:6px;border-radius:8px;border:0;background:transparent;color:inherit;cursor:pointer;opacity:.7;font:inherit}
.sb-tab[aria-selected=true]{background:rgba(127,127,127,.18);opacity:1}
.sb-body{flex:1;overflow:auto;padding:10px 14px 14px}
.sb-input,.sb-area{width:100%;box-sizing:border-box;padding:8px 10px;border-radius:8px;border:1px solid rgba(127,127,127,.3);background:rgba(127,127,127,.08);color:inherit;font:inherit}
.sb-area{min-height:160px;resize:vertical}
.sb-tags{display:flex;flex-wrap:wrap;gap:4px;margin:8px 0}
.sb-chip{padding:1px 8px;border-radius:999px;border:1px solid rgba(127,127,127,.3);background:transparent;color:inherit;font-size:11px;cursor:pointer}
.sb-chip[aria-pressed=true]{background:#4d6bfe;border-color:#4d6bfe;color:#fff}
.sb-item{display:block;width:100%;text-align:left;padding:8px 10px;margin:4px 0;border-radius:8px;border:1px solid rgba(127,127,127,.18);background:transparent;color:inherit;cursor:pointer;font:inherit}
.sb-item:hover{background:rgba(127,127,127,.1)}
.sb-meta{opacity:.6;font-size:11px}
.sb-snip{opacity:.8;font-size:12px;margin-top:2px}
.sb-note h4{margin:10px 0 4px;font-size:13px}
.sb-note p,.sb-note li{margin:3px 0;white-space:pre-wrap;word-break:break-word}
.sb-link{color:#6d8cff;cursor:pointer;text-decoration:underline;background:none;border:0;padding:0;font:inherit}
.sb-save{margin-top:8px;padding:8px 14px;border-radius:8px;border:0;background:#4d6bfe;color:#fff;cursor:pointer;font:inherit}
.sb-err{color:#ff6b6b;font-size:12px;margin:6px 0}
`

    function BrainIcon({ size = 16 }) {
      return h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true },
        h('path', { d: 'M9.5 3a3 3 0 0 0-3 3v.2A3 3 0 0 0 4 9.2a3 3 0 0 0 .6 4.6A3 3 0 0 0 7 18.5 2.5 2.5 0 0 0 12 19V5.5A2.5 2.5 0 0 0 9.5 3Z' }),
        h('path', { d: 'M14.5 3a3 3 0 0 1 3 3v.2a3 3 0 0 1 2.5 3 3 3 0 0 1-.6 4.6 3 3 0 0 1-2.4 4.7A2.5 2.5 0 0 1 12 19' }))
    }

    /** Render a line, turning [[Title]] into a clickable link. Text stays text: no HTML injection. */
    function inline(line, onLink, keyBase) {
      const parts = line.split(/(\[\[[^\]]+\]\])/g)
      return parts.map((part, i) => {
        const m = /^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]$/.exec(part)
        if (!m) return part
        return h('button', { key: `${keyBase}-${i}`, className: 'sb-link', onClick: () => onLink(m[1].trim()) }, m[2] || m[1])
      })
    }

    function MarkdownLite({ body, onLink }) {
      return h('div', { className: 'sb-note' }, body.split('\n').map((line, i) => {
        if (/^#{1,6}\s/.test(line)) return h('h4', { key: i }, inline(line.replace(/^#+\s*/, ''), onLink, i))
        if (/^\s*[-*]\s/.test(line)) return h('li', { key: i }, inline(line.replace(/^\s*[-*]\s/, ''), onLink, i))
        if (!line.trim()) return null
        return h('p', { key: i }, inline(line, onLink, i))
      }))
    }

    const slug = t => String(t).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')

    function Panel() {
      const isOpen = useOpen()
      const [tab, setTab] = useState('browse')
      const [query, setQuery] = useState('')
      const [tag, setTag] = useState('')
      const [data, setData] = useState(null)
      const [note, setNote] = useState(null)
      const [error, setError] = useState('')
      const [draft, setDraft] = useState({ title: '', tags: '', content: '' })

      const refresh = useCallback(async () => {
        try {
          const qs = new URLSearchParams()
          if (query.trim()) qs.set('q', query.trim())
          if (tag) qs.set('tag', tag)
          setData(await api(qs.toString() ? `?${qs}` : ''))
          setError('')
        } catch (e) { setError(String(e.message || e)) }
      }, [query, tag])

      // Poll while open so a note the agent captures mid-conversation shows up live.
      useEffect(() => {
        if (!isOpen) return undefined
        const first = setTimeout(refresh, query ? 200 : 0)
        const timer = setInterval(refresh, 4000)
        return () => { clearTimeout(first); clearInterval(timer) }
      }, [isOpen, refresh, query])

      const openNote = useCallback(async id => {
        try { setNote(await api(`/${encodeURIComponent(id)}`)); setError('') } catch (e) { setError(`${id}: ${e.message}`) }
      }, [])

      const save = useCallback(async () => {
        try {
          const r = await api('', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(draft) })
          setDraft({ title: '', tags: '', content: '' })
          setTab('browse')
          await openNote(r.id)
          await refresh()
        } catch (e) { setError(String(e.message || e)) }
      }, [draft, openNote, refresh])

      if (!isOpen) return null
      const count = !data ? ''
        : data.mode === 'overview' ? `${data.total} note${data.total === 1 ? '' : 's'}`
        : `${data.results.length} match${data.results.length === 1 ? '' : 'es'}`

      let body
      if (tab === 'capture') {
        body = h('div', null,
          h('input', { className: 'sb-input', placeholder: 'Title', value: draft.title, onChange: e => setDraft({ ...draft, title: e.target.value }) }),
          h('div', { style: { height: 6 } }),
          h('input', { className: 'sb-input', placeholder: 'Tags (comma separated)', value: draft.tags, onChange: e => setDraft({ ...draft, tags: e.target.value }) }),
          h('div', { style: { height: 6 } }),
          h('textarea', { className: 'sb-area', placeholder: 'What should your future self remember? Use [[Note Title]] to link.', value: draft.content, onChange: e => setDraft({ ...draft, content: e.target.value }) }),
          h('button', { className: 'sb-save', onClick: save, disabled: !draft.title.trim() || !draft.content.trim() }, 'Save to brain'))
      } else if (note) {
        body = h('div', null,
          h('button', { className: 'sb-link', onClick: () => setNote(null) }, '< back'),
          h('h3', { style: { margin: '8px 0 2px' } }, note.title),
          h('div', { className: 'sb-meta' }, `${note.tags.map(t => `#${t}`).join(' ')}  ·  updated ${String(note.updated).slice(0, 16).replace('T', ' ')}`),
          h(MarkdownLite, { body: note.body, onLink: title => openNote(slug(title)) }),
          h('div', { className: 'sb-meta', style: { marginTop: 12 } }, `Linked from (${note.backlinks.length})`),
          note.backlinks.map(b => h('button', { key: b.id, className: 'sb-item', onClick: () => openNote(b.id) }, b.title)))
      } else {
        const items = !data ? [] : data.mode === 'search' ? data.results : data.notes
        body = h('div', null,
          h('input', { className: 'sb-input', placeholder: 'Search your brain (BM25)…', value: query, onChange: e => setQuery(e.target.value), autoFocus: true }),
          data && data.tags ? h('div', { className: 'sb-tags' }, data.tags.slice(0, 10).map(t => h('button', { key: t.name, className: 'sb-chip', 'aria-pressed': tag === t.name, onClick: () => setTag(tag === t.name ? '' : t.name) }, `#${t.name} ${t.count}`))) : null,
          items.length === 0 && data ? h('div', { className: 'sb-meta', style: { marginTop: 10 } }, query ? 'No matches.' : 'Empty so far. Ask the agent to remember something, or use Capture.') : null,
          items.map(n => h('button', { key: n.id, className: 'sb-item', onClick: () => openNote(n.id) },
            h('div', null, h('b', null, n.title)),
            n.snippet ? h('div', { className: 'sb-snip' }, n.snippet) : null,
            h('div', { className: 'sb-meta' }, `${n.tags.map(t => `#${t}`).join(' ')}${n.score !== undefined ? `  ·  score ${n.score}` : ''}`))))
      }

      return h('section', { className: 'sb-panel', role: 'dialog', 'aria-label': 'Second Brain' },
        h('div', { className: 'sb-head' }, h(BrainIcon, { size: 18 }), h('b', null, 'Second Brain'), h('span', { className: 'sb-meta' }, count),
          h('button', { className: 'sb-x', 'aria-label': 'Close', onClick: () => store.set(false) }, '×')),
        h('div', { className: 'sb-tabs', role: 'tablist' },
          h('button', { className: 'sb-tab', role: 'tab', 'aria-selected': tab === 'browse', onClick: () => setTab('browse') }, 'Browse'),
          h('button', { className: 'sb-tab', role: 'tab', 'aria-selected': tab === 'capture', onClick: () => setTab('capture') }, 'Capture')),
        error ? h('div', { className: 'sb-err', style: { padding: '0 14px' } }, error) : null,
        h('div', { className: 'sb-body' }, body))
    }

    function ToggleButton() {
      const isOpen = useOpen()
      return h('button', { type: 'button', className: 'sb-btn', title: 'Second Brain (Ctrl/Cmd+Shift+B)', 'aria-pressed': isOpen, onClick: () => store.set(v => !v) },
        h(BrainIcon), h('span', null, 'Brain'))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        // Styles and the shortcut are effects: unloading the plugin removes both.
        ctx.effect(() => {
          const style = document.createElement('style')
          style.id = 'dsh-second-brain-style'
          style.textContent = CSS
          document.head.appendChild(style)
          return () => style.remove()
        }, 'second-brain: styles')
        ctx.effect(() => {
          const onKey = e => {
            if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'b') { e.preventDefault(); store.set(v => !v) }
          }
          window.addEventListener('keydown', onKey)
          return () => window.removeEventListener('keydown', onKey)
        }, 'second-brain: shortcut')

        ctx.slots.inject('conversation.input.right', () => ctx.slots.register(
          { name: 'conversation.input.right', id: 'second-brain-toggle', order: 80, label: 'Second Brain' }, ToggleButton))
        ctx.slots.inject('shell.overlay', () => ctx.slots.register(
          { name: 'shell.overlay', id: 'second-brain-panel', order: 50 }, Panel))
      },
    }
  },
})
