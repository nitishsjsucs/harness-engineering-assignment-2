"""What this session cost, taken from the provider's own numbers.

OpenRouter returns `usage.cost` in USD on every response, which beats
multiplying tokens by a price list we would have to keep up to date. Grouping by
model matters because a fallback chain means not every call was answered by the
model you asked for.

Other routes (OpenAI, Google) report tokens but no price. The ledger says so
instead of printing a confident $0.000000: a wrong number is worse than "n/a".
"""


class Ledger:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, usage: dict) -> None:
        self.calls.append(dict(usage))

    @property
    def priced(self) -> list[dict]:
        """The calls whose provider told us what they cost."""
        return [call for call in self.calls if call.get("cost") is not None]

    @property
    def total(self) -> float | None:
        """USD across the priced calls, or None when nothing was priced at all."""
        return sum(call["cost"] for call in self.priced) if self.priced else None

    def by_model(self) -> dict[str, dict]:
        grouped: dict[str, dict] = {}
        for call in self.calls:
            row = grouped.setdefault(
                call.get("model") or "unknown",
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cost": None},
            )
            row["calls"] += 1
            for field in ("prompt_tokens", "completion_tokens", "cached_tokens"):
                row[field] += call.get(field) or 0
            if call.get("cost") is not None:
                row["cost"] = (row["cost"] or 0.0) + call["cost"]
        return grouped

    def table(self) -> list[str]:
        """Lines ready to print. Text, so the UI stays free of formatting rules."""
        lines = [f"  {'model':<30}{'calls':>6}{'in':>9}{'cached':>8}{'out':>7}{'cost':>11}"]
        for name, row in sorted(self.by_model().items(), key=lambda item: -(item[1]["cost"] or 0.0)):
            cost_text = f"{row['cost']:.6f}" if row["cost"] is not None else "n/a"
            lines.append(
                f"  {name[:30]:<30}{row['calls']:>6}{row['prompt_tokens']:>9}"
                f"{row['cached_tokens']:>8}{row['completion_tokens']:>7}{cost_text:>11}"
            )
        total = self.total
        total_text = f"{total:.6f}" if total is not None else "n/a"
        lines.append(f"  {'total':<30}{len(self.calls):>6}{'':>9}{'':>8}{'':>7}{total_text:>11}")
        if total is None:
            lines.append("  this provider reports no cost; the token counts above are exact")
        elif len(self.priced) != len(self.calls):
            missing = len(self.calls) - len(self.priced)
            lines.append(f"  {missing} call(s) reported no cost and are not in the total")
        return lines
