# Pipeline Autopsy

A platform in which IBM Bob investigates why a data pipeline's output is wrong, for any project and any
database, using read-only access. Design: [Pipeline_Autopsy_Design_Doc_Platform.md](../Pipeline_Autopsy_Design_Doc_Platform.md).

The platform never knows a table name, a column name or a SQL dialect. A **connector** hides the database,
a **manifest** hides the project, and a learned **baseline** replaces hand-written rules.

```
autopsy/core/        models, manifest loader + validator, baselines, connector registry
autopsy/connectors/  base interface + one file per source (duckdb, sqlite, files, postgres): the only code with SQL
autopsy/checks/      freshness, schema, profile, duplicates, volume (work on roles, not names)
autopsy/mcp_server/  six read-only tools over stdio; the same functions the tests call
autopsy/service/     web UI + JSON API: connections, mapping, run history, incidents, schedule (autopsy serve)
autopsy/cli.py       autopsy validate | baseline | grade | project-name | investigate | serve
.bob/                custom mode + rules for the Incident Investigator
investigator/        investigate.sh: one headless Bob run
../plugins/          acme_shop (test case, plus a live demo shop in app/ and demo/), sensor_readings (second project)
```

## Quick start

Dependencies are declared in `pyproject.toml`; there is no `requirements.txt`. Installing the package installs them
(`pyyaml`, `mcp`, `duckdb`, `starlette`, `uvicorn`; add the `postgres` extra for `psycopg`).

```bash
python -m venv .venv
source .venv/Scripts/activate                            # Git Bash; PowerShell: .venv\Scripts\Activate.ps1; Linux/macOS: source .venv/bin/activate
pip install -e "autopsy-platform[dev]"
pytest autopsy-platform                                  # 186 tests, no Bob needed

# the live demo: a believable shop you can break, with Autopsy watching it (see "The live demo")
python plugins/acme_shop/demo/run_demo.py
python plugins\acme_shop\demo\run_demo.py --autopsy-port 8766

# the scripted scenarios against the Acme Shop test plug-in (bash)
export AUTOPSY_PYTHON="$(which python)"
bash plugins/acme_shop/scripts/run_all.sh reference      # deterministic investigator
bash plugins/acme_shop/scripts/run_all.sh bob            # real Bob (needs the Bob Shell and the MCP registration below)
```

`autopsy serve` and the other commands only run the platform; they install nothing. Run them with the Python of the venv
that has the package installed (`.venv\Scripts\python -m autopsy.cli serve`, or `autopsy serve` once the venv is active).

Onboarding any project takes four commands and no platform code:

```bash
$EDITOR manifest.yaml                                    # map roles to the project's columns
autopsy validate manifest.yaml                           # every role column exists and has the right type
autopsy baseline manifest.yaml                           # learn normal values from healthy data into state/<project>.json
investigator/investigate.sh manifest.yaml first-run      # reports/incident_<project>_first-run.md
```

## The web UI

```bash
pip install -e "autopsy-platform[dev]"          # add ,postgres for the PostgreSQL driver
autopsy serve                                    # http://127.0.0.1:8765, state in autopsy-platform/state/
```

Everything a person does in the UI is also an HTTP call ([docs/api.md](docs/api.md)), and a project made in the UI is an
ordinary manifest (`state/manifests/<project>.yaml`) that the CLI and Bob use unchanged.

1. **Add a connection.** Pick a connector, fill the form, press *Test connection* (it lists the tables it found), save.
2. **Create a project.** Pick tables; the service suggests roles from column types, nullability and uniqueness, and a
   person confirms them; draw the lineage; the mapping is checked against the live database before it is saved.
   Or *import* an existing manifest file, which brings its connection along.
3. **Learn a baseline** from healthy data, then **run checks**. A monitor run checks every dataset; a failure starts an
   investigation that names the most upstream failing dataset and opens an incident with a severity and a report.
   The next clean run resolves it.
4. **Watch.** Health matrix, lineage graph, trend charts against the learned baseline, run history, incidents, and a
   per-project schedule. *Setup* shows the manifest and the MCP entry for pointing Bob at the same project.

### Connectors

| Connector | Source | Status |
|---|---|---|
| `duckdb` | a DuckDB file, opened read-only | contract-tested |
| `sqlite` | a SQLite file, opened `mode=ro` | contract-tested |
| `files` | a folder of `.csv`, `.tsv`, `.parquet`; each file is a dataset | contract-tested. Files are loaded into memory (limit 1 GB) and the connection then has file and network access switched off |
| `postgres` | a PostgreSQL database; read-only session, 30 s statement timeout | **not run against a live server** (see below) |

