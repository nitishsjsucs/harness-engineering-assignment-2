/**
 * dsh-dino-break — a T-rex runner that floats in the bottom-right corner of
 * the DSH Web UI, for the minutes while the agent works.
 *
 *   conversation.input.right  toggle button in the composer tool row
 *   shell.overlay             the floating game card (canvas)
 *
 * Game loop: requestAnimationFrame with a fixed-step update (so speed does not
 * depend on the monitor's refresh rate), axis-aligned hitboxes, and a speed
 * that ramps with the score. Keys are read from the canvas only, so pressing
 * Space in the composer never makes the dino jump.
 */
window.__ModuleLoader__.load({
  id: 'dsh-dino-break',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useEffect, useRef, useSyncExternalStore } = React

    // ── shared open/closed store ────────────────────────────────────────────
    let open = false
    const listeners = new Set()
    const store = {
      get: () => open,
      set(next) { open = typeof next === 'function' ? next(open) : next; listeners.forEach(fn => fn()) },
      subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    }
    const useOpen = () => useSyncExternalStore(store.subscribe, store.get, store.get)

    // ── sprites: 1 = filled pixel. Drawn at PX canvas pixels per sprite pixel ──
    const PX = 2
    const DINO_BODY = [
      '..........######.',
      '.........##.#####',
      '.........########',
      '.........########',
      '.........####....',
      '.........#######.',
      '#.......#####....',
      '#.....#######....',
      '##...#########...',
      '###.##########...',
      '.############....',
      '..###########....',
      '...#########.....',
      '....#######......',
    ]
    const DINO_LEGS = [
      ['.....##..##......', '.....#....#......', '.....##...##.....'],
      ['.....##...#......', '.....#....##.....', '.....##..........'],
      ['.....#....##.....', '.....##...#......', '..........##.....'],
    ]
    const CACTUS = [
      '...##...',
      '..####..',
      '#.####..',
      '#.####.#',
      '#.####.#',
      '######.#',
      '.#######',
      '..####..',
      '..####..',
      '..####..',
      '..####..',
      '..####..',
    ]
    const BIRD = [
      ['....#.......', '...##.......', '..########..', '.##########.', '#...######..', '.....###....'],
      ['.....###....', '#...######..', '.##########.', '..########..', '...##.......', '....#.......'],
    ]

    function drawSprite(g, rows, x, y) {
      for (let r = 0; r < rows.length; r++) {
        for (let c = 0; c < rows[r].length; c++) {
          if (rows[r][c] === '#') g.fillRect(Math.round(x + c * PX), Math.round(y + r * PX), PX, PX)
        }
      }
    }

    // ── the game, independent of React ──────────────────────────────────────
    const W = 600, H = 170, GROUND = 140, STEP = 1000 / 60
    const HI_KEY = 'dsh-dino-break:hi'

    function readHi() { try { return Number(localStorage.getItem(HI_KEY)) || 0 } catch { return 0 } }
    function writeHi(v) { try { localStorage.setItem(HI_KEY, String(v)) } catch { /* private mode */ } }

    function createGame(canvas) {
      const g = canvas.getContext('2d')
      const dino = { x: 40, y: 0, vy: 0, w: 17 * PX, h: 17 * PX }
      let state, obstacles, clouds, speed, score, hi = readHi(), frame, spawnIn, raf = 0, last = 0, acc = 0

      function reset() {
        state = 'ready'
        obstacles = []
        clouds = [{ x: 420, y: 30 }, { x: 180, y: 55 }]
        speed = 5
        score = 0
        frame = 0
        spawnIn = 60
        dino.y = GROUND - dino.h
        dino.vy = 0
      }

      function jump() {
        if (state === 'over') { reset(); state = 'running'; return }
        if (state === 'ready') state = 'running'
        if (dino.y >= GROUND - dino.h - 0.5) dino.vy = -11.5
      }

      function spawn() {
        const flyer = score > 250 && Math.random() < 0.3
        if (flyer) {
          const high = Math.random() < 0.5
          obstacles.push({ kind: 'bird', x: W + 10, y: high ? GROUND - 64 : GROUND - 34, w: 12 * PX, h: 6 * PX })
        } else {
          const n = 1 + Math.floor(Math.random() * Math.min(3, 1 + score / 200))
          for (let i = 0; i < n; i++) obstacles.push({ kind: 'cactus', x: W + 10 + i * 18, y: GROUND - 12 * PX, w: 8 * PX, h: 12 * PX })
        }
        // Gap shrinks as speed rises but never below what a jump can clear.
        spawnIn = Math.max(38, 70 + Math.random() * 60 - speed * 3)
      }

      function hits(a, b) {
        const pad = 4 // forgive the sprite's transparent corners
        return a.x + pad < b.x + b.w && a.x + a.w - pad > b.x && a.y + pad < b.y + b.h && a.y + a.h - pad > b.y
      }

      function update() {
        if (state !== 'running') return
        frame++
        dino.vy += 0.62
        dino.y = Math.min(GROUND - dino.h, dino.y + dino.vy)
        if (dino.y >= GROUND - dino.h) dino.vy = 0
        for (const o of obstacles) o.x -= speed * (o.kind === 'bird' ? 1.15 : 1)
        obstacles = obstacles.filter(o => o.x + o.w > -10)
        for (const c of clouds) c.x -= speed * 0.2
        if (clouds[0] && clouds[0].x < -60) clouds.shift()
        if (clouds.length < 3 && Math.random() < 0.01) clouds.push({ x: W + 20, y: 20 + Math.random() * 50 })
        if (--spawnIn <= 0) spawn()
        score += speed / 12
        speed = Math.min(13, 5 + score / 180)
        for (const o of obstacles) {
          if (hits(dino, o)) {
            state = 'over'
            if (Math.floor(score) > hi) { hi = Math.floor(score); writeHi(hi) }
          }
        }
      }

      function draw() {
        const dark = matchMedia('(prefers-color-scheme: dark)').matches
        const ink = dark ? '#b8bcc4' : '#535353'
        g.clearRect(0, 0, W, H)
        g.fillStyle = dark ? 'rgba(184,188,196,.25)' : 'rgba(83,83,83,.2)'
        for (const c of clouds) { g.fillRect(c.x, c.y, 38, 6); g.fillRect(c.x + 8, c.y - 5, 20, 5) }
        g.fillStyle = ink
        g.fillRect(0, GROUND, W, 2)
        for (let i = 0; i < 12; i++) g.fillRect((i * 57 - (frame * speed) % 57 + W) % W, GROUND + 6 + (i % 3) * 3, 3 + (i % 2) * 2, 2)
        const legs = state === 'running' && dino.y >= GROUND - dino.h - 0.5 ? DINO_LEGS[1 + (Math.floor(frame / 6) % 2)] : DINO_LEGS[0]
        drawSprite(g, DINO_BODY.concat(legs), dino.x, dino.y)
        for (const o of obstacles) drawSprite(g, o.kind === 'bird' ? BIRD[Math.floor(frame / 12) % 2] : CACTUS, o.x, o.y)
        g.font = '600 14px ui-monospace, SFMono-Regular, Menlo, monospace'
        g.textAlign = 'right'
        g.fillText(`HI ${String(hi).padStart(5, '0')}  ${String(Math.floor(score)).padStart(5, '0')}`, W - 12, 22)
        g.textAlign = 'center'
        if (state === 'ready') g.fillText('Press Space / click to start', W / 2, 70)
        if (state === 'over') { g.fillText('G A M E   O V E R', W / 2, 62); g.fillText('Space / click to restart', W / 2, 84) }
      }

      function loop(t) {
        // Fixed-step physics: identical game speed on 60 Hz and 120 Hz screens.
        acc += Math.min(100, t - (last || t))
        last = t
        while (acc >= STEP) { update(); acc -= STEP }
        draw()
        raf = requestAnimationFrame(loop)
      }

      reset()
      raf = requestAnimationFrame(loop)
      return { jump, stop: () => cancelAnimationFrame(raf) }
    }

    // ── React views ─────────────────────────────────────────────────────────
    const CSS = `
.dino-btn{display:inline-flex;align-items:center;gap:4px;height:28px;padding:0 8px;border-radius:8px;border:1px solid transparent;background:transparent;color:inherit;opacity:.8;cursor:pointer;font:inherit;font-size:12px}
.dino-btn:hover,.dino-btn[aria-pressed=true]{opacity:1;background:rgba(127,127,127,.16)}
.dino-card{position:fixed;right:16px;bottom:16px;z-index:61;width:380px;max-width:calc(100vw - 32px);border-radius:14px;border:1px solid rgba(127,127,127,.28);background:var(--dino-bg,#1c1c1f);color:var(--dino-fg,#e8e8ea);box-shadow:0 18px 48px rgba(0,0,0,.4);font:12px system-ui,-apple-system,sans-serif;overflow:hidden}
@media (prefers-color-scheme: light){.dino-card{--dino-bg:#fff;--dino-fg:#1d1d1f}}
.dino-head{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;opacity:.85}
.dino-x{border:0;background:transparent;color:inherit;font-size:16px;cursor:pointer}
.dino-canvas{display:block;width:100%;height:auto;outline:none;cursor:pointer}
.dino-canvas:focus-visible{box-shadow:inset 0 0 0 2px #4d6bfe}
`

    function DinoIcon() {
      return h('svg', { width: 16, height: 16, viewBox: '0 0 17 17', fill: 'currentColor', 'aria-hidden': true },
        DINO_BODY.concat(DINO_LEGS[0]).flatMap((row, r) => [...row].map((ch, c) => ch === '#' ? h('rect', { key: `${r}-${c}`, x: c, y: r, width: 1, height: 1 }) : null)))
    }

    function Game() {
      const isOpen = useOpen()
      const canvasRef = useRef(null)
      const gameRef = useRef(null)

      useEffect(() => {
        if (!isOpen || !canvasRef.current) return undefined
        const canvas = canvasRef.current
        canvas.width = W
        canvas.height = H
        gameRef.current = createGame(canvas)
        canvas.focus()
        // Unmounting (closing the card) stops the animation frame: no hidden CPU use.
        return () => gameRef.current && gameRef.current.stop()
      }, [isOpen])

      if (!isOpen) return null
      const onKey = e => {
        if (e.code === 'Space' || e.code === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); gameRef.current && gameRef.current.jump() }
        if (e.code === 'Escape') store.set(false)
      }
      return h('section', { className: 'dino-card', role: 'dialog', 'aria-label': 'Dino Break game' },
        h('div', { className: 'dino-head' }, h('span', null, 'Dino Break — play while the agent works'),
          h('button', { className: 'dino-x', 'aria-label': 'Close', onClick: () => store.set(false) }, '×')),
        h('canvas', { ref: canvasRef, className: 'dino-canvas', tabIndex: 0, onKeyDown: onKey, onPointerDown: () => { canvasRef.current.focus(); gameRef.current && gameRef.current.jump() } }))
    }

    function ToggleButton() {
      const isOpen = useOpen()
      return h('button', { type: 'button', className: 'dino-btn', title: 'Dino Break', 'aria-pressed': isOpen, onClick: () => store.set(v => !v) },
        h(DinoIcon), h('span', null, 'Break'))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.effect(() => {
          const style = document.createElement('style')
          style.id = 'dsh-dino-break-style'
          style.textContent = CSS
          document.head.appendChild(style)
          return () => style.remove()
        }, 'dino-break: styles')
        ctx.slots.inject('conversation.input.right', () => ctx.slots.register(
          { name: 'conversation.input.right', id: 'dino-break-toggle', order: 85, label: 'Dino Break' }, ToggleButton))
        ctx.slots.inject('shell.overlay', () => ctx.slots.register(
          { name: 'shell.overlay', id: 'dino-break-game', order: 60 }, Game))
      },
    }
  },
})
