# Part B — DeepSeek Harness: Creator mode, seven community plugins, two of our own

> Install the DeepSeek Harness, customise it in Creator mode with community plugins, write two
> plugins from scratch, and show the prompt and the demo for each.

What is here:

```
scripts/install-community-plugins.sh   the seven community plugins
scripts/install-local-plugins.sh       packs and installs our two plugins
scripts/install-presets.sh             copies our two agent presets into $DSH_HOME
plugins/dsh-second-brain/              plugin 1 — tools + HTTP API + floating panel  (full stack)
plugins/dsh-dino-break/                plugin 2 — a T-rex runner in the corner        (browser only)
presets/ml-researcher/                 domain agent by configuration
presets/research-librarian/            domain agent by subtraction (no shell, no writes)
community-plugins.md                   what each community plugin adds, and why those seven
creator-mode-prompts.md                the prompts, what the agent inspects, what it writes
```

Verified on `@deepseek-ai/dsh@0.1.5-rc.2`, macOS 26 (arm64), Node 25.9, pnpm 12.

---

## 1. What the DeepSeek Harness is

`dsh` is DeepSeek's open-source agent harness, built on [Cordis](https://github.com/cordiverse/cordis)
with one organising idea: **everything is a plugin**. Not "the agent plus a plugin API" — the agent loop,
the tools, the sandbox, the session store, the LLM adapter and the browser UI are all plugin rows in a
`cordis.yml`, composed in layers.

```
$DSH_HOME/profiles/web/package.json        dsh.profile.bundles: the ordered layer list
  @deepseek-ai/dsh-base                    layer 1: registries, persistence, sandbox, model route
  @deepseek-ai/dsh-web-app                 layer 2: the web surface
  dshmarket, dsh-second-brain, ...         layer 3..n: each installed bundle's cordis.patch.yml
$DSH_HOME/profiles/web/cordis.patch.yml    your own overrides, applied last
```

Two planes decide where a change belongs, and getting this wrong is the usual reason a plugin
"loads but does nothing":

| Plane | Holds | Lives in |
|---|---|---|
| **Host composition** | registries and anything shared by every session: persistence, sandbox, approval, the model route, the subagent registry | profile bundles (`dsh plugin add`) |
| **Agent preset** | what ONE session contributes to those registries: its tools, persona, prompt sections, skills | `agent.cordis.yml` under `$DSH_HOME/.agent-presets/<id>/` |

A bundle adds a capability to the deployment. A preset decides how one agent works. Our Second Brain is a
bundle (every session gets the tools); our ML Researcher is a preset (only that mode works that way).

---

## 2. Install and run

```bash
npx @deepseek-ai/dsh web              # no install; starts the Web UI on http://127.0.0.1:3080
# or
npm install -g @deepseek-ai/dsh && dsh web
```

The command prints a URL with a one-time token. Everything below assumes the `web` profile.

To keep an experiment away from your real configuration, point `DSH_HOME` somewhere disposable —
this is how the whole of Part B was developed:

```bash
DSH_HOME=/tmp/dsh-demo dsh web --no-open --port 3180
```

### Configure a model — for free

Settings -> Models. The shipped card is DeepSeek (`platform.deepseek.com`). For this assignment the
same OpenRouter key as Part A works — add it as a **custom provider**, because OpenRouter is not in the
built-in catalogue:

| Field | Value |
|---|---|
| Provider ID | `openrouter` |
| Base URL | `https://openrouter.ai/api/v1` |
| API protocol | `openai-completions` |
| API key | `sk-or-...` |
| Models | `deepseek/deepseek-v4-flash-0731:free`, `nvidia/nemotron-3.5-lightning:free` |

Both of those cost **nothing** and both do tool calling, which is what a harness actually needs. The
equivalent, written straight into `$DSH_HOME/settings.yaml` (what this repo was tested with — the two
`compat` switches are the ones most OpenAI-compatible gateways need):

```yaml
llm-pi-ai:
  providers:
    openrouter:
      apiKeyEnv: OPENROUTER_API_KEY
      api: openai-completions
      baseURL: https://openrouter.ai/api/v1
      compat:
        supportsDeveloperRole: false
        maxTokensField: max_tokens
      models:
        - id: deepseek/deepseek-v4-flash-0731:free
          displayName: DeepSeek V4 Flash (free)
        - id: nvidia/nemotron-3.5-lightning:free
          displayName: Nemotron 3.5 Lightning (free)
```

Then start the harness with the key in the environment: `OPENROUTER_API_KEY=sk-or-... dsh web`.

