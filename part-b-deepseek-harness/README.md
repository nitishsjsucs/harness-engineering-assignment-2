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

### Configure a model

Settings -> Models. The shipped card is DeepSeek (`platform.deepseek.com`). For this assignment the
same OpenRouter key as Part A works — add it as a **custom provider**, because OpenRouter is not in the
built-in catalogue:

| Field | Value |
|---|---|
| Provider ID | `openrouter` |
| Base URL | `https://openrouter.ai/api/v1` |
| API protocol | `openai-completions` |
| API key | `sk-or-...` |
| Models | `google/gemini-3.5-flash`, `deepseek/deepseek-v4-flash`, `anthropic/claude-sonnet-5`, ... |

An OpenAI key is simpler still: **Add provider -> openai**, paste the key, done (the installed catalogue
supplies endpoint and model list).

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

## 8. Troubleshooting, from things that actually went wrong here

| Symptom | Cause and fix |
|---|---|
| `Cannot find package '@deepseek-ai/dsh-tools' imported from .../my-plugin/index.js` | You installed a plugin **folder**. `dsh plugin add ./dir` creates a pnpm link, and a linked folder outside `$DSH_HOME` cannot resolve the in-box packages dsh symlinks into `$DSH_HOME/profiles/node_modules`. Pack a tarball instead (`npm pack`), which is what `install-local-plugins.sh` does. |
| `ERR_PNPM_IGNORED_BUILDS: node-pty` and every later install fails too | pnpm refuses a dependency build script. Set `allowBuilds: {node-pty: true}` in `$DSH_HOME/profiles/web/pnpm-workspace.yaml`, then re-run. Until it is resolved, the profile install stays blocked. |
| A preset shows its id and "No description" | `preset.yml` failed to parse. Usually an unquoted `:` inside `description:`. Quote it or use a `>-` block. |
| Plugin loads, UI shows nothing | Wrong plane or wrong slot. Check the client bundle is in the boot graph (`view-source` the index page and search for your package name), and that `dsh.client.inject` names the package that owns your slot. |
| The workspace picker does nothing over a remote/automated browser | The auto picker chose the native OS dialog. Pin the in-app one in `$DSH_HOME/profiles/web/cordis.patch.yml`: `- id: directory-picker` / `name: '@deepseek-ai/dsh-host-directory-picker-browse'`. |

---

## 9. What was verified, and what was not

Verified on this machine: all seven community plugins install and load; Plugin Market reports
`Installed (8)`; both our plugins install from tarballs and appear in the composer row; the Second Brain
panel creates a note through the HTTP API and the note lands on disk as Markdown with front matter and a
working wikilink; the API refuses a request without its header; the Dino game runs, scores, and ends;
both presets appear in the mode dropdown with their metadata; `npm test` passes for the vault.

Not verified without a model key: the agent actually *calling* `brain_*` in a live session, and the
Creator-mode transcripts. Those are the on-camera parts — they need a provider key, and the commands are
exactly the ones in section 7.
