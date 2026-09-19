# dsh-dino-break

A T-rex runner that floats in the bottom-right corner of the DeepSeek Harness Web UI,
for the minutes while the agent works.

This is the "generate a plugin from one sentence" demo, done properly: the whole plugin is
a **browser-only** Cordis plugin, which makes it the shortest possible tour of the Client
half of the harness — two slots, one store, no Host code at all.

## What it adds

| Surface | What you get |
|---|---|
| Web UI | "Break" button in the composer tool row (`conversation.input.right`) |
| Web UI | A floating game card (`shell.overlay`): canvas runner, jump on Space / Up / click, cacti then birds, rising speed, score and a high score kept in `localStorage` |
| Host | Nothing. `index.js` is an empty `apply()` — the Loader row needs a module, the game needs no server |

## Install

```bash
cd part-b-deepseek-harness && ./scripts/install-local-plugins.sh
```

or `npm pack ./plugins/dsh-dino-break --pack-destination /tmp && dsh plugin --profile web add /tmp/dsh-dino-break-0.1.0.tgz`.

## How it is put together

**Two slots, one store.** The button and the game live in different slots and therefore in
different React trees, so a module-level store with `useSyncExternalStore` connects them —
the same trick DSH's own UI plugins use, and the reason the game can be toggled from a
toolbar it has no parent relationship with.

**Keys are read from the canvas, not the window.** The canvas takes `tabIndex=0` and handles
`keydown` itself, so pressing Space while writing a prompt types a space instead of jumping.
A plugin that hijacks a global key in a text-first app is a bug, not a feature.

**Fixed-step physics.** `requestAnimationFrame` delivers frames at whatever rate the display
runs; the update loop consumes a 1/60 s accumulator, so the game is not twice as fast on a
120 Hz screen. Closing the card unmounts the component, which cancels the animation frame —
no hidden CPU burn.

**Sprites are text.** The dino, cactus and bird are string arrays where `#` is a pixel, drawn
as 2x2 `fillRect`s. The same array renders the toolbar icon as SVG rects, so the button and
the game can never drift apart.

## The prompt that built it

One sentence, in Creator mode:

> Add a dinosaur jumping game floating in the bottom right of the Harness UI, with a toggle
> button next to the composer.

The full transcript of what the agent inspected and wrote is in
[`../../creator-mode-prompts.md`](../../creator-mode-prompts.md).

## Limitations

- No duck (`ArrowDown`) move yet; the high birds are cleared by jumping.
- The high score is per browser profile (`localStorage`), not per user.
- Sound would need an audio asset; the plugin ships no binary files on purpose.