A new source is one connector file plus a form description in `autopsy/connectors/specs.py`; the same contract tests apply.

### Security

- **No authentication.** `autopsy serve` binds to `127.0.0.1` and warns if you bind elsewhere. Anyone who can reach it can
  add connections and read what they expose, including any file path the service process can read. Put it behind
  your own access control before sharing it.
- Browser pages on other sites cannot drive it: the Host header must be loopback, cross-origin writes are refused, and
  write bodies must be `application/json`.
- Passwords entered in the UI are stored **as plain text** in `state/secrets.json` (owner-only permissions where the OS
  supports them), exported into the service's environment, and referred to by variable name everywhere else. No endpoint
  returns them. Use a real secret manager for anything beyond a single-user machine, and give the database account only SELECT.

## The live demo

`plugins/acme_shop/` contains a small production-style shop, built as if by another team, so the platform can be
shown finding real incidents that a person causes:

```bash
python plugins/acme_shop/demo/run_demo.py                       # add --autopsy-port 8766 if 8765 is in use
```

The launcher talks to the platform only through its HTTP API. It reseeds healthy data into `plugins/acme_shop/demo/data/`
(never a database you set up by hand), starts Pipeline Autopsy and imports the plug-in's manifest, learns the baseline
from the healthy data, runs the first checks (18 of 18 pass), turns on a one-minute schedule with auto-investigate, then
starts the shop and opens both pages. Ctrl+C stops everything.

| Page | Where | What it is |
|---|---|---|
| Shop | `http://127.0.0.1:8780/#/shop` | storefront: products, cart, checkout as a chosen customer and channel, a live feed of placed orders |
| Finance | `.../#/finance` | the back-office dashboard the business reads: revenue by day and channel, KPIs |
| Operations | `.../#/operations` | the pipeline (run now, auto-run), simulated customers, data counts, and the **Incident lab** |
| Pipeline Autopsy | `http://127.0.0.1:8765/#/projects/acme_shop` | health, lineage, trends, history, incidents with root cause and report |

**The flow.** In the Incident lab press *Make it happen*. The shop rebuilds its reports, Finance visibly goes wrong, and
within a minute (immediately with *Run checks*) Autopsy opens an incident that names the cause. Press *Roll back* in the
shop; the next check resolves the incident.

| Incident in the shop | What the business sees | What Autopsy should say |
|---|---|---|
| Partner feed replays a batch | one day of revenue doubles | `orders_raw` / `find_duplicates`, SEV1 |
| Checkout v2.4 renames a column | all revenue moves to an "unknown" channel | `orders_raw` / `check_schema`, SEV2 |
| Mobile release adds guest checkout | revenue about 40% low, nothing errors | `orders_raw` / `profile_dataset`, SEV2 |
| Order ingestion goes down | the last three days are missing | `orders_raw` / `check_freshness`, SEV3 |
| Pricing deploy sends cents | revenue 100 times too high | `orders_raw` / `profile_dataset`, SEV1 |

How it is built, and what to know before you present it:

- **Separate programs.** The shop (a standard-library Python server with its own pipeline subprocess) and the platform
  share only one DuckDB file, which the platform opens read-only. The shop imports nothing from `autopsy/`.
- **Sticky incidents.** An incident keeps affecting orders placed while it is live, and also rewrites the last few days of
  orders as if it had been live since then, because a demo cannot wait three days. *Roll back* restores the original
  values from the shop's own bookkeeping (its `app` schema, which the manifest never mentions). An order placed during an
  ingestion outage goes to a dead-letter queue and is replayed on roll back.
- **Shared-file robustness.** DuckDB allows one writer process, so the shop, the pipeline and the platform's connector
  all wait and retry while another process holds the file, recognising both the Linux and the Windows wording of the error.
- **Time.** Naive timestamps are read as UTC throughout (the platform's `utcnow()`, the shop's clock, the seed's default
  `--as-of`). A source that writes local time is off by its UTC offset: keep that in mind when you map a real database.
- **Detection thresholds.** One bad amount trips the manifest's value range at once, but null customer ids need more than
  2% of all rows to fail the profile check, which is why the guest-checkout incident rewrites several days of orders.
- **Presenter notes** (what Autopsy should find, and how the roll back works) are in each incident card in the lab.
- `autopsy-platform/tests/test_acme_app.py` checks it automatically: every incident is triggered, the platform's verdict
  is compared with `plugins/acme_shop/expected/expected_results.yaml`, the incident is rolled back and the platform must
  report clean. It also covers live orders under an incident, bad requests, the shop's cross-site guards, and the
  platform reading while the shop writes from a separate process.