> **Know the ceiling before you demo.** OpenRouter's free tier is **20 requests per minute and 50 per
> day**; an account that has ever purchased $10 of credits gets 1000 per day
> ([limits](https://openrouter.ai/docs/api-reference/limits)). One agent turn is several requests — the
> capture demo below cost four — so a long filming session can exhaust 50 quickly. Check what is left:
> `curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY"`.

An OpenAI key is simpler still: **Add provider -> openai**, paste the key, done (the installed catalogue
supplies endpoint and model list) — but it is not free.

If a gateway refuses every request, the two switches that fix most of them go in `$DSH_HOME/settings.yaml`:

```yaml
llm-pi-ai:
  providers:
    openrouter:
      api: openai-completions
      baseURL: https://openrouter.ai/api/v1
      compat:
        supportsDeveloperRole: false     # gateway rejects role: "developer" on reasoning models
        maxTokensField: max_tokens       # gateway only knows max_tokens
      models:
        - id: google/gemini-3.5-flash
```

Keys are stored write-only in `$DSH_HOME/.credentials.yaml`; settings keep only a reference.

> Note: the built-in `web_search` tool routes through DeepSeek's own endpoint, so on an OpenRouter or
> OpenAI key it will not work. That is one reason `dsh-free-search` is in our seven.

---

## 3. Creator mode

Switch the session mode dropdown from **Standard mode** to **Creator mode**. It is an agent preset that
adds runtime-inspection and plugin tools (`cordis_inspect_list`, `cordis_inspect_query`, `cordis_define`,
`cordis_run`, `cordis_stop`, `cordis_undefine`), two authoring skills, and a persona that explains the two
planes above. The agent can therefore ask the running UI which slots exist instead of guessing, mount a
plugin into the live process, watch it fail, and rewrite it — all without a restart.

The prompts we used, what the agent inspects for each, and the follow-ups that turn a demo into a plugin
are in **[creator-mode-prompts.md](creator-mode-prompts.md)**.

---

## 4. The seven community plugins

```bash
./scripts/install-community-plugins.sh web
```

`dshmarket` (a market inside Settings), `dsh-find-plugin` (the agent searches the catalogue itself),
`dsh-better-sidebar` (files + terminal + git workbench), `dsh-context` (context-window dashboard),
`dsh-free-search` (keyless web search), `dsh-chat-toc` (conversation navigation), and
`@nonamelego/dsh-catppuccin` (themes).

Each one covers a different extension point — market, tool, surface, panel, browser-only, theme — so the
set is a tour of what a plugin may be. Details, the node-pty build-approval gotcha, and the security
argument: **[community-plugins.md](community-plugins.md)**.

---

## 5. The two plugins written from scratch

```bash
./scripts/install-local-plugins.sh web       # packs to a tarball, then dsh plugin add
```

### [dsh-second-brain](plugins/dsh-second-brain) — full stack

Five tools (`brain_capture`, `brain_search`, `brain_read`, `brain_list`, `brain_link`) over an
**Obsidian-compatible Markdown vault**, a system-prompt section that tells the agent when to use them, a
loopback-only JSON API, and a floating panel in the Web UI with BM25 search, tag chips, a note reader with
clickable `[[wikilinks]]` and backlinks, and a capture form.

It exists because a session's context dies with the session and a folder of Markdown does not.
`lib/vault.js` has no harness imports and is unit-tested (`npm test`, 9 tests, no network).

### [dsh-dino-break](plugins/dsh-dino-break) — browser only

A T-rex runner floating in the bottom-right corner, toggled from the composer tool row. Zero Host code:
two slot registrations (`conversation.input.right`, `shell.overlay`), one shared store, a canvas game
with fixed-step physics and a `localStorage` high score. This is the "generate a plugin from one
sentence" demo — and the shortest possible tour of the Client half of the harness.

---

## 6. Domain agents as presets, not forks

```bash
./scripts/install-presets.sh
```

| Preset | Built by | Point |
|---|---|---|
| **ML Researcher** | configuration | Experiment discipline in the persona (hypothesis -> one change -> the repo's own eval -> capture), `tool-ralph` disabled, no parallel todos, harder tool-result pruning for long training logs |
| **Research Librarian** | subtraction | No shell, no `tool-fs` at all, no subagents. Web search/fetch + the Second Brain + glob/grep. A knowledge agent that cannot modify the machine |

Both appear in the mode dropdown beside Standard / PTC / Minimal / Creator, in the same process, on the
same profile. Nothing was forked.

---

## 7. Demo script (what to show)

1. `DSH_HOME=/tmp/dsh-demo dsh web` — empty harness, Settings -> Models, add the key.
2. Settings -> Plugin Market: 4k plugins; install one from the UI.
3. `./scripts/install-community-plugins.sh` in a terminal; restart; point at Context Insights, the new
   sidebar, the Catppuccin themes.
4. Creator mode + prompt 1 from `creator-mode-prompts.md`: the dino game appears in the running page.
5. `./scripts/install-local-plugins.sh`; restart; **Brain** and **Break** in the composer row.
6. Ask the agent: *"Remember that this project pins PyTorch 2.9 because MPS crashes on 2.10"*, then in a
   NEW session: *"what do you know about our PyTorch version?"* — `brain_search` runs before the answer.
   The note is visible in the panel and on disk as Markdown.
7. Switch the mode dropdown to **Research Librarian**, ask it to edit a file, and watch it decline and
   name the preset that can — capability boundaries you can see.

---

## 8. Testing a plugin's tools without a model

A plugin's tools only earn their keep when the agent can actually call them, and checking that
normally costs a key, credits and a nondeterministic model. `scripts/mock-provider.py` is a scripted
OpenAI-compatible endpoint: it speaks just enough of the Chat Completions API for the harness to talk
to it, and answers with the tool call you choose. The harness does everything else for real —
validates the arguments, applies the permission policy, runs the tool, records the turn.

```bash
python3 scripts/mock-provider.py --call 'brain_search({"query":"pytorch"})'
```

Then add a custom provider (`mock` / `http://127.0.0.1:4111/v1` / `openai-completions` / any key /
model `mock-model`) and send any message. The server prints the tool catalogue the harness sent,
which is the fastest way to see whether your plugin's tools actually reached the model:

```
--- request 1: model=mock-model stream=True messages=4
    tools offered (36): advanced_search, ask_user_question, bash, brain_capture, brain_link,
    brain_list, brain_read, brain_search, ..., web_search, workflow, write
      * brain_capture(title, content, tags)
      * brain_search(query, limit)
```

It also makes the Part B demo rehearsable at zero cost, and gives you a deterministic way to
reproduce a tool bug that a model only triggers occasionally.

## 9. Troubleshooting, from things that actually went wrong here

| Symptom | Cause and fix |
|---|---|
| `Cannot find package '@deepseek-ai/dsh-tools' imported from .../my-plugin/index.js` | You installed a plugin **folder**. `dsh plugin add ./dir` creates a pnpm link, and a linked folder outside `$DSH_HOME` cannot resolve the in-box packages dsh symlinks into `$DSH_HOME/profiles/node_modules`. Pack a tarball instead (`npm pack`), which is what `install-local-plugins.sh` does. |
| `ERR_PNPM_IGNORED_BUILDS: node-pty` and every later install fails too | pnpm refuses a dependency build script. Set `allowBuilds: {node-pty: true}` in `$DSH_HOME/profiles/web/pnpm-workspace.yaml`, then re-run. Until it is resolved, the profile install stays blocked. |
| A preset shows its id and "No description" | `preset.yml` failed to parse. Usually an unquoted `:` inside `description:`. Quote it or use a `>-` block. |
| Plugin loads, UI shows nothing | Wrong plane or wrong slot. Check the client bundle is in the boot graph (`view-source` the index page and search for your package name), and that `dsh.client.inject` names the package that owns your slot. |
| The workspace picker does nothing over a remote/automated browser | The auto picker chose the native OS dialog. Pin the in-app one in `$DSH_HOME/profiles/web/cordis.patch.yml`: `- id: directory-picker` / `name: '@deepseek-ai/dsh-host-directory-picker-browse'`. |

---

## 10. What was verified

All of it was run on this machine on 2026-09-19 (`dsh@0.1.5-rc.2`, macOS 26 arm64, Node 25.9):

**Installation and UI.** All seven community plugins install and load; Settings -> Plugin Market reports
`Installed (8)` and marks `DSH-better-sidebar` as installed; both our plugins install from tarballs and
add **Brain** and **Break** to the composer row; both presets appear in the mode dropdown with their
metadata beside Standard / PTC / Minimal / Creator.

**The Second Brain, end to end.** The panel captured a note through the HTTP API, and the note landed on
disk as Markdown with front matter, tags and a working `[[wikilink]]`; the API refused the same request
without its header. With a model attached, the harness offered **36 tools including all five `brain_*`**
and ran them for real: `brain_capture` created a note stamped with the session id, and in a **separate
session with an empty context**, `brain_search` returned that note ranked by BM25 — memory outliving the
conversation, which is the whole point of the plugin. `npm test` passes (9 tests, no network).

Re-run on the **free** route (`deepseek/deepseek-v4-flash-0731:free`, 4 requests, $0), the model did
something better than the paid one: it called `brain_search` *before* capturing — which is exactly what
the plugin's system-prompt section asks for — then `brain_list` to see the existing tags, then
`brain_capture`, and it added a `Related: [[...]]` wikilink of its own accord. The note it wrote:

```markdown
---
title: Presets ship as files in git (DSH)
tags: [decisions, dsh]
source: "dsh-session:session-6b6349e1-..."
---
**Decision:** Ship presets as files committed to git, rather than ... from a copied preset in chat.
**Why:** Editing from a copied preset requires Full access (sandbox escalation) ...
Related: [[tool-call-from-the-mock-provider]]
```

Five lines of prompt turned a tool list into a habit — on a model that costs nothing.

**Creator mode.** One sentence produced a working plugin in the live process: skill load ->
`cordis_inspect_list` -> `cordis_inspect_query` -> `cordis_define` -> `cordis_run` -> approval -> a whale
animating in the corner and a "Hide Whale" button in the composer. 7 tool calls, 56 s, 85% cache hit.
Details in [creator-mode-prompts.md](creator-mode-prompts.md).

**The Dino game** runs, scores, ends and restarts, and does not steal Space from the composer.

Not verified: the `dsh plugin add github:...` path (our plugins were installed from tarballs, which is
the same code path pnpm takes for a registry install, but not literally a git install), and Windows
anything — `tool-pwsh` rows are untouched defaults.
