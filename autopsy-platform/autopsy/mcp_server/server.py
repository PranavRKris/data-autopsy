"""MCP server: six generic, read-only tools over one project's manifest, spoken over stdio.

The server code is identical for every project; only the manifest path differs.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:                                            # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:                     # mcp 2.x renamed it
    from mcp.server.mcpserver import MCPServer as FastMCP

from autopsy.core.models import AutopsyError
from autopsy.mcp_server.tools import Tools


def build_server(tools: Tools) -> FastMCP:
    mcp = FastMCP("autopsy")

    @mcp.tool()
    def describe_project() -> dict[str, Any]:
        """Start here. Lists the project's datasets with their roles, business_visible flags, lineage
        (feeds = downstream, fed_by = upstream) and which checks are possible for each. This is the
        only source of dataset names for the rest of the investigation."""
        return tools.describe_project()

    @mcp.tool()
    def check_freshness(dataset: str) -> dict[str, Any]:
        """Is the newest row of `dataset` recent enough? Returns newest event time, age in hours,
        the limit, and days with zero rows in the last 14."""
        return tools.check_freshness(dataset)

    @mcp.tool()
    def check_schema(dataset: str) -> dict[str, Any]:
        """Compare `dataset`'s live columns with the learned baseline: missing, new and retyped columns."""
        return tools.check_schema(dataset)

    @mcp.tool()
    def profile_dataset(dataset: str, columns: list[str] | None = None) -> dict[str, Any]:
        """Null rate, min, max and median of `dataset`'s measure and required columns (or the given
        `columns`), with limits and the comparison to the baseline."""
        return tools.profile_dataset(dataset, columns)

    @mcp.tool()
    def find_duplicates(dataset: str) -> dict[str, Any]:
        """Count repeated values of `dataset`'s key role: repeated keys, extra rows, per-day counts, sample keys."""
        return tools.find_duplicates(dataset)

    @mcp.tool()
    def check_volume(dataset: str) -> dict[str, Any]:
        """Rows per day for the last 14 complete days against the trailing median, and the days outside the allowed band."""
        return tools.check_volume(dataset)

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m autopsy.mcp_server", description=__doc__)
    parser.add_argument("--manifest", default=os.environ.get("AUTOPSY_MANIFEST"),
                        help="path to the project manifest (default: $AUTOPSY_MANIFEST)")
    args = parser.parse_args(argv)
    if not args.manifest:
        parser.error("give --manifest <path> or set AUTOPSY_MANIFEST")
    try:
        tools = Tools.from_manifest_path(args.manifest)
    except AutopsyError as exc:
        print(f"autopsy: {exc.message}", file=sys.stderr)       # stdout belongs to the MCP protocol
        return 2
    build_server(tools).run(transport="stdio")
    return 0
