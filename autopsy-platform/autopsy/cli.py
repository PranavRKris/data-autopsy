"""Command line: autopsy validate | baseline | grade | project-name | investigate | serve."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from autopsy.core.baseline import learn_baseline, save_baseline, utcnow
from autopsy.core.manifest import load_manifest, validate_against
from autopsy.core.models import AutopsyError
from autopsy.core.registry import create_connector


def _connect(manifest):
    return create_connector(manifest.connector, manifest.connection)


def cmd_validate(args) -> int:
    manifest = load_manifest(args.manifest)
    issues = validate_against(manifest, _connect(manifest))
    for issue in issues:
        print(issue)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        print(f"INVALID: {len(errors)} error(s) in {args.manifest}")
        return 1
    print(f"OK: {len(manifest.datasets)} dataset(s) in project {manifest.project!r} match the live database")
    return 0


def cmd_baseline(args) -> int:
    manifest = load_manifest(args.manifest)
    data = learn_baseline(manifest, _connect(manifest), utcnow(), args.since, args.until)
    path = save_baseline(data)
    print(f"Baseline for {manifest.project!r} saved to {path}")
    return 0


def cmd_grade(args) -> int:
    from autopsy.grade import grade_report, load_expected

    grade = grade_report(Path(args.report).read_text(encoding="utf-8"), load_expected(args.expected, args.scenario),
                         args.scenario)
    print(grade.line())
    return 0 if grade.passed and (grade.severity_ok or not args.strict_severity) else 1


def cmd_project_name(args) -> int:
    print(load_manifest(args.manifest).project)
    return 0


def cmd_investigate(args) -> int:
    from autopsy.investigate import investigate
    from autopsy.mcp_server.tools import Tools

    inv = investigate(Tools.from_manifest_path(args.manifest), [args.dataset] if args.dataset else None)
    if args.output:
        Path(args.output).write_text(inv.report, encoding="utf-8")
    else:
        print(inv.report)
    return 0


def cmd_serve(args) -> int:
    from autopsy.service.serve import main as serve_main

    return serve_main(args.rest)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "serve":          # serve has its own options (--host, --port, ...)
        return cmd_serve(argparse.Namespace(rest=argv[1:]))
    parser = argparse.ArgumentParser(prog="autopsy", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the web UI and API (autopsy serve --help for its options)")

    p = sub.add_parser("validate", help="check the manifest against the live database")
    p.add_argument("manifest")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("baseline", help="learn normal values from the current (healthy) data into state/")
    p.add_argument("manifest")
    p.add_argument("--since", help="only learn from event times at or after this ISO date")
    p.add_argument("--until", help="only learn from event times before this ISO date")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("grade", help="compare a report with a plug-in's expected results")
    p.add_argument("report")
    p.add_argument("expected")
    p.add_argument("scenario")
    p.add_argument("--strict-severity", action="store_true", help="also fail when the severity differs")
    p.set_defaults(func=cmd_grade)

    p = sub.add_parser("project-name", help="print the project name from a manifest")
    p.add_argument("manifest")
    p.set_defaults(func=cmd_project_name)

    p = sub.add_parser("investigate", help="run the reference investigator (no LLM) and print a report")
    p.add_argument("manifest")
    p.add_argument("--dataset", help="start from this dataset instead of the business-visible ones")
    p.add_argument("--output", help="write the report to this file")
    p.set_defaults(func=cmd_investigate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AutopsyError as exc:
        print(f"autopsy: {exc.code}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
