# Creator mode: the prompts

Creator mode is not a code generator bolted onto the side of DeepSeek Harness. It is an
**agent preset** — `presets/cordis/agent.cordis.yml` inside `@deepseek-ai/dsh-agent-presets` —
that adds three things to the Standard composition:

| Added by Creator mode | What it is for |
|---|---|
| `tool-cordis` (`cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`, `cordis_define`, `cordis_run`, `cordis_stop`, `cordis_undefine`) | Read the live runtime, then mount a plugin into the running process and take it out again |
| Two skills: `cordis-plugin-development`, `editing-cordis-compositions` | The procedure: inspect before you write, Host vs Client, where a preset may be edited |
| A persona that explains the two planes | HOST composition (shared registries) vs AGENT PRESET (what one session contributes) |

The agent can therefore answer "what slots exist?" by **asking the running UI**, not by guessing —
which is the entire reason a one-sentence plugin request works at all.

> Version note. This repo targets `@deepseek-ai/dsh@0.1.5-rc.2` (`npm view @deepseek-ai/dsh version`),
> where Creator mode mounts **in-memory** plugins with `cordis_define` / `cordis_run`, and persistent
> installation is `dsh plugin add`. The `0.1.6-alpha` line adds a `plugin_manager` tool that installs
> bundles from chat. Both end at the same artifact: a package with a `dsh.bundle` manifest.
> Everything in this repo is packaged that way, so it works on either line.

---

## The workflow Creator mode actually follows

```
inspect        cordis_inspect_list            what Providers exist on Host and Client right now
               cordis_inspect_query           exact Service methods / Slot props / Event signatures
write          plain JS, no bundler           code.host and/or code.client
mount          cordis_define -> cordis_run    live in the running process, no restart
observe        the Trajectory + the page      does it actually render / does the tool actually run
keep or drop   package it, or cordis_undefine promote only what survived
```

"Test in memory, then package" is the loop. The two plugins in `plugins/` are what came out the
other end, cleaned up, given tests and a manifest.

---

## Prompt 1 — the one-sentence plugin (dsh-dino-break)

Paste this into a **Creator mode** session:

> Add a dinosaur jumping game floating in the bottom right of the Harness UI, with a toggle button
> next to the composer. Keep it in memory for now so I can try it before we package it.

What the agent does, in order:

1. `cordis_inspect_list` — enumerates Client providers, finds `slots`.
2. `cordis_inspect_query` with `Slots.listSubTree` — finds `shell.overlay` (root-scoped, `kind: list`)
   for the floating card and `conversation.input.right` (the composer tool row) for the button.
3. Writes `code.client` as a plain JS function body returning `{ inject: ['slots'], apply(ctx) {...} }`,
   using `React.createElement` (no JSX, no imports — the browser module table supplies React).
4. `cordis_define` then `cordis_run`: the game appears in the page you already have open. No restart.
5. You play it. If the dino's hitbox is wrong, you say so and it redefines a new Package version.

Follow-up prompts that show the loop working:

> The dino jumps when I press space while typing in the composer. Read keys from the canvas only.

> Add birds after 250 points, and keep a high score in localStorage.

> Now package it as an installable bundle so it survives a restart.

The packaged result is [`plugins/dsh-dino-break`](plugins/dsh-dino-break) — `package.json` with
`dsh.bundle` + `dsh.client`, a `cordis.patch.yml` with one row, `client.js` registering into the two
slots, and an empty `index.js` because the plugin has no Host half at all.

---

## Prompt 2 — the full-stack plugin (dsh-second-brain)

A second brain needs storage, a search path, tools, a prompt section and a UI, so the prompt is a
specification rather than a sentence:

