"""Grade a report against a plug-in's expected results. Knows nothing about any plug-in except that file."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from autopsy.core.models import ManifestError

_SEVERITY = re.compile(r"\bSEV[1-4]\b")
_NO_INCIDENT = re.compile(r"\b(none|no incident|no root cause)\b", re.I)


@dataclass
class Grade:
    scenario: str
    root_ok: bool
    severity_ok: bool
    detail: str

    @property
    def passed(self) -> bool:
        return self.root_ok

    def line(self) -> str:
        verdict = "PASS" if self.root_ok else "FAIL"
        sev = "severity ok" if self.severity_ok else "severity MISMATCH"
        return f"{self.scenario}: {verdict} ({sev}). {self.detail}"


def sections(report: str) -> dict[str, str]:
    """Map '## Heading' (lower-cased) to the text under it."""
    out: dict[str, str] = {}
    current = None
    for line in report.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            out[current] = ""
        elif current is not None:
            out[current] += line + "\n"
    return out


def load_expected(path: str | Path, scenario: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    try:
        return data["scenarios"][scenario]
    except (KeyError, TypeError):
        raise ManifestError(f"scenario {scenario!r} not found in {path}") from None


def grade_report(report: str, expected: dict[str, Any], scenario: str = "?") -> Grade:
    parts = sections(report)
    cause = parts.get("root cause", "")
    impact = parts.get("impact", "") or parts.get("summary", "")
    found = _SEVERITY.search(impact) or _SEVERITY.search(report)
    got_sev = found.group(0) if found else "none"
    want_sev = str(expected.get("severity", "none"))
    severity_ok = got_sev == want_sev

    want_dataset = str(expected.get("root_dataset", "none"))
    if want_dataset == "none":
        root_ok = bool(_NO_INCIDENT.search(cause)) and not _SEVERITY.search(cause)
        return Grade(scenario, root_ok, severity_ok,
                     f"expected no incident; Root cause section {'says none' if root_ok else 'names a problem'}.")

    checks = expected.get("root_check", [])
    checks = [checks] if isinstance(checks, str) else list(checks)
    has_dataset = re.search(rf"\b{re.escape(want_dataset)}\b", cause) is not None
    has_check = any(re.search(rf"\b{re.escape(c)}\b", cause) for c in checks)
    return Grade(
        scenario, has_dataset and has_check, severity_ok,
        f"expected {want_dataset} / {'|'.join(checks)} / {want_sev}; "
        f"Root cause {'names' if has_dataset else 'misses'} the dataset and {'names' if has_check else 'misses'} "
        f"the check; severity {got_sev}.",
    )
