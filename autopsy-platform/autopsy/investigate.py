"""Reference investigator: the doc's investigation steps run deterministically, with no LLM.

It calls the same tool functions Bob calls through MCP, so it verifies the tools, the severity
rubric and the grader offline. Bob's run is the real investigation; this is its dry-run oracle.
It names no table or column: every name comes from describe_project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autopsy.core.models import FAIL, OK, SKIPPED, WARN
from autopsy.mcp_server.tools import Tools

CHECK_ORDER = ("check_freshness", "check_volume", "check_schema", "profile_dataset", "find_duplicates")
# When several checks fail on the root dataset, the first of these names the cause; volume is usually a symptom.
ROOT_PRIORITY = ("find_duplicates", "check_schema", "profile_dataset", "check_freshness", "check_volume")

FIXES = {
    "find_duplicates": [
        "Find the load or batch that wrote the repeated key values (see the sample keys and the days with extra rows).",
        "Confirm with the owning team whether that load ran more than once.",
        "Remove the extra copies in the source, and make the load idempotent so a re-run cannot double rows.",
        "Rebuild every downstream dataset listed under Impact once the source is clean.",
    ],
    "check_schema": [
        "Compare the column list in the evidence with what the upstream producer now sends.",
        "Confirm with the producer whether the change was intended, and agree a mapping or a rollback.",
        "Update the pipeline's handling of the changed column so it no longer falls back to a default value.",
        "Rebuild every downstream dataset listed under Impact.",
    ],
    "profile_dataset": [
        "Find the source or feed that started sending the unexpected values (see the columns and window in the evidence).",
        "Confirm the cause with the owning team, for example a null key, a changed unit or a bad parser.",
        "Correct the feed or add a validation step in front of it so bad rows are rejected or quarantined.",
        "Reload the affected period and rebuild every downstream dataset listed under Impact.",
    ],
    "check_freshness": [
        "Check whether the upstream producer or the scheduled load stopped, and since when (see the newest event time).",
        "Restart or backfill the missing period once the producer is healthy.",
        "Rebuild every downstream dataset listed under Impact.",
    ],
    "check_volume": [
        "Compare the days outside the band with the producer's own record counts for those days.",
        "Backfill missing days, or remove extra rows, at the source.",
        "Rebuild every downstream dataset listed under Impact.",
    ],
}


@dataclass
class Investigation:
    project: str
    start: list[str]
    findings: dict[str, dict[str, dict[str, Any]]]       # dataset -> tool -> finding
    root_dataset: str | None = None
    root_check: str | None = None
    severity: str | None = None
    report: str = ""
    other_roots: list[str] = field(default_factory=list)


def investigate(tools: Tools, start: list[str] | None = None) -> Investigation:
    described = tools.describe_project()
    datasets = {d["name"]: d for d in described["datasets"]}
    start = start or [n for n, d in datasets.items() if d["business_visible"]] or \
        [n for n, d in datasets.items() if not d["feeds"]]

    # Aggregates can hide an upstream problem, so the whole upstream closure is checked, not just
    # the datasets that already look wrong.
    scope = list(start)
    for name in start:
        scope += [a for a in tools.manifest.ancestors(name) if a not in scope]

    findings: dict[str, dict[str, dict[str, Any]]] = {}
    for name in scope:
        findings[name] = {t: tools.call(t, name) for t in CHECK_ORDER if t in datasets[name]["possible_checks"]}

    failing = {n: [t for t, f in fs.items() if f.get("status") == FAIL] for n, fs in findings.items()}
    failing = {n: ts for n, ts in failing.items() if ts}
    roots = [n for n in failing if not any(a in failing for a in tools.manifest.ancestors(n))]

    inv = Investigation(tools.manifest.project, start, findings)
    if roots:
        scored = [(_severity(n, _root_check(failing[n]), findings[n], tools, datasets), n) for n in roots]
        scored.sort(key=lambda s: (int(s[0][-1]), roots.index(s[1])))
        inv.severity, inv.root_dataset = scored[0]
        inv.root_check = _root_check(failing[inv.root_dataset])
        inv.other_roots = [n for _, n in scored[1:]]
    else:
        warned = [n for n, fs in findings.items() if any(f.get("status") == WARN for f in fs.values())]
        if warned:
            inv.root_dataset = warned[0]
            inv.root_check = next(t for t, f in findings[warned[0]].items() if f.get("status") == WARN)
            inv.severity = "SEV4"
    inv.report = _report(inv, tools, datasets, failing)
    return inv


def _root_check(failed: list[str]) -> str:
    return next(t for t in ROOT_PRIORITY if t in failed)


def _severity(name: str, check: str, findings: dict[str, Any], tools: Tools, datasets: dict) -> str:
    """The rubric, decided from check type, business_visible and lineage; never from a name."""
    reaches_visible = any(datasets[d]["business_visible"] for d in [name, *tools.manifest.descendants(name)])
    finding = findings[check]
    wrong_values = "SEV1" if reaches_visible else "SEV2"
    if check == "find_duplicates":
        return wrong_values
    if check == "profile_dataset":
        kinds = set(finding["evidence"].get("problem_kinds", []))
        return wrong_values if kinds & {"range", "median_shift"} else "SEV2"
    if check == "check_schema":
        return "SEV2"
    if check == "check_volume":
        outside = finding["evidence"].get("outside_band", [])
        return "SEV2" if outside and all(o["change"] > 0 for o in outside) else "SEV3"
    return "SEV3"


def _report(inv: Investigation, tools: Tools, datasets: dict, failing: dict[str, list[str]]) -> str:
    m = tools.manifest
    now = tools.now().date().isoformat()
    lines = [f"# Incident report: {m.project} / {', '.join(inv.start)} on {now}", ""]

    evidence = []
    skipped = []
    for name, fs in inv.findings.items():
        for tool, f in fs.items():
            if "error" in f:
                evidence.append(f"- `{tool}({name})`: error {f['error']}: {f['message']}")
            else:
                evidence.append(f"- `{tool}({name})`: {f['status']}. {f['summary']}")
                if f["status"] == SKIPPED:
                    skipped.append(f"{tool}({name})")
    has_lineage = any(d["feeds"] for d in datasets.values())

    if inv.root_dataset is None:
        total = sum(len(fs) for fs in inv.findings.values())
        lines += ["## Summary", f"No incident found: no check failed across {len(inv.findings)} dataset(s) "
                  f"({total} checks run).", ""]
        lines += ["## Evidence", *evidence, ""]
        lines += ["## Root cause", "None found. No dataset has a failing check.", ""]
        lines += ["## Impact", "None. No dataset shows wrong data.", ""]
        lines += ["## Recommended fix", "1. None needed.", ""]
        confidence = "high" if not skipped else "medium"
    else:
        root, check = inv.root_dataset, inv.root_check
        finding = inv.findings[root][check]
        downstream = m.descendants(root)
        bad_down = [d for d in downstream if d in failing]
        visible = [d for d in [root, *downstream] if datasets[d]["business_visible"]]
        what = "A quality warning was found" if finding["status"] == WARN else "Data is wrong"
        lines += ["## Summary",
                  f"{what} in `{root}` ({check}): {finding['summary']} Severity {inv.severity}.", ""]
        lines += ["## Evidence", *evidence, ""]
        lines += ["## Root cause",
                  f"`{root}` / `{check}`: the problem starts here, the most upstream failing dataset. {finding['summary']}"
                  + (f" Other independent roots: {', '.join(inv.other_roots)}." if inv.other_roots else ""), ""]
        impact = [f"Severity {inv.severity}."]
        impact.append(f"Downstream of `{root}`: {', '.join(downstream) if downstream else 'nothing'}.")
        if bad_down:
            impact.append(f"Failing downstream checks: {', '.join(bad_down)}.")
        if visible:
            impact.append(f"Business-visible dataset(s) affected: {', '.join(visible)}.")
        impact.append(_severity_reason(inv.severity, check))
        lines += ["## Impact", " ".join(impact), ""]
        lines += ["## Recommended fix", *[f"{i}. {s}" for i, s in enumerate(FIXES[check], 1)], ""]
        confidence = "high" if has_lineage and finding["status"] == FAIL and not skipped else "medium"
        if not has_lineage:
            confidence = "medium"

    notes = []
    if not has_lineage:
        notes.append("no lineage is declared, so each failing dataset is reported separately")
    if skipped:
        notes.append("could not check: " + ", ".join(skipped))
    if not tools.baseline():
        notes.append("no baseline was available, so only manifest limits were used")
        confidence = "medium" if confidence == "high" else confidence
    lines += ["## Confidence", confidence.capitalize() + (". " + "; ".join(notes).capitalize() + "." if notes else "."), ""]
    return "\n".join(lines)


def _severity_reason(severity: str, check: str) -> str:
    return {
        "SEV1": "Wrong values reach a business-visible dataset, with a large error.",
        "SEV2": "Wrong values with a partial effect, or only in datasets no business user sees.",
        "SEV3": "Data is late or missing, but the values present are correct.",
        "SEV4": "Quality warning with no measurable effect yet.",
    }[severity]