> Build me a Second Brain plugin for this harness.
>
> Storage: one Markdown file per note in `$DSH_HOME/second-brain`, YAML front matter with title, tags,
> created, updated, and `[[wikilinks]]` in the body — Obsidian must be able to open the folder.
>
> Tools: `brain_capture` (a new title creates a note, an existing title appends a dated update, never
> overwrite), `brain_search` (BM25 over title, tags and body, title matches ranked higher),
> `brain_read` (note plus outgoing links plus backlinks), `brain_list` (recent notes and a tag
> histogram), `brain_link` (append a wikilink from one note to another).
>
> Prompt: add a short system-prompt section telling the agent to search the brain before answering
> questions about past work, and to capture durable decisions.
>
> UI: a button in the composer tool row that opens a floating panel — search, tag filter, note reader
> with clickable wikilinks and backlinks, and a capture form.
>
> Inspect the real Slot and Service APIs before writing code, and keep the vault logic in a module with
> no harness imports so I can unit-test it.

What the agent inspects: `Tool.listTools` and the `tools` registry shape for `defineTool`;
`Service.listService` for `systemPrompt` (`ctx.systemPrompt.section({ name, order, text })`) and
`webServer` (`ctx.webServer.register({ kind, path, handler })`); `Slots.listSubTree` for
`conversation.input.right` and `shell.overlay`.

Two corrections worth showing on camera, because they are the difference between a demo and a plugin:

> The panel can't reach the Host. Give the plugin its own JSON route on the web server, and make that
> route refuse requests that are not loopback and do not carry a custom header — it sits outside the
> token-guarded `/api`.

> Split the Host half in two rows: tools in one, the HTTP API in another that injects `webServer`,
> so the tools still load in a headless profile.

The packaged result is [`plugins/dsh-second-brain`](plugins/dsh-second-brain), with
`lib/vault.js` unit-tested by `npm test` (9 tests, no harness, no network).

---

## Prompt 3 — a domain agent as a preset, not a fork

> Copy the Standard preset into a new preset called `ml-researcher`. Persona: an ML research engineer
> that searches the Second Brain first, states a hypothesis and a metric before editing, changes one
> thing per experiment, never edits the evaluation, and captures results with `brain_capture`.
> Disable `tool-ralph` — I do not want an unattended loop near a training script — and turn off
> parallel todos. Prune tool results harder, because training logs are long.

Creator mode loads `editing-cordis-compositions`, copies the shipped composition into
`$DSH_HOME/.agent-presets/ml-researcher/`, edits the copy, and the preset shows up in the session mode
dropdown. It never touches the shipped preset directory — an upgrade would overwrite it, and breaking
the `cordis` preset would disable Creator mode itself.

The second preset in this repo, `research-librarian`, is the same move by **subtraction**: no shell,
no `tool-fs`, no subagents — web search plus the Second Brain, and nothing that can modify the machine.

> Now make a second preset called `research-librarian` with no shell and no filesystem write or edit
> tools at all — web search, web fetch, glob/grep and the brain tools only — and a persona that tells
> the user which preset to switch to when a request needs code execution.

Both live in [`presets/`](presets) and install with `scripts/install-presets.sh`.

---

## Prompt 4 — connect an MCP server (configuration as a plugin)

> Configure the MCP server at `http://127.0.0.1:3333/mcp` in this profile as `demo`, make its tools
> available now, then call its ping tool and tell me the result.

This one has no code at all: the agent writes a configuration-only bundle whose patch inserts
`@deepseek-ai/dsh-mcp-client` with `serverName: demo`, installs it, and then calls `mcp__demo__ping`.
It is the cleanest illustration of "everything is a plugin" — an integration and a UI widget are the
same kind of object in this harness.

---

## What to show on camera

1. Switch the mode dropdown to **Creator mode** and read the four extra tools in the trajectory.
2. Paste **Prompt 1**. Let it inspect, define, run. Play the game in the same page.
3. Break it on purpose (`the dino jumps while I type`), let it fix and re-run — this is the
   define / run / observe / redefine loop that makes Creator mode worth the extra tools.
4. `cordis_undefine`, then install the packaged version with `scripts/install-local-plugins.sh`
   and restart: the same game, now surviving a restart, versioned in git, with a manifest.
5. Paste **Prompt 3** and switch a new session to the `ml-researcher` preset to show that a domain
   agent is a file, not a fork.
