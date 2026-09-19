"""progress.png + report.md -- what the loop actually achieved.

The chart is the same idea as Karpathy's progress chart: one dot per
experiment, kept ones highlighted, and a step line for the best score so far.

Colour choices, so they can be defended on camera: kept/discarded/failed are
three *roles*, not three arbitrary series, so each gets its own marker shape as
well as its own colour (identity is never colour-alone); discarded runs are
deliberately recessive grey; there is exactly one y-axis; and the grid sits
behind the data.
"""

from __future__ import annotations

from pathlib import Path

KEPT = "#1B7F5F"  # green: this experiment moved the metric
DISCARDED = "#8A9099"  # muted grey: measured, then reverted
FAILED = "#C2453D"  # status red: crash or guard violation, no valid metric
BEST = "#2563EB"  # blue: running best


def write_report(harness, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = Path(out_dir or harness.state_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = harness.ledger.records()
    png = out_dir / "progress.png"
    md = out_dir / "report.md"
    plot_progress(records, harness.spec, png)
    md.write_text(render_markdown(records, harness, png.name))
    return png, md


def plot_progress(records: list[dict], spec, png_path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")  # no display on a headless laptop run
    import matplotlib.pyplot as plt

    scored = [r for r in records if r["metric"] is not None]
    failed = [r for r in records if r["metric"] is None]
    kept = [r for r in scored if r["status"] == "keep"]
    other = [r for r in scored if r["status"] != "keep"]

    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    ax.grid(True, color="#E6E6E3", linewidth=0.8)
    ax.set_axisbelow(True)

    if kept:
        xs, ys = _running_best(records, spec)
        ax.step(xs, ys, where="post", color=BEST, linewidth=2, label="best so far", zorder=2)
    ax.scatter(
        [r["id"] for r in other], [r["metric"] for r in other],
        s=42, facecolors="none", edgecolors=DISCARDED, linewidths=1.4, label="discarded", zorder=3,
    )
    ax.scatter(
        [r["id"] for r in kept], [r["metric"] for r in kept],
        s=70, color=KEPT, marker="o", edgecolors="white", linewidths=1.2, label="kept", zorder=4,
    )
    if failed and scored:
        # No metric to plot, so park failures on the worst edge of the axis and
        # mark them with an x: visible, but never mistaken for a score.
        edge = max(r["metric"] for r in scored) if spec.direction == "min" else min(r["metric"] for r in scored)
        ax.scatter(
            [r["id"] for r in failed], [edge] * len(failed),
            s=60, color=FAILED, marker="x", linewidths=1.8, label="crash / invalid", zorder=5,
        )

    values = [r["metric"] for r in scored]
    if values and min(values) > 0 and max(values) / min(values) > 20:
        # One big early win would otherwise squash every later improvement into
        # the axis floor; on a positive metric a log axis keeps them readable.
        ax.set_yscale("log")

    for i, r in enumerate(kept):  # direct labels on the interesting points only
        ax.annotate(
            _shorten(r["description"]),
            (r["id"], r["metric"]),
            textcoords="offset points",
            xytext=(6, 8 if i % 2 == 0 else -14),  # alternate, so labels do not collide
            fontsize=7,
            color="#3C4043",
        )

    ax.margins(x=0.05, y=0.15)  # room for the direct labels, top and bottom
    ax.set_xlabel("experiment")
    ax.set_ylabel(f"{spec.metric} ({'lower' if spec.direction == 'min' else 'higher'} is better)")
    ax.set_title(f"arh autoresearch: {spec.name} -- {len(kept)} kept of {len(records)} experiments", loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)
    return png_path


def _running_best(records: list[dict], spec) -> tuple[list, list]:
    xs, ys, best = [], [], None
    for r in records:
        if r["status"] == "keep" and r["metric"] is not None:
            best = r["metric"]
        if best is not None:
            xs.append(r["id"])
            ys.append(best)
    if xs:  # extend the line to the right edge so the last value is readable
        xs.append(records[-1]["id"])
        ys.append(ys[-1])
    return xs, ys


def render_markdown(records: list[dict], harness, png_name: str) -> str:
    spec = harness.spec
    state = harness.state
    kept = [r for r in records if r["status"] == "keep"]
    counts = {s: sum(r["status"] == s for r in records) for s in ("keep", "discard", "crash", "invalid")}
    baseline = (state.get("baseline") or {}).get("metric")
    best = (state.get("best") or {}).get("metric")

    lines = [
        f"# autoresearch report: {spec.name}",
        "",
        f"- branch: `{state['branch']}` ({state['git_mode']} git mode)",
        f"- metric: `{spec.metric}` ({spec.direction})",
        f"- experiments: {len(records)} "
        f"(keep {counts['keep']}, discard {counts['discard']}, crash {counts['crash']}, invalid {counts['invalid']})",
    ]
    if baseline is not None and best is not None:
        change = (best - baseline) / abs(baseline) * 100 if baseline else 0.0
        lines.append(f"- baseline `{baseline:.6g}` -> best `{best:.6g}` ({change:+.1f}%)")
    lines += ["", f"![progress]({png_name})", "", "## Kept improvements", ""]
    if kept:
        lines += ["| # | commit | " + spec.metric + " | delta | description |", "|---|---|---|---|---|"]
        for r in kept:
            delta = f"{r['delta']:+.4g}" if r["delta"] is not None else "-"
            lines.append(f"| {r['id']} | `{r['commit']}` | {r['metric']:.6g} | {delta} | {_clean(r['description'])} |")
    else:
        lines.append("_nothing kept yet._")

    lines += ["", "## Every experiment", "", "| # | status | metric | duration | description | reason |", "|---|---|---|---|---|---|"]
    for r in records:
        metric = f"{r['metric']:.6g}" if r["metric"] is not None else "-"
        lines.append(
            f"| {r['id']} | {r['status']} | {metric} | {r['duration_s']:.1f}s | "
            f"{_clean(r['description'])} | {_clean(r.get('reason', ''))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _clean(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def _shorten(text: str, width: int = 28) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "..."
