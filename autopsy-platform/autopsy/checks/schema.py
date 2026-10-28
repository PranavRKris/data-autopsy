"""Schema drift: compare the live columns with the learned baseline."""
from __future__ import annotations

from autopsy.checks.context import CheckContext, skipped
from autopsy.core.models import FAIL, OK, WARN, Finding

CHECK = "check_schema"


def check_schema(ctx: CheckContext, dataset: str) -> Finding:
    ds = ctx.dataset(dataset)
    base = ctx.baseline_for(ds)
    if not base:
        return skipped(CHECK, ds, "no baseline for this dataset (run 'autopsy baseline' on a healthy period)")

    expected = {c["name"]: c["type"] for c in base["columns"]}
    live = {c.name: c.type for c in ctx.connector.describe(ds.source)}
    missing = [c for c in expected if c not in live]
    new = [c for c in live if c not in expected]
    retyped = [{"column": c, "was": expected[c], "now": live[c]}
               for c in expected if c in live and expected[c].upper() != live[c].upper()]
    evidence = {"missing": missing, "new": new, "retyped": retyped}

    if missing or retyped:
        parts = []
        if missing:
            parts.append(f"missing column(s) {', '.join(missing)}")
        if new:
            parts.append(f"new column(s) {', '.join(new)}")
        if retyped:
            parts.append("retyped " + ", ".join(r["column"] for r in retyped))
        return Finding(CHECK, ds.name, FAIL, "Schema changed since the baseline: " + "; ".join(parts) + ".",
                       evidence, ["profile_dataset"])
    if new:
        return Finding(CHECK, ds.name, WARN, f"New column(s) since the baseline: {', '.join(new)}.", evidence)
    return Finding(CHECK, ds.name, OK, "Columns and types match the baseline.", evidence)
