"""Generic checks. They work on datasets and roles, never on table or column names."""
from autopsy.checks.context import CheckContext
from autopsy.checks.duplicates import find_duplicates
from autopsy.checks.freshness import check_freshness
from autopsy.checks.profile import profile_dataset
from autopsy.checks.schema import check_schema
from autopsy.checks.volume import check_volume

__all__ = [
    "CheckContext", "check_freshness", "check_schema", "check_volume", "find_duplicates", "profile_dataset",
]
