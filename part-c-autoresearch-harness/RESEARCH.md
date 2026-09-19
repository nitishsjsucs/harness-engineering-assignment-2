# What already exists, and what `arh` took from it

Eight autoresearch harnesses were read before writing a line of `arh`, plus the
[awesome-autoresearch](https://github.com/WecoAI/awesome-autoresearch) list and
the two harness-engineering sources the assignment points at. Everything below
was read from the repositories themselves (READMEs, prompts, source) in
September 2026. No code was copied; what was borrowed is an idea, and it is
attributed.

## The survey

| harness | what it is | loop | keep rule | guards against fooling yourself | packaging |
|---|---|---|---|---|---|
| [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | the original: nanochat-style training plus a `program.md` prompt the agent runs overnight | branch `autoresearch/<tag>`, edit `train.py`, commit, run, grep the log, log a TSV row, keep or `git reset` | `val_bpb` strictly lower | rules only: `prepare.py` "must not" be edited, fixed 300 s `TIME_BUDGET`, `evaluate_bpb` pinned to one val shard, NaN stops the run | a single markdown prompt; works with any assistant |
| [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) | the loop as an extension for the pi agent, aimed at any metric (tests, bundle size, Lighthouse) | `init_experiment` / `run_experiment` / `log_experiment` tools; state in `.auto/` | the agent decides; keep auto-commits, anything else `git checkout -- .` | `checks.sh` gates a keep **in code**; `run_experiment` refuses any command that is not `.auto/measure.sh`; a MAD-based confidence score; auto-stop after 20 consecutive failures | npm package + skills |
| [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch) | a general-purpose Claude Code skill/plugin with 14 subcommands | commit first, then verify, then a separate guard command; failures are `git revert`ed so history keeps them | metric improves **and** the guard command passes | verify commands screened for dangerous shell, hooks blocking dangerous git, a Mann-Whitney regression check, blind judges, a line-count simplify gate | skills + Claude Code plugin |
| [evo-hq/evo](https://github.com/evo-hq/evo) | tree search over experiments, many hosts | subagents in worktrees; frontier strategies (argmax, top-k, epsilon-greedy, softmax, pareto) | node commits only if the score improved **and** all gates passed | the strongest set found: inherited gates, an auto-added held-out score floor, a verifier agent that checks for test-set leakage and shrunken eval commands before a run, and a post-run check that flags runs finishing in under 20% of the median duration | CLI + plugin |
| [Human-Agent-Society/CORAL](https://github.com/Human-Agent-Society/CORAL) | many agents in parallel against a shared leaderboard | each agent on `coral/<id>` in its own worktree; `coral eval` commits and queues; a separate grader daemon scores that commit in a detached worktree | nothing auto-reverts; agents move themselves back to a good attempt | the grading environment and answer keys live in `.coral/private/`, unreadable by the agents in Docker mode -- real isolation rather than an instruction | CLI + plugin |
| [MatthewZMD/agent-digivolve-harness](https://github.com/MatthewZMD/agent-digivolve-harness) | iterative improvement of prompts/documents with an eval package | candidate built in a worktree, cherry-picked in if kept | **train pass rate strictly up AND holdout not down**, enforced in code | an explicit holdout in the eval package; the human must approve the eval package before the baseline; evaluation by a separate subagent or judge panel | CLI + operator skill |
| [alfonsograziano/auto-agent](https://github.com/alfonsograziano/auto-agent) | improving *agents* against a golden dataset | a Node orchestrator runs Claude Code/Kiro in a target repo, one branch per hypothesis | the agent writes `Decision: CONTINUE\|ROLLBACK` and the orchestrator regexes it; unparseable means rollback | forbidden files and "run the evals once" are prompt-level only; the agent effectively grades itself | Node CLI |
| [trevin-creator/autoresearch-mlx](https://github.com/trevin-creator/autoresearch-mlx) | Karpathy's setup ported to Apple Silicon (MLX) | same loop; only `train.py` is ever staged; `results.tsv` is committed | same | `rigor.py`: the author measured ~0.03 bpb of re-run noise, so a candidate runs 3 seeds and is kept only if a bootstrap puts P(better) at 0.95+; hashes `train.py` so a config is never scored twice | scripts |

Also on the awesome list and worth knowing: Weco running the loop on the loop's
own code (and reporting KernelBench reward hacking dropping from 63% to 34%);
FML-bench, whose finding is that a greedy hill climber nearly matches tree
search across 18 ML tasks; BTCautoresearch, which uses walk-forward
out-of-sample testing; and Agon, a Claude Code plugin with an explicit auditor
role.

## What `arh` borrowed, changed, or refused

| from | borrowed | changed, and why |
|---|---|---|
| karpathy/autoresearch | the whole shape: `program.md` as the system prompt, branch `autoresearch/<tag>`, one editable file, a fixed training budget inside the frozen file, `results.tsv`, bits per byte, the progress chart, "a crash is data", the simplicity criterion | the rules are **enforced instead of stated**. `prepare.py` is hashed before and after every run, the diff is checked against an allowlist, and the branch is a private repository by default so a task can live inside someone else's repo. The 300 s budget became 60 s so an experiment fits a laptop minute. |
| pi-autoresearch | a fixed, harness-owned measurement command; a stop rule for repeated failure | the measurement command lives in `autoresearch.toml`, which the agent may not edit and the hook will not let it open -- rather than in a script the agent is explicitly allowed to change mid-loop. |
| uditgoenka/autoresearch | a second gate beyond the metric; statuses beyond keep/discard; a bounded default iteration count | our second gate is the holdout `[confirm]` run; `max_experiments` lives in the spec; statuses are keep/discard/crash/**invalid**, where invalid means "this number is not trustworthy" rather than "this idea did not work" -- a distinction none of the surveyed ledgers made, and the one a human most needs when reading the log. |
| evo | the "suspiciously fast run" heuristic; an auditing agent that reads the diff before the run | implemented as `[guards].min_duration_fraction` against the median kept duration, and as the `experiment-reviewer` subagent. We kept single-branch hill climbing rather than tree search: FML-bench's result is that greedy is close, and a laptop cannot afford parallel worktrees of a 60 s GPU job. |
| CORAL | the insight that isolation beats instruction | we cannot hide the data from training code that runs on the same machine, so the frozen half is protected by hash and allowlist instead, and the evaluator (not the trainer) owns the `METRIC` line. `[guards].forbid_patterns` rejects a diff that even mentions the private split helper. |
| digivolve | "holdout must not drop" as a mechanical keep rule | the same rule, optional per task: `[confirm]` re-runs the task on a split that was never used for selection and rejects a val-only improvement. Turned on for quickstart, documented but off for tinygpt because it doubles a 60 s experiment. |
| auto-agent | the failure mode to avoid | never let the proposer write the verdict. `arh run` computes it; the agent only reads it. |
| autoresearch-mlx | the honest noise measurement | we measured it too (2.5258 vs 2.5001 bpb for the identical baseline) and set `min_delta` above the noise floor, and we say in the README that single-run keeps are provisional. Multi-seed scoring with a bootstrap is the obvious next feature and is not implemented. |

Deliberately **not** copied: an agent-written `Decision:` line, an editable
measurement script, and telemetry.

## Harness engineering principles this is built on

Grounded in [wquguru/harness-books](https://github.com/wquguru/harness-books)
(*Harness Engineering: A Design Guide to Claude Code*, and the Claude
Code/Codex comparison), plus the Vizuara harness-engineering material. The
book's framing -- a harness is what makes an unreliable component usable, and
reliability belongs in the harness rather than in the model -- is the whole
argument for this project.

1. **Treat the model as an unstable component, not a teammate.** The proposer
   is allowed to be wrong every time. `arh` assumes that and makes wrongness
   cheap: every experiment is either committed or reverted within seconds, and
   the ledger records both.
2. **The prompt is part of the control plane, not personality.** `program.md`
   is the task's system prompt and lives beside the code it governs; the
   harness appends the facts it will enforce anyway (editable files, budget,
   metric direction) so the prompt and the runtime cannot drift apart.
3. **The loop is the heartbeat.** `arh loop` is an explicit episode loop with
   stop conditions (experiments, wall clock, three stalls), not a chat that
   happens to continue.
4. **Tools are managed execution interfaces.** The agent's file tools enforce
   the allowlist in code; `run_experiment` is the only path to a number. A
   permission that exists only in a prompt is not a permission.
5. **Context is working memory, governed in layers.** Long-lived state is the
   ledger on disk; per-episode context is rebuilt from it. That is why an
   8-hour run does not degrade: nothing important lives in the window.
6. **Error paths are main paths.** Crash, timeout, NaN, tampering and
   unparseable output each have a status, a reason string, a log file and a
   revert. There is no path that leaves the working tree in an unknown state.
7. **Verification must be independent.** The implementer never scores itself:
   the frozen evaluator computes the metric, the engine decides the verdict,
   and the `experiment-reviewer` subagent reads the diff with no stake in it.
8. **Institutions over tricks.** Everything a human would otherwise have to
   remember -- which files are frozen, how long a run may take, what counts as
   an improvement, what to do on a crash -- is written down in
   `autoresearch.toml` and enforced by the harness, so the loop behaves the
   same whether it is driven by Claude Code, by an OpenRouter model, or by a
   person at 2 a.m.

The one principle this project adds, which the surveyed harnesses mostly leave
implicit: **a harness that can only say "better" or "worse" is not enough. It
also has to be able to say "I do not trust this number."** That is what the
`invalid` status is for, and it is the status that fires when an experiment
tries to move the ruler instead of the model.
