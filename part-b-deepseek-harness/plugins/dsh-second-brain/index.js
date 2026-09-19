/**
 * dsh-second-brain — Host half, part 1: the model-facing tools.
 *
 * Five tools let the agent keep a durable, linked memory outside any one
 * session: capture, search, read (with backlinks), list, link. A short system
 * prompt section tells the agent WHEN to use them, because a tool the model
 * never thinks to call is dead weight.
 *
 * Everything registered through `ctx` is an effect: unloading the plugin
 * (dsh plugin remove, or a config edit under HMR) unregisters the tools and
 * the prompt section with no cleanup code here.
 */
import { defineTool } from '@deepseek-ai/dsh-tools'
import Schema from '@deepseek-ai/schemastery'
import { Vault, defaultVaultDir } from './lib/vault.js'

export const name = 'dsh-second-brain'
export const inject = ['tools', 'systemPrompt']

export const Config = Schema.object({
  vaultDir: Schema.string().default('').description('Folder holding the Markdown notes. Empty means $DSH_HOME/second-brain.'),
  promptSection: Schema.boolean().default(true).description('Add usage guidance for the brain tools to every system prompt.'),
  searchLimit: Schema.number().default(8).description('Default number of search results.'),
})

const GUIDANCE = `You have a Second Brain: a persistent Markdown vault (Obsidian-compatible) that outlives this session.
- Before answering questions about the user's past projects, decisions, preferences or earlier findings, call brain_search first.
- When the user says "remember", states a durable preference or decision, or a task produces a reusable insight, call brain_capture with a specific title, concise content and 1-4 tags.
- Connect related ideas with [[Note Title]] wikilinks inside captured content, or with brain_link.
- Cite notes you relied on by title. Never invent note contents: read them with brain_read.`

/** Render helper: every tool returns a JSON value for programs and a readable text for the model. */
const text = s => [{ type: 'text', text: s }]

export function apply(ctx, config) {
  const vault = new Vault(config.vaultDir || defaultVaultDir())
  const limitDefault = Math.max(1, config.searchLimit ?? 8)

  if (config.promptSection) {
    ctx.systemPrompt.section({ name: 'plugin:second-brain', order: 9000, text: GUIDANCE, interpolate: false })
  }

  ctx.tools.register(defineTool({
    name: 'brain_capture',
    description: 'Save a note to the Second Brain. A new title creates a note; an existing title appends a dated update (nothing is ever overwritten). Use [[Other Note]] wikilinks in content to connect ideas.',
    parameters: {
      title: { type: 'string', required: true, description: 'Specific, reusable title, e.g. "LoRA rank ablation results"' },
      content: { type: 'string', required: true, description: 'Markdown body: the fact, decision or insight, with enough context to be useful months later' },
      tags: { type: 'string', description: 'Comma-separated tags, e.g. "ml, experiments"' },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, v) => text(`${v.created ? 'Created' : 'Updated'} note "${v.title}" (id: ${v.id}) in ${v.vault}. Tags: ${v.tags.join(', ') || 'none'}. Links: ${v.links.join(', ') || 'none'}.`),
    },
    async execute(args, exec) {
      const source = exec?.agent?.session?.id ? `dsh-session:${exec.agent.session.id}` : ''
      const { id, created, note } = await vault.capture({ title: args.title, content: args.content, tags: args.tags ?? '', source })
      return { id, created, title: note.title, tags: note.tags, links: note.links, vault: vault.dir }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'brain_search',
    description: 'Full-text search (BM25 ranking over title, tags and body) across the Second Brain. Returns ids, titles, scores and snippets.',
    parameters: {
      query: { type: 'string', required: true, description: 'Keywords to look for' },
      limit: { type: 'number', description: `Maximum results (default ${limitDefault})` },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (args, v) => text(v.results.length === 0
        ? `No notes match "${args.query}". The vault has ${v.total} notes.`
        : v.results.map((r, i) => `${i + 1}. ${r.title} (id: ${r.id}, score ${r.score}) [${r.tags.join(', ')}]\n   ${r.snippet}`).join('\n')),
    },
    async execute(args) {
      const limit = Math.min(Math.max(1, Math.floor(args.limit ?? limitDefault)), 50)
      const results = await vault.search(args.query, limit)
      const { total } = await vault.overview({ limit: 0 })
      return { results, total }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'brain_read',
    description: 'Read one Second Brain note in full, including its outgoing [[links]] and the notes that link back to it.',
    parameters: {
      id: { type: 'string', required: true, description: 'Note id from brain_search or brain_list (lowercase-dashed)' },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, v) => text(`# ${v.title}\nid: ${v.id} | tags: ${v.tags.join(', ') || 'none'} | updated: ${v.updated}\n\n${v.body}\n\nLinks to: ${v.links.join(', ') || 'none'}\nLinked from: ${v.backlinks.map(b => b.title).join(', ') || 'none'}`),
    },
    async execute(args) {
      const note = await vault.read(args.id)
      const backlinks = await vault.backlinks(note.id)
      return { id: note.id, title: note.title, tags: note.tags, updated: note.updated, body: note.body, links: note.links, backlinks }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'brain_list',
    description: 'Overview of the Second Brain: most recently updated notes and a tag histogram, optionally filtered by one tag.',
    parameters: {
      tag: { type: 'string', description: 'Only notes with this tag' },
      limit: { type: 'number', description: 'Maximum notes (default 20)' },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, v) => text(`${v.total} notes in ${v.vault}\nTags: ${v.tags.map(t => `${t.name}(${t.count})`).join(', ') || 'none'}\n\n${v.notes.map(n => `- ${n.title} (id: ${n.id}) [${n.tags.join(', ')}]`).join('\n')}`),
    },
    async execute(args) {
      return await vault.overview({ tag: args.tag ?? '', limit: Math.min(Math.max(1, Math.floor(args.limit ?? 20)), 100) })
    },
  }))

  ctx.tools.register(defineTool({
    name: 'brain_link',
    description: 'Connect two existing notes by appending a [[wikilink]] from one to the other under a "Related" heading.',
    parameters: {
      from: { type: 'string', required: true, description: 'Id of the note that gets the link' },
      to: { type: 'string', required: true, description: 'Id of the note being linked to' },
      reason: { type: 'string', description: 'One phrase explaining the relationship' },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, v) => text(v.changed ? `Linked ${v.from} -> ${v.to}.` : `${v.from} already links to ${v.to}.`),
    },
    async execute(args) {
      return await vault.link(args.from, args.to, args.reason ?? '')
    },
  }))
}
