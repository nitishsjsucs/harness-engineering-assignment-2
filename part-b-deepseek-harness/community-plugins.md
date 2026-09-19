# The seven community plugins

Installed into the `web` profile with `scripts/install-community-plugins.sh`, all verified on
`@deepseek-ai/dsh@0.1.5-rc.2` on macOS 26 (arm64), Node 25.

| # | Plugin | Install name | What it adds | Where it shows up |
|---|---|---|---|---|
| 1 | [dsh-market](https://github.com/dsh-market/dsh-market) | `dshmarket` | A plugin market inside Settings: ~4k catalogued plugins, search, categories, one-click install/upgrade, themes tab | Settings -> Plugin Market |
| 2 | [dsh-find-plugin](https://github.com/awesome-dsh-plugin/dsh-find-plugin) | `dsh-find-plugin` | A `find_dsh_plugin` **tool** — the agent itself searches the catalogue and hands back `dsh plugin add` commands | The model's tool list |
| 3 | [DSH-better-sidebar](https://github.com/omdsh-dev/DSH-better-sidebar) | `dsh-better-sidebar` | A real workbench in the right sidebar: file tree + editor, terminal (node-pty), Git panel, subagent view; other plugins can register pages into it | Right sidebar |
| 4 | [dsh-context](https://github.com/bowenliang123/dsh-context) | `dsh-context` | Context-window dashboard: what is occupying the prompt, per-turn growth, a `/context` command | Left sidebar -> Context Insights |
| 5 | [dsh-free-search](https://github.com/DDDMUC/dsh-free-search) | `dsh-free-search` | Keyless web search tools (DuckDuckGo / Bing / SearXNG), so search works without a DeepSeek search key | The model's tool list |
| 6 | [dsh-chat-toc](https://github.com/a792883583/dsh-chat-toc) | `dsh-chat-toc` | Table of contents for a long conversation: jump between your questions, bookmarks, pinned turns | Conversation sidebar |
| 7 | [dsh-catppuccin-theme](https://github.com/NoNameLeGo/dsh-catppuccin-theme) | `@nonamelego/dsh-catppuccin` | Latte / Frappé / Macchiato / Mocha themes plus a glassmorphism skin | Settings -> General -> Catppuccin theme |

```bash
./scripts/install-community-plugins.sh web       # all seven
dsh plugin --profile web remove dsh-chat-toc     # any one of them, back out
```

## Why these seven

They were not picked for stars. Each one covers a different **extension point** of the harness, so
together they are a tour of what a plugin is allowed to be:

- **A market** (`dshmarket`) is a Settings page plus a package-manager driver — a plugin that installs plugins.
- **A tool** (`dsh-find-plugin`, `dsh-free-search`) adds to the model's catalogue. `dsh-free-search` is the
  interesting one: DSH's built-in `web_search` routes through DeepSeek's endpoint, so on an OpenRouter or
  OpenAI key it is dead weight. A community plugin replaces a first-party capability without forking anything.
- **A surface** (`dsh-better-sidebar`) claims a whole region and then *re-exports it*: it defines slots other
  plugins register into. Extension points compose.
- **An observability panel** (`dsh-context`) reads the session's own projections. It is the cheapest way to
  see prompt-cache behaviour and compaction actually happening — the concepts Part A implements by hand.
- **A navigation aid** (`dsh-chat-toc`) touches only the browser half: no Host code at all, the same shape as
  our `dsh-dino-break`.
- **A theme** (`@nonamelego/dsh-catppuccin`) overrides theme tokens — configuration as a package.

## Installing them is running their code

`dsh plugin add` puts third-party JavaScript in the harness process, with your file access and your
credentials. Tool approvals do not sandbox plugin code. Two concrete consequences we hit:

- `dsh-better-sidebar` depends on **node-pty** (a native terminal binding), and pnpm ≥ 10 refuses to run a
  dependency's build script until it is allowed. `dsh` fails with `ERR_PNPM_IGNORED_BUILDS` and names the
  package; you allow it in the profile's `pnpm-workspace.yaml`:

  ```yaml
  allowBuilds:
    node-pty: true
  ```

  That is permission to execute that package's install script on your machine. It is a decision, not a hoop.
- An install that fails leaves the profile manifest and lockfile restored, but downloaded files may remain
  under `node_modules`. Removing a bundle (`dsh plugin remove`) unlists it and unloads it; it does not undo
  anything it already wrote to disk.

For anything unfamiliar: read the source, pin a commit (`github:owner/repo#<sha>`), and try it in a profile
that holds no keys — `DSH_HOME=/tmp/dsh-sandbox dsh web` gives you a disposable one, which is exactly how
the screenshots in this repo were produced.

## Verified state

After `install-community-plugins.sh` plus `install-local-plugins.sh`, Settings -> Plugin Market reports
**Installed (8)** and the Settings pages gained *Plugins*, *Agent presets*, *Plugin Market* and *Side card*.
The composer tool row carries **Brain** and **Break** from our own two plugins, and the session mode
dropdown lists **ML Researcher** and **Research Librarian** beside the four shipped presets.