## The six tools

`describe_project` (start here), `check_freshness`, `check_schema`, `profile_dataset`, `find_duplicates`,
`check_volume`. Each check takes a logical dataset name and returns one finding
(`status`: ok / warn / fail / skipped, `summary`, `evidence`, `next_checks`, `truncated`), capped at 50 rows or
about 2 KB. Errors come back as `{"error": "<code>", "message": "..."}`. There is deliberately no SQL tool.

Start the server for one project with `python -m autopsy.mcp_server --manifest <path>` (or set `AUTOPSY_MANIFEST`).

### Registering it in Bob (unverified, see below)

```json
{
  "mcpServers": {
    "autopsy": {
      "command": "python",
      "args": ["-m", "autopsy.mcp_server", "--manifest", "C:/path/to/plugins/acme_shop/manifest.yaml"],
      "env": {"ACME_DB_PATH": "C:/path/to/plugins/acme_shop/acme.duckdb"}
    }
  }
}
```

One registration per project differs only in the manifest path (and the database environment variable the
manifest names). `investigate.sh` also exports `AUTOPSY_MANIFEST`, in case Bob passes environment through.

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `AUTOPSY_MANIFEST` | MCP server, `investigate.sh` | manifest path when `--manifest` is not given |
| `AUTOPSY_STATE_DIR` | baselines, service | where `<project>.json`, `service.db`, `secrets.json` and `manifests/` live (default `state/`) |
| `AUTOPSY_TEST_POSTGRES_DSN` | tests | a scratch PostgreSQL database; enables the live PostgreSQL contract tests |
| `AUTOPSY_NOW` | everything time-based | pin the clock (ISO) for repeatable demos and tests; **unset it in real use** |
| `AUTOPSY_PYTHON`, `BOB` | scripts | interpreter and Bob Shell command |
| `ACME_DB_PATH` | Acme Shop manifest, shop, scripts | the shop's DuckDB file (the manifest names the variable, not the path); must be set in the process that runs the platform |
| `ACME_AS_OF` | Acme seed | the time the seeded data runs up to (default: now, UTC) |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No module named 'starlette'` (or similar) | the command ran with a Python that does not have the package; activate the venv and `pip install -e "autopsy-platform[dev]"` |
| Importing the Acme manifest says `ACME_DB_PATH is not set` | set it in the terminal that starts `autopsy serve`; the manifest names the variable, not the path |
| `port 8765 is already in use` | another `autopsy serve` is running; stop it or pass `--port` (the launcher takes `--autopsy-port`) |
| A run says `Could not run checks: ... being used by another process` | a writer held the database longer than the 10 second wait; run again |
| PowerShell: `export` is not recognised | use `$env:ACME_DB_PATH = "..."`; `export` is for bash |
| Freshness fails on a database you seeded earlier | the seed data runs up to the moment it was made; reseed right before checking |

## Where this differs from the design doc

- **The whole upstream lineage is checked, not only datasets that look wrong.** The doc says to walk upstream
  from a failing dataset until a dataset is clean. In the Acme scenarios S1, S2 and S3 the business-visible mart
  passes every check (a doubled day, a swapped channel and 40% fewer joined rows leave row counts and value ranges
  intact), so that rule would stop before the cause. The investigator rules (`.bob/rules-incident-investigator/`)
  and the reference investigator therefore check every upstream dataset.
- **`having` in the query spec.** The doc's spec has no way to ask for "keys that repeat" without pulling every
  key. `having` (filters on output names) is the one addition, and each connector turns it into a `HAVING` clause.
- **The profile check compares the last 3 complete days** as well as the whole dataset, because a unit shift or
  null spike on the newest days barely moves an all-time median. Today's partial day is excluded.
- **A reference investigator (`autopsy investigate`)** runs the doc's investigation steps with no LLM, through
  the same tool functions Bob calls. It is the offline oracle for the tools, the severity rubric and `autopsy grade`.
  It is not a substitute for Bob's run.
- Extras beyond the doc's must-haves: the SQLite, `files` and PostgreSQL connectors, the web UI and API with run
  history, incidents and a schedule, the `sensor_readings` plug-in, the live Acme Shop demo, and the three swap demos
  (`tests/test_swaps.py`) are all built; `AUTOPSY_NOW` exists for repeatable runs.

## What is verified and what is not

Verified by the test suite on this machine (Python 3.14, DuckDB 2.0, mcp 2.3):

- All connectors (fake, DuckDB, SQLite) pass the same contract tests, including "never writes".
- Every check runs against the in-memory connector with no database file.
- The MCP server starts as a subprocess and answers `list_tools`, `describe_project` and `find_duplicates` over stdio.
- All six Acme Shop scenarios give the expected root dataset, check and severity; 54 of 54 across three seeds and
  three times of day in a sweep run during development.
- The three swap demos leave `autopsy/` byte-identical; `tests/test_no_project_names.py` fails the build on any leak.
- `investigate.sh` builds the right Bob command and report path (tested with a stub `bob`).
- The service: connections (secrets never returned or written to a manifest), mapping validation, role suggestions,
  runs, the incident lifecycle (open, recur, resolve), the schedule, and the HTTP error and cross-site guards.
  All six Acme scenarios driven through the service from an imported manifest open the expected incident
  (`tests/test_service_scenarios.py`).
- The `files` connector passes the same contract as the databases, including "cannot write".
- The web UI was exercised in headless Edge with demo data: every page and tab in light, dark and phone width, and real
  click-throughs (add connection, the five-step wizard, import, run, acknowledge, edit mapping, schedule, command palette)
  with no console errors. There are no automated browser tests; see below.
- The live demo: each of the five shop incidents is found with the expected root cause and severity, and rolling it back
  returns the platform to clean (`tests/test_acme_app.py`). The one-command launcher was run end to end: the first check
  run was 18 of 18, then a guest-checkout incident triggered in the shop was found by the platform's own schedule (SEV2,
  `orders_raw` / `profile_dataset`, "customer_id: 42.3% null") and resolved after the roll back, with no button pressed
  in Autopsy. The shop UI was clicked through in headless Edge: checkout, all five incidents triggered and rolled back,
  the Finance chart changing each time, no console errors.
- The platform reads while another process writes the same DuckDB file (test with a separate writer process), and a
  busy file is retried in the Windows wording as well as the Linux one.

**Not verified:**

- **The PostgreSQL connector has never run against a live server.** Its SQL shape and read-only session options are
  pinned by stub tests (`tests/test_postgres_connector.py`), which cannot show that PostgreSQL accepts the SQL. Set
  `AUTOPSY_TEST_POSTGRES_DSN` to a scratch database to run the full contract against it before relying on it.
- **The UIs have no automated browser tests** (the Autopsy UI and the shop UI were exercised by scripted browser
  sessions during development). The PostgreSQL form and the write-only secret field were not clicked through, the shop
  has no dark theme, and no screen reader or full keyboard tab-through was tried on either.
- **The demo's one-minute detection delay** is the schedule's minimum interval; *Run checks* in Autopsy is instant.
- **Real databases and time zones:** the platform treats naive timestamps as UTC. A source in local time will skew the
  freshness and "today" logic by its offset; this was found on the demo machine and fixed for the demo, not generalised.
- The scheduler is tested with an injected clock and a short real-thread tick, not over hours of wall-clock time.
- Role suggestions are a starting point: a numeric reference column is indistinguishable from a measure without a name
  hint, so people must confirm the mapping (the UI says so).

**Not verified, needs Bob** (no Bob in the build environment; the design doc lists the same items as "things to check"):

- A real Bob run: whether Bob picks the right root cause from these tools and rules.
- The custom mode's `groups` names (`read`, `mcp`) and the `.bob/rules/` folder name.
- Where Bob reads MCP settings and whether arguments or environment variables reach a local server.
- Whether Bob offers an ignore file or context condensing (Chapter 4), and what the badge grader wants as evidence.

## Accuracy table

Reference investigator (no LLM), Acme Shop, `plugins/acme_shop/scripts/run_all.sh reference`:

| Scenario | What breaks upstream | Expected root | Result |
|---|---|---|---|
| S0 | nothing (control) | none | correct |
| S1 | a day's orders loaded twice | `orders_raw` / `find_duplicates`, SEV1 | correct |
| S2 | `channel` renamed upstream | `orders_raw` / `check_schema`, SEV2 | correct |
| S3 | 40% of new orders have a null `customer_id` | `orders_raw` / `profile_dataset`, SEV2 | correct |
| S4 | no orders for 3 days | `orders_raw` / `check_freshness`, SEV3 | correct |
| S5 | amounts in cents | `orders_raw` / `profile_dataset`, SEV1 | correct |

Bob column: run `run_all.sh bob` and record the results here.
