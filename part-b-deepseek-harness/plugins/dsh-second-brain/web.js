/**
 * dsh-second-brain — Host half, part 2: a tiny JSON API for the browser panel.
 *
 * It is a separate plugin row (see cordis.patch.yml) because it needs the
 * `webServer` service, which only the Web profile provides. Splitting it out
 * means the tools in index.js still load in a headless or TUI profile.
 *
 * Routes (same origin as the DSH Web UI):
 *   GET  /second-brain/api/notes?q=&tag=&limit=   search or overview
 *   GET  /second-brain/api/notes/<id>            one note + backlinks
 *   POST /second-brain/api/notes                 capture {title, content, tags}
 *
 * The routes sit outside DSH's token-guarded /api, so they defend themselves:
 * a loopback Host header (defeats DNS rebinding) and a custom request header
 * (a cross-origin page cannot send one without a CORS preflight, which this
 * API never approves).
 */
import Schema from '@deepseek-ai/schemastery'
import { Vault, defaultVaultDir } from './lib/vault.js'

export const name = 'dsh-second-brain-web'
export const inject = ['webServer']

export const Config = Schema.object({
  vaultDir: Schema.string().default('').description('Must match the tools row so both halves see the same vault.'),
  routePrefix: Schema.string().default('/second-brain').description('URL prefix of the JSON API.'),
})

const LOOPBACK = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/i
const MAX_BODY = 256 * 1024

function send(res, status, value) {
  const body = JSON.stringify(value)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'content-length': Buffer.byteLength(body) })
  res.end(body)
}

async function readJson(req) {
  let size = 0
  const chunks = []
  for await (const chunk of req) {
    size += chunk.length
    if (size > MAX_BODY) throw Object.assign(new Error('request body too large'), { status: 413 })
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
}

export function apply(ctx, config) {
  const vault = new Vault(config.vaultDir || defaultVaultDir())
  const prefix = config.routePrefix.replace(/\/+$/, '')
  const api = `${prefix}/api/notes`

  async function handle(req, res) {
    if (!LOOPBACK.test(req.headers.host ?? '')) return send(res, 403, { error: 'loopback only' })
    if (req.headers['x-second-brain'] !== '1') return send(res, 403, { error: 'missing x-second-brain header' })

    const url = new URL(req.url ?? '/', 'http://localhost')
    try {
      if (req.method === 'GET' && url.pathname === api) {
        const q = url.searchParams.get('q')?.trim()
        const limit = Math.min(Number(url.searchParams.get('limit')) || 30, 100)
        if (q) return send(res, 200, { mode: 'search', results: await vault.search(q, limit) })
        return send(res, 200, { mode: 'overview', ...(await vault.overview({ tag: url.searchParams.get('tag') ?? '', limit })) })
      }
      if (req.method === 'GET' && url.pathname.startsWith(`${api}/`)) {
        const id = decodeURIComponent(url.pathname.slice(api.length + 1))
        const note = await vault.read(id)
        return send(res, 200, { ...note, path: undefined, backlinks: await vault.backlinks(id) })
      }
      if (req.method === 'POST' && url.pathname === api) {
        const body = await readJson(req)
        const result = await vault.capture({ title: body.title, content: body.content, tags: body.tags ?? '', source: 'dsh-web-panel' })
        return send(res, 201, { id: result.id, created: result.created })
      }
      return send(res, 404, { error: 'not found' })
    } catch (error) {
      const status = error.status ?? (error.code === 'ENOENT' ? 404 : 400)
      return send(res, status, { error: error.message })
    }
  }

  // register() returns a disposer; handing it to ctx.effect removes the route on unload.
  ctx.effect(() => ctx.webServer.register({ kind: 'prefix', path: prefix, handler: handle }), 'second-brain: http api')
}
