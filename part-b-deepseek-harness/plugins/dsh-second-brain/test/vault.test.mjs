// Offline tests for the vault logic. Run: node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Vault, slugify, parseNote, serializeNote, extractLinks, normalizeTags, rank } from '../lib/vault.js'

async function withVault(fn) {
  const dir = await mkdtemp(join(tmpdir(), 'second-brain-'))
  try { await fn(new Vault(dir), dir) } finally { await rm(dir, { recursive: true, force: true }) }
}

test('slugify makes safe ids', () => {
  assert.equal(slugify('Attention Is All You Need!'), 'attention-is-all-you-need')
  assert.equal(slugify('   '), 'note')
})

test('front matter round-trips, including tags with odd characters', () => {
  const text = serializeNote({ title: 'A: B', tags: ['ml', 'c++'], created: '2026-09-19T00:00:00Z' }, 'Body [[Other]]')
  const { meta, body } = parseNote(text)
  assert.equal(meta.title, 'A: B')
  assert.deepEqual(meta.tags, ['ml', 'c++'])
  assert.equal(body.trim(), 'Body [[Other]]')
})

test('wikilinks and tags normalise', () => {
  assert.deepEqual(extractLinks('see [[LoRA Rank]] and [[Adam|the optimizer]] and [[LoRA Rank#results]]'), ['lora-rank', 'adam'])
  assert.deepEqual(normalizeTags(' ML, #papers ,deep learning'), ['ml', 'papers', 'deep-learning'])
})

test('capture creates, then appends instead of overwriting', () => withVault(async vault => {
  const first = await vault.capture({ title: 'Project Atlas', content: 'Uses PyTorch 2.', tags: 'work' }, new Date('2026-09-01T00:00:00Z'))
  assert.equal(first.created, true)
  const second = await vault.capture({ title: 'project atlas', content: 'Switched to JAX.', tags: 'jax' }, new Date('2026-09-02T00:00:00Z'))
  assert.equal(second.created, false)
  const note = await vault.read('project-atlas')
  assert.match(note.body, /Uses PyTorch 2\./)
  assert.match(note.body, /## Update 2026-09-02\s+Switched to JAX\./)
  assert.deepEqual(note.tags, ['work', 'jax'])
}))

test('search ranks title matches above body mentions', () => withVault(async vault => {
  await vault.capture({ title: 'Learning rate warmup', content: 'Linear warmup for 500 steps stabilised training.' })
  await vault.capture({ title: 'Groceries', content: 'Eggs, milk. Also read about learning rate schedules later.' })
  await vault.capture({ title: 'Unrelated', content: 'Nothing to see.' })
  const results = await vault.search('learning rate')
  assert.equal(results[0].id, 'learning-rate-warmup')
  assert.equal(results.length, 2)
  assert.ok(results[0].snippet.toLowerCase().includes('warmup') || results[0].snippet.length > 0)
}))

test('backlinks and link()', () => withVault(async vault => {
  await vault.capture({ title: 'Transformers', content: 'Attention layers.' })
  await vault.capture({ title: 'BERT', content: 'Encoder built on [[Transformers]].' })
  await vault.capture({ title: 'GPT', content: 'Decoder only.' })
  assert.deepEqual((await vault.backlinks('transformers')).map(b => b.id), ['bert'])
  const r = await vault.link('gpt', 'transformers', 'also attention based')
  assert.equal(r.changed, true)
  assert.equal((await vault.link('gpt', 'transformers')).changed, false)
  assert.deepEqual((await vault.backlinks('transformers')).map(b => b.id).sort(), ['bert', 'gpt'])
}))

test('ids cannot escape the vault', () => withVault(async vault => {
  await assert.rejects(() => vault.read('../etc/passwd'), /invalid note id/)
  await assert.rejects(() => vault.read('A'), /invalid note id/)
}))

test('overview reports totals and tag histogram', () => withVault(async (vault, dir) => {
  await vault.capture({ title: 'One', content: 'x', tags: 'ml, papers' })
  await vault.capture({ title: 'Two', content: 'y', tags: 'ml' })
  const o = await vault.overview({ tag: 'papers' })
  assert.equal(o.total, 2)
  assert.deepEqual(o.tags[0], { name: 'ml', count: 2 })
  assert.deepEqual(o.notes.map(n => n.id), ['one'])
  assert.match(await readFile(join(dir, 'one.md'), 'utf8'), /^---\ntitle: One\ntags: \[ml, papers\]/)
}))

test('rank returns nothing for stopword-only queries', () => {
  assert.deepEqual(rank([{ title: 'x', tags: [], body: 'the and' }], 'the and'), [])
})
