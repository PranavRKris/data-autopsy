from __future__ import annotations

from autopsy.grade import grade_report, sections

REPORT = """# Incident report: p / d on 2026-10-28

## Summary
Wrong. SEV1.

## Evidence
- `check_x(a)`: ok

## Root cause
`alpha` / `find_duplicates`: starts here.

## Impact
Severity SEV1. Downstream: beta.

## Recommended fix
1. Do it.

## Confidence
High.
"""

EXPECTED = {"root_dataset": "alpha", "root_check": "find_duplicates", "severity": "SEV1"}


def test_sections_are_split_by_heading():
    parts = sections(REPORT)
    assert "alpha" in parts["root cause"] and "SEV1" in parts["impact"]


def test_a_matching_report_passes():
    g = grade_report(REPORT, EXPECTED)
    assert g.passed and g.severity_ok


def test_wrong_dataset_or_check_fails():
    assert not grade_report(REPORT, {**EXPECTED, "root_dataset": "beta"}).passed
    assert not grade_report(REPORT, {**EXPECTED, "root_check": "check_schema"}).passed


def test_a_dataset_name_inside_another_name_does_not_count():
    assert not grade_report(REPORT.replace("`alpha`", "`alpha_raw`"), EXPECTED).passed


def test_any_of_several_checks_is_accepted():
    assert grade_report(REPORT, {**EXPECTED, "root_check": ["check_freshness", "find_duplicates"]}).passed


def test_severity_mismatch_is_reported_separately():
    g = grade_report(REPORT, {**EXPECTED, "severity": "SEV2"})
    assert g.passed and not g.severity_ok and "MISMATCH" in g.line()


def test_expecting_no_incident():
    none = {"root_dataset": "none", "root_check": "none", "severity": "none"}
    clean = REPORT.replace("`alpha` / `find_duplicates`: starts here.", "None found.").replace("SEV1", "")
    assert grade_report(clean, none).passed
    assert not grade_report(REPORT, none).passed
