# dsh-second-brain

A Second Brain for DeepSeek Harness: the agent captures what is worth keeping into an
**Obsidian-compatible Markdown vault**, searches it with BM25, reads notes with their
backlinks, and links ideas together — and you browse the same vault from a floating
panel in the Web UI.

The point is a harness-engineering one: a session's context dies with the session.
A vault on disk does not. This plugin is the smallest complete version of that idea —
storage the model can write, a retrieval path it can query, and prompt guidance that
tells it when to do either.

## What it adds

| Surface | What you get |
|---|---|
| Tools | `brain_capture`, `brain_search`, `brain_read`, `brain_list`, `brain_link` |
| System prompt | ~5 lines telling the agent when to search and when to capture |
| Web UI | "Brain" button in the composer tool row; floating panel with Browse / Capture, BM25 search, tag chips, note reader with clickable `[[wikilinks]]` and backlinks |
| Disk | One `.md` file per note with YAML front matter — open the folder in Obsidian and every link works |

## Install

```bash
# from a checkout of this repo
cd part-b-deepseek-harness
./scripts/install-local-plugins.sh            # packs both plugins and installs them into the web profile
```

or by hand:

```bash
npm pack ./plugins/dsh-second-brain --pack-destination /tmp
dsh plugin --profile web add /tmp/dsh-second-brain-0.1.0.tgz
```

Restart `dsh web`. The notes live in `$DSH_HOME/second-brain` by default; point both rows
in `cordis.patch.yml` at an existing Obsidian vault to share notes with Obsidian.

> A local folder is not installable by reference: `dsh plugin add ./path` links the folder,
> and a linked folder cannot resolve the in-box `@deepseek-ai/*` packages (DSH symlinks those
> into `$DSH_HOME/profiles/node_modules`, which a folder outside that tree never sees).
> Packing to a tarball — what the script does — installs a real copy into the profile, which resolves.

## Try it

Ask the agent, in this order:

1. `Remember that this project pins PyTorch 2.9 because the MPS backend crashes on 2.10.`
2. `What do you know about our PyTorch version?` (it should call `brain_search` before answering)
3. `Capture a note about the Second Brain plugin itself and link it to the PyTorch note.`

Open the **Brain** panel while the agent works: the panel polls every 4 seconds, so notes
appear as the agent writes them.

## How it is put together

```
index.js      Host: the five tools + the system-prompt section          (inject: tools, systemPrompt)
web.js        Host: JSON API for the panel                              (inject: webServer)
lib/vault.js  Pure storage + BM25 logic — no harness imports, unit tested
client.js     Browser: composer button + floating panel (React via the host's module table)
```

Three decisions worth pointing at:

**Two Host rows, one vault.** The tools row needs only `tools`; the API row needs `webServer`,
which only the Web profile provides. Splitting them means the tools still load in a headless
or TUI profile — a plugin should not lose its model-facing half because a UI service is absent.

**Capture appends, never overwrites.** Capturing a title that already exists adds a dated
`## Update` section. A memory that silently overwrites itself is worse than no memory.

**The API defends itself.** The routes sit outside DSH's token-guarded `/api`, so they check
that the `Host` header is loopback (defeats DNS rebinding) and require a custom
`x-second-brain: 1` header, which a cross-origin page cannot send without a CORS preflight
this API never answers.

## Tests

```bash
cd plugins/dsh-second-brain && npm test        # node --test, no harness, no network
```

Covers front-matter round-tripping, wikilink extraction, append-on-existing-title, BM25
ranking (title beats body mention), backlinks, and path-traversal refusal for note ids.

## The prompt that built it

This plugin was authored in **Creator mode**; the full prompt and what the agent did with it
are in [`../../creator-mode-prompts.md`](../../creator-mode-prompts.md).

## Limitations

- Search rebuilds the index on every query. Fine for a few thousand notes; a persistent index
  is the obvious next step.
- No delete or rename tool: destructive operations on memory should be a human's decision
  (delete the `.md` file).
- The panel polls instead of subscribing; DSH has no client event for "a plugin's data changed".
