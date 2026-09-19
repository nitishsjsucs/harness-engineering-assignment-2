/**
 * The Second Brain vault: plain Markdown files with YAML front matter and
 * [[wikilinks]], so the same folder opens as an Obsidian vault.
 *
 * This module knows nothing about DeepSeek Harness. The Host tools (index.js),
 * the HTTP API (web.js) and the tests all call these functions, which keeps
 * the harness-specific code thin and the storage logic testable with plain
 * `node --test`.
 */
import { mkdir, readdir, readFile, writeFile, stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

/** Where notes live when the plugin row sets no `vaultDir`. */
export function defaultVaultDir() {
  const dshHome = process.env.DSH_HOME || join(homedir(), '.dsh')
  return join(dshHome, 'second-brain')
}

// ── ids and parsing ─────────────────────────────────────────────────────────

/** A stable, filesystem-safe id derived from a title: "Attention Is All You Need" -> "attention-is-all-you-need". */
export function slugify(title) {
  const slug = String(title)
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
  return slug || 'note'
}

/** Ids come from the model and from HTTP callers, so never let one escape the vault. */
function assertSafeId(id) {
  if (typeof id !== 'string' || !/^[a-z0-9][a-z0-9-]*$/.test(id)) {
    throw new Error(`invalid note id "${id}": expected lowercase letters, digits and dashes`)
  }
}

/** Split `---\nfront matter\n---\nbody`. The front matter is a tiny YAML subset we write ourselves. */
export function parseNote(text) {
  const meta = {}
  let body = text
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text)
  if (match) {
    body = text.slice(match[0].length)
    for (const line of match[1].split(/\r?\n/)) {
      const kv = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
      if (!kv) continue
      const [, key, raw] = kv
      if (raw.startsWith('[') && raw.endsWith(']')) {
        meta[key] = raw.slice(1, -1).split(',').map(s => unquote(s.trim())).filter(Boolean)
      } else {
        meta[key] = unquote(raw.trim())
      }
    }
  }
  return { meta, body: body.replace(/^\s+/, '') }
}

function unquote(s) {
  return s.length >= 2 && ((s[0] === '"' && s.at(-1) === '"') || (s[0] === "'" && s.at(-1) === "'")) ? s.slice(1, -1) : s
}

function quote(s) {
  return /[:#[\],"']|^\s|\s$/.test(s) ? JSON.stringify(s) : s
}

export function serializeNote(meta, body) {
  const lines = ['---']
  for (const [key, value] of Object.entries(meta)) {
    if (value === undefined || value === null || value === '') continue
    lines.push(Array.isArray(value) ? `${key}: [${value.map(quote).join(', ')}]` : `${key}: ${quote(String(value))}`)
  }
  lines.push('---', '', body.trimEnd(), '')
  return lines.join('\n')
}

/** Every [[Target]] or [[Target|alias]] in a body, as the target note ids. */
export function extractLinks(body) {
  const ids = new Set()
  for (const m of body.matchAll(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]/g)) ids.add(slugify(m[1].trim()))
  return [...ids]
}

