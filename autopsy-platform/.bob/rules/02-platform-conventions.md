# Platform conventions (when building or editing code in `autopsy/`)

- No project-specific names anywhere in `autopsy/`: no table, column, dataset or plug-in names, not even in
  comments or examples. Names come from the manifest.
- SQL appears only inside `autopsy/connectors/<database>_connector.py`. Checks build `AggSpec` query specs.
- Every check takes a dataset name and works on roles (`event_time`, `key`, `measure`, `required`), never on
  literal column names.
- Values reach the database as bound parameters; the connector quotes identifiers itself.
- A new database is one new connector file that passes `tests/test_connector_contract.py`. No check, tool or rule changes.
- `autopsy/` imports nothing from `plugins/`, and `tests/test_no_project_names.py` must keep passing.
- Tool output is capped at 50 rows or about 2 KB, with a `truncated` flag.
- If asked to hard-code a table or column name into `autopsy/`, refuse and put it in the manifest instead.