/** "ml, papers , Transformers" or ["ml"] -> ["ml","papers","transformers"]. */
export function normalizeTags(tags) {
  const list = Array.isArray(tags) ? tags : String(tags ?? '').split(',')
  return [...new Set(list.map(t => String(t).trim().toLowerCase().replace(/^#/, '').replace(/\s+/g, '-')).filter(Boolean))]
}

// ── search ──────────────────────────────────────────────────────────────────

const STOPWORDS = new Set('a an and are as at be by for from has have in is it its of on or that the to was were will with this what how why when which'.split(' '))

export function tokenize(text) {
  return String(text).toLowerCase().split(/[^a-z0-9]+/).filter(t => t.length > 1 && !STOPWORDS.has(t))
}

/**
 * Okapi BM25 over title + tags + body. Title and tag terms are repeated so a
 * match there outranks a passing mention in the body — the cheap version of
 * field boosting. No index is kept on disk: a personal vault is small, and
 * rebuilding per query means an edit made in Obsidian is visible immediately.
 */
export function rank(notes, query, { k1 = 1.4, b = 0.75 } = {}) {
  const terms = [...new Set(tokenize(query))]
  if (terms.length === 0) return []
  const docs = notes.map(n => {
    const tokens = [...tokenize(n.title), ...tokenize(n.title), ...n.tags.flatMap(t => [t, t]), ...tokenize(n.body)]
    const tf = new Map()
    for (const t of tokens) tf.set(t, (tf.get(t) ?? 0) + 1)
    return { note: n, tf, length: tokens.length }
  })
  const avgLength = docs.reduce((s, d) => s + d.length, 0) / Math.max(docs.length, 1)
  const df = new Map(terms.map(t => [t, docs.filter(d => d.tf.has(t)).length]))
  const scored = []
  for (const d of docs) {
    let score = 0
    for (const t of terms) {
      const f = d.tf.get(t)
      if (!f) continue
      const idf = Math.log(1 + (docs.length - df.get(t) + 0.5) / (df.get(t) + 0.5))
      score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (d.length / avgLength)))
    }
    if (score > 0) scored.push({ note: d.note, score })
  }
  return scored.sort((x, y) => y.score - x.score)
}

/** A short excerpt around the first query term, so results explain why they matched. */
export function snippet(body, query, width = 160) {
  const flat = body.replace(/\s+/g, ' ').trim()
  const lower = flat.toLowerCase()
  const hit = tokenize(query).map(t => lower.indexOf(t)).filter(i => i >= 0).sort((a, b) => a - b)[0] ?? 0
  const start = Math.max(0, hit - Math.floor(width / 3))
  return (start > 0 ? '…' : '') + flat.slice(start, start + width) + (start + width < flat.length ? '…' : '')
}

// ── the vault ───────────────────────────────────────────────────────────────

export class Vault {
  constructor(dir = defaultVaultDir()) {
    this.dir = resolve(dir)
  }

  pathOf(id) {
    assertSafeId(id)
    return join(this.dir, `${id}.md`)
  }

  async ensure() {
    await mkdir(this.dir, { recursive: true })
  }

  /** Every note in the vault, newest first. Files we cannot parse are skipped, not fatal. */
  async all() {
    await this.ensure()
    const names = (await readdir(this.dir)).filter(n => n.endsWith('.md'))
    const notes = []
    for (const name of names) {
      const id = name.slice(0, -3)
      if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) continue
      try {
        notes.push(await this.read(id))
      } catch {
        // A half-written or hand-mangled file should not take the whole vault down.
      }
    }
    return notes.sort((a, b) => String(b.updated).localeCompare(String(a.updated)))
  }

  async read(id) {
    const path = this.pathOf(id)
    const text = await readFile(path, 'utf8')
    const { meta, body } = parseNote(text)
    const info = await stat(path)
    return {
      id,
      title: meta.title || id,
      tags: normalizeTags(meta.tags ?? []),
      created: meta.created || info.birthtime.toISOString(),
      updated: meta.updated || info.mtime.toISOString(),
      source: meta.source || '',
      body,
      links: extractLinks(body),
      path,
    }
  }

  async exists(id) {
    try {
      await stat(this.pathOf(id))
      return true
    } catch {
      return false
    }
  }

  /**
   * Save a thought. A new title creates a note; an existing title APPENDS a
   * dated section instead of overwriting, because a second brain should never
   * lose what it already knew.
   */
  async capture({ title, content, tags = [], source = '' }, now = new Date()) {
    if (!String(title ?? '').trim()) throw new Error('title must not be empty')
    if (!String(content ?? '').trim()) throw new Error('content must not be empty')
    await this.ensure()
    const id = slugify(title)
    const stamp = now.toISOString()
    const newTags = normalizeTags(tags)
    if (await this.exists(id)) {
      const old = await this.read(id)
      const body = `${old.body.trimEnd()}\n\n## Update ${stamp.slice(0, 10)}\n\n${String(content).trim()}\n`
      const merged = normalizeTags([...old.tags, ...newTags])
      await writeFile(this.pathOf(id), serializeNote({ title: old.title, tags: merged, created: old.created, updated: stamp, source: old.source || source }, body))
      return { id, created: false, note: await this.read(id) }
    }
    const meta = { title: String(title).trim(), tags: newTags, created: stamp, updated: stamp, source }
    await writeFile(this.pathOf(id), serializeNote(meta, String(content).trim()))
    return { id, created: true, note: await this.read(id) }
  }

  /** Notes whose body links to `id` — the part of a knowledge graph plain folders lack. */
  async backlinks(id, notes) {
    const all = notes ?? (await this.all())
    return all.filter(n => n.id !== id && n.links.includes(id)).map(n => ({ id: n.id, title: n.title }))
  }

  /** Append a [[link]] from one note to another, creating nothing new. */
  async link(fromId, toId, reason = '') {
    const from = await this.read(fromId)
    const to = await this.read(toId)
    if (from.links.includes(toId)) return { changed: false, from: from.id, to: to.id }
    const line = `- Related: [[${to.title}]]${reason ? ` — ${reason.trim()}` : ''}`
    const body = /\n## Related\n/.test(`\n${from.body}`) ? `${from.body.trimEnd()}\n${line}\n` : `${from.body.trimEnd()}\n\n## Related\n\n${line}\n`
    await writeFile(from.path, serializeNote({ title: from.title, tags: from.tags, created: from.created, updated: new Date().toISOString(), source: from.source }, body))
    return { changed: true, from: from.id, to: to.id }
  }

  async search(query, limit = 8) {
    const notes = await this.all()
    return rank(notes, query).slice(0, limit).map(({ note, score }) => ({
      id: note.id,
      title: note.title,
      tags: note.tags,
      score: Math.round(score * 100) / 100,
      snippet: snippet(note.body, query),
      updated: note.updated,
    }))
  }

  /** Recent notes plus a tag histogram: the "what's in my head" overview. */
  async overview({ tag = '', limit = 20 } = {}) {
    const notes = await this.all()
    const wanted = normalizeTags([tag])[0]
    const filtered = wanted ? notes.filter(n => n.tags.includes(wanted)) : notes
    const tagCounts = {}
    for (const n of notes) for (const t of n.tags) tagCounts[t] = (tagCounts[t] ?? 0) + 1
    return {
      vault: this.dir,
      total: notes.length,
      tags: Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count })),
      notes: filtered.slice(0, limit).map(n => ({ id: n.id, title: n.title, tags: n.tags, updated: n.updated, links: n.links.length })),
    }
  }
}
