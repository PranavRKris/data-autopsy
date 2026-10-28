# Pipeline Autopsy: Design Doc (Structure, Data Flow, HLD, LLD)

Oct 28, 2026 · @Pranav

## Purpose and scope

Pipeline Autopsy is a platform in which IBM Bob investigates why a data pipeline's output is wrong, for any project and any database, using read-only access.

The pain point it targets: pipeline maintenance consumes 53% of engineering capacity at large enterprises ([Fivetran benchmark, via DataDriven](https://datadriven.io/blog/53-of-data-engineering-capacity-goes-to-pipeline-maintenance)), while teams prioritize AI-assisted coding (72%) far above AI-assisted pipeline management (24%) per the same source. The platform sits in the neglected half.

**In scope**

- The platform: a connector layer, a manifest format, generic checks, an MCP server, a Bob custom mode with rules, and a headless investigation run

- One connector (DuckDB) behind an interface that other databases can implement later

- A separate test plug-in, Acme Shop (last section), that proves the platform works without being built for it

**Out of scope**

- Extra connectors beyond DuckDB (a SQLite connector is a day-3 stretch to prove database swapping; Databricks or Snowflake are later work)

- A UI, scheduling, alerting, or auto-fixing data

- Anything that writes to a project's database

**Done means:** the platform contains no project-specific names, and the Acme Shop test plug-in produces the correct root cause for each seeded failure, using only its manifest.

## How the platform stays independent

The platform never knows a table name, a column name or a SQL dialect; a connector and a manifest translate for it.

![platform, connector and project layers · 4 boxes](./media/image1.png)

*platform, connector and project layers · 4 boxes*

The platform asks for things in generic terms (a dataset, a role, a query spec), and everything project-specific lives in the tinted boxes.

**Three ideas make it work**

1.  **A connector hides the database.** The platform asks for "row count per day for dataset X" as a structured query spec, not SQL. The connector turns the spec into the database's own SQL. Only connector files contain SQL, so supporting a new database means writing one new connector.

2.  **A manifest hides the project.** A YAML file names the connector, lists the datasets, and says which column plays which role (event time, key, measure). Checks are written against roles, so a new project needs a new manifest and no platform code.

3.  **A baseline replaces hand-written rules.** The platform can snapshot a healthy period and learn normal null rates, value ranges and daily volumes. A project does not have to know in advance what "wrong" looks like.

**What you touch when something new arrives.** This is the test of independence: the right-hand column should almost always say "nothing".

| You want to support                                       | You write                                                          | Platform code that changes                      |
|-----------------------------------------------------------|--------------------------------------------------------------------|-------------------------------------------------|
| A new project on a supported database                     | One `manifest.yaml`                                                | Nothing                                         |
| A project whose schema changed (renamed or moved columns) | One or two lines in that project's manifest                        | Nothing                                         |
| A new database type (SQLite, Postgres, Snowflake)         | One connector file, registered by name, passing the contract tests | Nothing in checks, tools, rules or the mode     |
| A new kind of problem to detect                           | One check function written against roles, plus one MCP tool        | That one check and tool; still no project names |

Three tests enforce this mechanically, so independence is something you can show, not just claim: `tests/fake_connector.py` runs every check with no real database, `tests/test_connector_contract.py` holds any connector to the same behaviour, and `tests/test_no_project_names.py` fails the build if a plug-in's table or column name appears anywhere under `autopsy/`.

**Roles that checks run on**

| Role         | Meaning                                    | Checks it enables                         |
|--------------|--------------------------------------------|-------------------------------------------|
| `event_time` | Column recording when each row happened    | Freshness, volume per day                 |
| `key`        | Column or columns that should be unique    | Duplicate detection                       |
| `measure`    | Numeric column that carries business value | Range, unit-shift and distribution checks |
| `required`   | Column that must not be null               | Null-rate spikes                          |
| any column   | Compared to the learned baseline           | Schema drift                              |

**Honest limits.** The platform catches symptoms visible in the raw data: stale feeds, duplicates, schema drift, null spikes, unit shifts and volume drops. It cannot know business rules such as "every order needs a matching customer" unless the manifest declares them; declared cross-dataset checks are a stretch goal.

## Badge coverage map

Every chapter of the Level 3 course maps to a concrete piece of this project, so each requirement has visible evidence.

| Ch. | Topic                                              | What you build or do                                                                                                                                                             | Evidence to capture                                                           |
|-----|----------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| 1   | Setup and environment                              | Install Bob, create the platform repo and the separate Acme Shop plug-in folder                                                                                                  | Screenshot of Bob open on the repo                                            |
| 2   | Tab completion, next edit prediction, agentic chat | Scaffold the platform with agentic chat (models, connector interface); write check functions with tab completion; rename a manifest field across files with next edit prediction | Screenshots of a completion, an edit prediction, and one agentic chat session |
| 3   | Project context, custom rules, custom modes        | Rules such as "no project-specific names in the platform"; the Incident Investigator mode                                                                                        | The rules files, the mode YAML, and a chat where the mode obeys a rule        |
| 4   | Context window management and Bob Shell            | Headless investigation of the Acme Shop plug-in; a large log kept out of context                                                                                                 | Shell transcript, report file, a note on how context was kept small           |
| 5   | MCP                                                | Platform MCP server with 6 generic tools that read a project manifest                                                                                                            | MCP settings screenshot, a tool call visible in an investigation              |

**Assumption to verify:** exact evidence the badge grader wants is not known to me. Check the instructions in the linked course documentation before day 1.

## Repository file structure

Two folders sit side by side: the platform, which knows nothing about any project, and the plug-ins, of which Acme Shop is the first test case. The platform never imports from `plugins/`, and a plug-in never imports from the platform's internals.

```text
autopsy-platform/                  # the platform: no project-specific names anywhere
├── README.md
├── pyproject.toml                 # package is named autopsy (not platform, which clashes with Python's stdlib)
├── .bob/
│   ├── custom_modes.yaml          # incident-investigator mode (read + mcp only)
│   ├── rules/
│   │   ├── 01-safety.md           # read-only access, never modify a project
│   │   ├── 02-platform-conventions.md   # no project names in autopsy/, SQL only in connectors
│   │   └── 03-report-format.md    # required report sections
│   └── rules-incident-investigator/
│       ├── 01-investigation-steps.md
│       └── 02-severity-rubric.md
├── autopsy/
│   ├── core/
│   │   ├── models.py              # Dataset, Column, AggSpec, Finding, Severity
│   │   ├── manifest.py            # load and validate a project manifest
│   │   ├── baseline.py            # snapshot and load learned baselines
│   │   └── registry.py            # connector name to connector class
│   ├── connectors/
│   │   ├── base.py                # the Connector interface
│   │   └── duckdb_connector.py    # the only file that contains DuckDB SQL
│   ├── checks/
│   │   ├── freshness.py
│   │   ├── schema.py
│   │   ├── profile.py
│   │   ├── duplicates.py
│   │   └── volume.py
│   ├── mcp_server/
│   │   └── server.py              # 6 generic tools, started with --manifest <path>
│   └── cli.py                     # autopsy validate | baseline | grade
├── tests/
│   ├── fake_connector.py          # in-memory connector: proves checks need no real database
│   ├── test_checks.py
│   ├── test_connector_contract.py # any connector must pass these
│   └── test_no_project_names.py   # fails if autopsy/ mentions a plug-in's tables or columns
├── investigator/
│   └── investigate.sh             # usage: investigate.sh <manifest> <report-name>
├── state/                         # generated: learned baselines, one file per project
└── reports/                       # generated incident reports

plugins/
└── acme_shop/                     # the test case (last section of this doc)
    ├── README.md
    ├── manifest.yaml              # connector, datasets, roles, expectations
    ├── seed/seed_data.py          # clean data plus five failure scenarios
    ├── pipeline/                  # the sample pipeline under investigation
    │   ├── run_pipeline.py
    │   └── sql/                   # staging and mart SQL
    ├── logs/pipeline_run.log      # long, noisy log for the context demo
    ├── expected/expected_results.yaml   # the known root cause per scenario
    └── scripts/reset.sh           # delete the db, reseed one scenario, rerun the pipeline
└── sensor_readings/               # optional second plug-in for the swap demo (one dataset)
```

The `.bob/` layout follows the Bob Shell docs: project modes live in `.bob/custom_modes.yaml` and mode-specific instructions in `.bob/rules-{mode-slug}/` ([Bob Shell custom modes](https://bob.ibm.com/ja/docs/shell/configuration/custom-modes-bobshell)). The general `.bob/rules/` folder name is an assumption; confirm it in Chapter 3.

## Data flow

The platform reads two project-specific inputs, a manifest and a baseline, and every other step of a run is generic.

![end-to-end data flow · 3 lanes, 8 parts](./media/image2.png)

*end-to-end data flow · 3 lanes, 8 parts*

Setup happens once per project; after that every investigation repeats the lower lane, and nothing in it is allowed to write.

1.  A person writes the project's `manifest.yaml`: connector, datasets, column roles and expectations.

2.  `autopsy validate` checks the manifest against the live database through the connector, and `autopsy baseline` learns normal ranges from a healthy period and saves them under `state/`.

3.  `investigate.sh <manifest>` starts Bob Shell in the Incident Investigator mode, with the `.bob/` rules loaded as context.

4.  Bob calls the MCP tools. Each tool loads the manifest, builds a query spec and hands it to the connector, which runs read-only SQL and returns a small result.

5.  Each tool returns a structured finding (status, summary, evidence), Bob combines them into a report, and the script redirects the final answer into `reports/`.

6.  The plug-in's expected results file is compared with the report to decide pass or fail.

## High-level design (HLD)

The system has three layers and one dependency rule: project-specific things may depend on the platform, never the reverse.

| Component             | Responsibility                                                                 | Technology                                  | Boundary                                         |
|-----------------------|--------------------------------------------------------------------------------|---------------------------------------------|--------------------------------------------------|
| Platform core         | Models, manifest loading, baselines, connector registry                        | Python                                      | Imports nothing from any plug-in                 |
| Connector layer       | Turns query specs into SQL for one database type and enforces read-only access | Python, one file per database; DuckDB first | The only code allowed to contain SQL             |
| Checks                | Freshness, schema, profile, duplicates, volume                                 | Python                                      | Work on datasets and roles, never on table names |
| MCP server            | Exposes the checks as 6 tools; loads one manifest at start                     | Python MCP SDK over stdio                   | Read-only; no free-form SQL tool                 |
| Bob configuration     | Generic rules and the Incident Investigator mode                               | `.bob/` YAML and markdown                   | Read and MCP access only                         |
| Plug-in (per project) | Manifest, the project's database and pipeline                                  | YAML plus whatever the project already uses | Talks to the platform only through the manifest  |

**Key design decisions**

- **Dependency rule.** `autopsy/` imports nothing from `plugins/`, and a test fails if the platform mentions a plug-in's table or column names.

- **Query specs instead of SQL.** The platform describes what it wants (aggregates, grouping, filters) as data, and each connector turns that into SQL. This is what makes databases interchangeable.

- **Roles instead of names.** Checks run on roles declared in the manifest (event time, key, measure), so the same check works on any schema.

- **Safety in two layers.** Connectors open the database read-only, and the custom mode omits edit and command access.

- **Platform state stays out of the project.** Learned baselines live under `state/`, so the platform never writes to a project's database.

- **Small structured outputs.** Every tool returns a compact finding (at most 50 rows or about 2 KB), which is the main context-window strategy for Chapter 4.

- **The report is a redirect, not a file write.** Because the mode cannot edit files, the script captures Bob's final output into `reports/`.

**Non-functional targets:** an investigation under 2 minutes, a new project onboarded with a manifest in under 30 minutes, and zero writes to a project's database (a connector contract test asserts this).

## LLD: connector interface and query spec

A connector implements four methods and speaks one small query language, so the platform never writes SQL.

```python
class Connector(Protocol):
    def list_datasets(self) -> list[str]: ...
    def describe(self, dataset: str) -> list[ColumnInfo]: ...     # name, type, nullable
    def aggregate(self, dataset: str, spec: AggSpec) -> list[dict]: ...
    def sample(self, dataset: str, n: int = 5) -> list[dict]: ...  # n capped at 20
```

**The query spec**

| Part                | Allowed values                                                                | Notes                                              |
|---------------------|-------------------------------------------------------------------------------|----------------------------------------------------|
| `select`            | `count`, `count_distinct`, `count_null`, `min`, `max`, `avg`, `median`, `sum` | Each over a column or `*`, with an alias           |
| `group_by`          | A column, or a time bucket of a column (`day`, `hour`)                        | Buckets are how volume per day is computed         |
| `where`             | `=`, `!=`, `>`, `>=`, `<`, `<=`, `is_null`, `is_not_null`                     | Values are bound parameters, never pasted into SQL |
| `order_by`, `limit` | An alias or group column; limit up to 1,000                                   | The MCP tool caps what Bob sees much lower         |

**Example:** the same spec, and what the DuckDB connector turns it into.

```python
AggSpec(
    select=[Agg("count", "*", "n"), Agg("max", "event_ts", "latest")],
    group_by=[Bucket("event_ts", "day")],
    where=[Filter("event_ts", ">=", "2026-10-01")],
    order_by=["day"], limit=50)
```

```sql
select date_trunc('day', event_ts) as day, count(*) as n, max(event_ts) as latest
from <dataset> where event_ts >= ? group by 1 order by 1 limit 50
```

**Rules every connector follows**

- Dataset and column names are checked against `list_datasets` and `describe` before use; anything unknown raises a typed error.

- Values are always bound parameters, and the connector quotes identifiers itself.

- The connection is read-only: `read_only=True` for DuckDB, a read-only role or transaction for other databases.

- Results are plain Python dictionaries with no driver-specific types.

- Every connector passes the same contract tests (`tests/test_connector_contract.py`) against a tiny known dataset. Passing them is the definition of "supported".

**Adding a new database** means copying `duckdb_connector.py`, implementing the four methods, registering the name and passing the contract tests. No check, tool or rule changes.

**Why not give Bob a free SQL tool?** It is simpler to build, but it ties every investigation to one SQL dialect, makes safety depend on Bob's behavior, and floods the context window with raw rows.

## LLD: project manifest

The manifest is the only file a new project has to write, and it describes data in roles rather than in code.

| Field                         | Required | Meaning                                                                                                          |
|-------------------------------|----------|------------------------------------------------------------------------------------------------------------------|
| `project`                     | yes      | Short name, used for the baseline file and report titles                                                         |
| `connector`                   | yes      | Registered connector name, for example `duckdb`                                                                  |
| `connection`                  | yes      | Connector settings; secrets are environment variable names, never values                                         |
| `datasets[].name`             | yes      | Logical name used by every tool                                                                                  |
| `datasets[].source`           | yes      | The real table, view or file as the database knows it                                                            |
| `datasets[].roles`            | yes      | Columns playing `event_time`, `key`, `measure` and `required`                                                    |
| `datasets[].business_visible` | no       | Marks datasets whose numbers reach people; raises severity                                                       |
| `datasets[].feeds`            | no       | Logical names of the datasets this one is built into (lineage); lets the investigator walk from symptom to cause |
| `datasets[].expected`         | no       | Overrides such as `max_age_hours`, `max_null_rate`, `value_range`                                                |
| `thresholds`                  | no       | Project-wide defaults for the same limits                                                                        |

**Generic example** (placeholder names, not a real project):

```yaml
project: example
connector: duckdb
connection:
  path_env: EXAMPLE_DB_PATH        # name of an environment variable
datasets:
  - name: events
    source: raw.events
    feeds: [daily_totals]          # optional lineage
    roles:
      event_time: created_at
      key: [event_id]
      measure: [amount]
      required: [event_id, created_at]
    expected:
      max_age_hours: 36
      value_range: {amount: [1, 5000]}
  - name: daily_totals
    source: mart.daily_totals
    business_visible: true
    roles:
      event_time: day
      key: [day]
      measure: [total]
thresholds:
  max_null_rate: 0.02
  volume_change_ratio: 0.5
```

**Validation** (`autopsy validate`): every role column must exist according to `describe`; `event_time` must be a temporal type and `measure` a numeric type; a dataset without a `key` skips the duplicate check and says so; every name in `feeds` must be another dataset in the manifest; a secret value in the file is rejected.

**How each check uses the manifest and baseline**

| Check      | Role used             | Compared against                                    | Fails when                                                                           |
|------------|-----------------------|-----------------------------------------------------|--------------------------------------------------------------------------------------|
| Freshness  | `event_time`          | `max_age_hours`                                     | Newest row is too old, or recent days have no rows                                   |
| Schema     | all columns           | Baseline column list                                | A column is missing, new or retyped                                                  |
| Profile    | `measure`, `required` | `value_range`, `max_null_rate`, baseline statistics | Null rate too high, values outside the range, or the median shifts by a large factor |
| Duplicates | `key`                 | Uniqueness                                          | Any key appears more than once                                                       |
| Volume     | `event_time`          | Trailing median rows per day                        | A day deviates by more than `volume_change_ratio`                                    |

When a manifest gives no explicit limit, the baseline supplies one. With neither, the check reports `skipped` instead of guessing.

## LLD: MCP server

The server exposes six generic tools; each takes a dataset name from the manifest and returns one structured finding.

| Tool               | Inputs                        | Returns                                                                                                                          |
|--------------------|-------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| `describe_project` | none                          | Project name, datasets with their roles and `business_visible` flags, lineage from feeds, and which checks are possible for each |
| `check_freshness`  | `dataset`                     | Newest `event_time`, age in hours, the limit, and days with zero rows in the last 14                                             |
| `check_schema`     | `dataset`                     | Missing, new and retyped columns compared with the baseline                                                                      |
| `profile_dataset`  | `dataset`, optional `columns` | Null rate, min, max, median and distinct count for measure and required columns, with limits and baseline comparison             |
| `find_duplicates`  | `dataset`                     | Number of repeated keys, extra rows, per-day counts, up to 5 sample keys                                                         |
| `check_volume`     | `dataset`                     | Rows per day for the last 14 days against the trailing median, and the days outside the allowed band                             |

**The finding format** (every check tool returns this shape; `status` is `ok`, `warn`, `fail` or `skipped`):

```json
{
  "check": "check_freshness",
  "dataset": "events",
  "status": "fail",
  "summary": "Newest row is 71 hours old; the limit is 36.",
  "evidence": {"latest": "2026-10-25T08:00:00", "age_hours": 71, "max_age_hours": 36},
  "next_checks": ["check_volume"]
}
```

**Rules every tool follows**

- `dataset` must be a logical name from the manifest; anything else returns `unknown_dataset`.

- Tools never build SQL. They build query specs and call the connector.

- Output is capped at 50 rows or about 2 KB, with a `truncated` flag.

- Errors come back as `{"error": "<code>", "message": "..."}` so Bob can read them and continue.

- A tool whose required role is missing returns `skipped` with the reason, never a guess.

- Tools are pure functions of the manifest, baseline and database state, so they can be tested against the fake connector.

**Startup and registration.** `python -m autopsy.mcp_server --manifest <path>` (or with the AUTOPSY_MANIFEST environment variable set) starts a local stdio server for one project. The server code is identical for every project; only the manifest path differs. Register it in Bob through the MCP settings panel (the docs describe local and remote transports and adding servers from settings, per [Bob docs](https://bob.ibm.com/docs/ide)). Each project gets one registration that differs only in the manifest path. Confirm the exact config location and whether arguments can be passed in Chapter 5.

**Build approach:** write each tool's test against the fake connector first, then ask Bob in agentic chat to generate the tool from this section, and review it against the rules above.

## LLD: Bob configuration

Three configuration pieces carry Chapters 3 and 4: generic rules, one custom mode, and one headless Shell command that is told which project to investigate.

**Custom mode** (`.bob/custom_modes.yaml`), following the YAML format shown in the Bob Shell docs:

```yaml
customModes:
  - slug: incident-investigator
    name: "Incident Investigator"
    roleDefinition: >-
      You investigate why a project's data output is wrong, for any project
      and any database. You only observe. You never modify data, code or configuration.
    whenToUse: Use when a metric or table looks wrong and the cause is unknown.
    customInstructions: |-
      Start with describe_project; never assume table or column names.
      Follow the steps in the mode rules folder, in order.
      End with a report in the required format.
    groups:
      - read
      - mcp
```

The `groups` list is the permission boundary: no edit and no command groups. Verify the exact group names in your Bob version.

**Rules**

| File                                                    | Contents (keep each under 15 lines)                                                                                                                 |
|---------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `rules/01-safety.md`                                    | Never write to any project database, file or configuration. Never recommend `DROP`, `DELETE` or `TRUNCATE` as a first step.                         |
| `rules/02-platform-conventions.md`                      | When building the platform: no project-specific names in `autopsy/`, SQL only inside connector files, every check works on a dataset name and roles |
| `rules/03-report-format.md`                             | Sections: Summary, Evidence, Root cause, Impact, Recommended fix, Confidence                                                                        |
| `rules-incident-investigator/01-investigation-steps.md` | Fixed order: `describe_project`, then the checks on the symptom dataset, then walk upstream through feeds (next section)                            |
| `rules-incident-investigator/02-severity-rubric.md`     | SEV1 to SEV4 definitions (next section)                                                                                                             |

Rule 02 doubles as Chapter 3 evidence: ask Bob to hard-code a table name into a check and show it refusing or correcting itself.

**Headless run** (`investigator/investigate.sh`), based on the headless example in the docs:

```bash
#!/usr/bin/env bash
# usage: investigate.sh <manifest> <report-name> [dataset]
set -euo pipefail
export AUTOPSY_MANIFEST="$(realpath "$1")"      # the MCP server reads this
PROJECT="$(python -m autopsy.cli project-name "$1")"
START="${3:-its business-visible datasets}"
bob --chat-mode=incident-investigator \
    -p "Investigate why the output of project $PROJECT looks wrong, starting from $START. Use only the autopsy tools." \
    --hide-intermediary-output > "reports/incident_${PROJECT}_$2.md"
```

**Context window management (Chapter 4)**

- Tools return capped structured findings, so an investigation stays small however large the project's database is.

- Rule: never open a project's logs or data files in full. For the Acme Shop demo, run one separate session that summarizes its log, and give the investigator only that summary.

- One scenario per fresh session; do not chain several failures in one chat.

- Demo for the badge: show the same question with and without the log rule, and note the difference.

**Verify in the course:** whether Bob offers an ignore file, context condensing or a context meter, and how to pass the manifest path to an MCP server at run time. If Bob does not pass the environment variable through to the MCP server, the fallback is one MCP registration per project, named after the project, each with its own --manifest argument. Either way the platform code is the same.

## LLD: investigation logic and report

The investigator follows a fixed order that is driven only by what `describe_project` returns, so it never names a table or column and runs the same way on every plug-in.

1.  `describe_project`: learn the datasets, their roles, `business_visible` flags, lineage and which checks are possible. This is the only source of names for the rest of the run.

2.  Pick the starting point: the dataset named in the prompt, or else every `business_visible` dataset. This is where the symptom shows.

3.  On that dataset, run the checks cheapest first: `check_freshness`, `check_volume`, `check_schema`, `profile_dataset`, `find_duplicates`. Skip any check `describe_project` marks as not possible.

4.  Walk upstream: for every dataset with a failing check, repeat step 3 on the datasets that feed it, until a dataset is clean or has no upstream.

5.  The root cause is the most upstream failing finding; everything downstream of it is impact. Finish the remaining checks on that dataset to rule out a second cause.

**Why lineage matters.** Without `feeds`, Bob can say where a problem shows up but not where it started. The field is optional: with no lineage, Bob reports each failing dataset separately and sets confidence to medium at most.

**Severity rubric** (decided from the check type, `business_visible` and lineage, never from a table name)

| Level | Meaning                                                                                    | Generic example                                                        |
|-------|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| SEV1  | Wrong values in a business-visible dataset, or upstream of one, with a large error         | A measure's median shifts 100x; a repeated load doubles a day's totals |
| SEV2  | Wrong values with a partial effect, or wrong values only in datasets no business user sees | Null keys silently drop 40% of rows from a downstream join             |
| SEV3  | Data is late or missing, but the values present are correct                                | Newest row is three days old                                           |
| SEV4  | Quality or schema warning with no measurable effect yet                                    | An unexpected new column                                               |

Assign the highest level that applies and justify it in the Impact section. A plug-in states the severity it expects per scenario in its own expected results file; the platform never hard-codes one.

**Report template** (`.bob/rules/03-report-format.md` encodes this)

```markdown
# Incident report: <project> / <dataset> on <date>

## Summary
One sentence: what is wrong and how bad.

## Evidence
Each tool called, with the key numbers it returned.

## Root cause
Dataset and check where the problem starts, stated as a fact or a hypothesis.

## Impact
Which downstream datasets and measures are wrong, by how much, severity level and why.

## Recommended fix
Numbered steps for a human. Never run them.

## Confidence
High, medium or low, plus anything that could not be checked.
```

**Grading each run** (`autopsy grade <report> <expected_results.yaml> <scenario>`): a generic script reads the Root cause section and passes the run if it names the expected dataset and check, then compares severity. It knows nothing about any plug-in except what the expected results file says.

## Plug-in contract: what any project must provide

A plug-in is anything that hands the platform a manifest and a database it can read. This is the whole contract; if onboarding a project needs more than this, that is a platform bug.

| Item                                              | Required                       | Purpose                                                                                   |
|---------------------------------------------------|--------------------------------|-------------------------------------------------------------------------------------------|
| `manifest.yaml`                                   | Yes                            | The only file the platform reads: connector, connection, datasets, roles, lineage, limits |
| A database the named connector can open read-only | Yes                            | Where the data lives; the platform never writes to it                                     |
| Secrets as environment variables                  | Yes, if the database needs any | The manifest stores variable names, never values                                          |
| `expected/expected_results.yaml`                  | Test plug-ins only             | The known root cause per scenario, used by `autopsy grade`                                |
| `scripts/reset.sh`                                | Test plug-ins only             | Rebuilds a scenario so every demo run is repeatable                                       |

**Onboarding any project takes four commands and no platform code:**

1.  Write the manifest (copy the generic example and map roles to the project's columns).

2.  `autopsy validate <manifest>` confirms every role column exists and has the right type.

3.  `autopsy baseline <manifest>` learns normal values from a healthy period into `state/<project>.json`.

4.  `investigator/investigate.sh <manifest> <report-name>` runs an investigation.

## Build order, risks and things to verify

Build the platform first against the fake connector, and the Acme Shop plug-in last, because the plug-in exists only to test the platform. The plan fits in 3 days, with a cut line if time runs short.

| Slot     | Goal                                                                                                           | Chapter   | Done when                                                  |
|----------|----------------------------------------------------------------------------------------------------------------|-----------|------------------------------------------------------------|
| Day 1 AM | Install Bob; repo skeleton; `models.py`; Connector interface; fake connector; DuckDB connector; contract tests | 1, 2      | Contract tests pass for both connectors                    |
| Day 1 PM | Manifest loader and `autopsy validate`; the five checks; schema baseline                                       | 2         | `test_checks.py` passes with no database file present      |
| Day 2 AM | MCP server with the 6 tools; test with MCP Inspector; register in Bob                                          | 5         | A tool call shows up in a Bob chat                         |
| Day 2 PM | `.bob/` rules and the Incident Investigator mode; `investigate.sh`; `autopsy grade`                            | 3, 4      | Mode refuses an edit; a headless run writes a report       |
| Day 3 AM | Acme Shop plug-in, built in its own folder: seed, pipeline, manifest, expected results, reset                  | Test case | `autopsy validate` passes; each scenario shows its symptom |
| Day 3 PM | Run all scenarios; accuracy table; swap demo; README and screenshots                                           | All       | The demo script runs end to end from a clean checkout      |

**Cut line.** Must have for the demo: DuckDB and fake connectors, the five checks, the 6 tools, the mode and rules, `investigate.sh`, and Acme Shop scenarios S0, S1, S3 and S5. Cut in this order if a slot slips: scenarios S2 and S4; learned baseline statistics (keep the schema snapshot and use manifest limits instead); `autopsy grade` (grade by reading the report); the second plug-in; the SQLite connector.

**Risks and fallbacks**

- **MCP registration fails.** Test the tools with the MCP Inspector first, then retry registration.

- **The manifest path cannot reach the MCP server at run time.** Register one server per project with its own `--manifest` argument; no code changes.

- **Bob picks the wrong root cause.** That is useful evidence; keep the failing report and note which rule or tool change fixed it.

- **A project name leaks into the platform.** `test_no_project_names.py` catches it; move the name into the manifest.

**Things I could not confirm and you should check against the course material**

- Exact evidence or screenshots the badge grader expects for each chapter

- Name and location of the general rules folder, and the exact custom mode group names

- Whether Bob has an ignore file or context condensing feature for Chapter 4

- MCP config file location and format, and whether environment variables or arguments reach a local MCP server

## Test case: the Acme Shop plug-in

Acme Shop is a small fake online store, built separately from the platform as if by another team. It owns its database, its pipeline and its manifest, and imports nothing from `autopsy/`. Its only job is to prove the platform finds root causes it was never written for.

**The pipeline under test.** A seed script writes raw orders and customers into `acme.duckdb`; `run_pipeline.py` builds a cleaned staging table (orders joined to customers) and a revenue mart summed by day and sales channel.

| Logical dataset | Source table       | Roles                                                                                         | Feeds           | Business visible |
|-----------------|--------------------|-----------------------------------------------------------------------------------------------|-----------------|------------------|
| orders_raw      | raw.orders         | event_time `ordered_at`; key `order_id`; measure `amount`; required `order_id`, `customer_id` | `orders_clean`  | No               |
| customers_raw   | raw.customers      | key `customer_id`; required `customer_id`                                                     | `orders_clean`  | No               |
| orders_clean    | staging.stg_orders | event_time `ordered_at`; key `order_id`; measure `amount`; required `customer_id`, `channel`  | `daily_revenue` | No               |
| daily_revenue   | mart.daily_revenue | event_time `day`; key `day`, `channel`; measure `revenue`                                     | none            | Yes              |

Logical names deliberately differ from table names, so the demo shows that Bob only ever uses the names the manifest gives it.

**Its manifest** (`plugins/acme_shop/manifest.yaml`, abridged)

```yaml
project: acme_shop
connector: duckdb
connection:
  path_env: ACME_DB_PATH
datasets:
  - name: orders_raw
    source: raw.orders
    feeds: [orders_clean]
    roles:
      event_time: ordered_at
      key: [order_id]
      measure: [amount]
      required: [order_id, customer_id]
    expected:
      max_age_hours: 30
      value_range: {amount: [1, 2000]}
  - name: customers_raw
    source: raw.customers
    feeds: [orders_clean]
    roles: {key: [customer_id], required: [customer_id]}
  - name: orders_clean
    source: staging.stg_orders
    feeds: [daily_revenue]
    roles: {event_time: ordered_at, key: [order_id], measure: [amount], required: [customer_id, channel]}
  - name: daily_revenue
    source: mart.daily_revenue
    business_visible: true
    roles: {event_time: day, key: [day, channel], measure: [revenue]}
thresholds:
  max_null_rate: 0.02
  volume_change_ratio: 0.5
```

**Seeded scenarios.** Each one breaks something upstream; the symptom always appears in `daily_revenue`, so Bob has to walk the lineage to find the cause.

| ID  | What breaks upstream                                                                | Symptom in daily_revenue               | Check that should find it                  | Root dataset | Sev  |
|-----|-------------------------------------------------------------------------------------|----------------------------------------|--------------------------------------------|--------------|------|
| S0  | Nothing (healthy control)                                                           | None                                   | All checks ok                              | none         | none |
| S1  | One day's batch of orders is loaded twice                                           | That day's revenue doubles             | find_duplicates, with a check_volume spike | `orders_raw` | SEV1 |
| S2  | Upstream renames `channel` to `sales_channel`; staging fills the gap with "unknown" | All revenue moves to channel "unknown" | check_schema                               | `orders_raw` | SEV2 |
| S3  | 40% of new orders arrive with a null `customer_id`; the join drops them             | Revenue about 40% low                  | profile_dataset (null rate)                | `orders_raw` | SEV2 |
| S4  | No orders loaded for the last 3 days                                                | Last 3 days missing                    | check_freshness, check_volume              | `orders_raw` | SEV3 |
| S5  | Amounts start arriving in cents instead of dollars                                  | Revenue 100x too high                  | profile_dataset (range, median shift)      | `orders_raw` | SEV1 |

**Expected results file** (what `autopsy grade` compares against)

```yaml
scenarios:
  S0: {root_dataset: none, root_check: none, severity: none}
  S1: {root_dataset: orders_raw, root_check: find_duplicates, severity: SEV1}
  S3: {root_dataset: orders_raw, root_check: profile_dataset, severity: SEV2}
  S5: {root_dataset: orders_raw, root_check: profile_dataset, severity: SEV1}
  # S2, S4 follow the same shape
```

**Running it end to end.** The baseline is learned once from the healthy S0 data, before any failure is injected; `reset.sh` never relearns it.

```bash
export ACME_DB_PATH=plugins/acme_shop/acme.duckdb
plugins/acme_shop/scripts/reset.sh S0
autopsy validate plugins/acme_shop/manifest.yaml
autopsy baseline plugins/acme_shop/manifest.yaml        # writes state/acme_shop.json

plugins/acme_shop/scripts/reset.sh S5                   # inject one failure
investigator/investigate.sh plugins/acme_shop/manifest.yaml s5
autopsy grade reports/incident_acme_shop_s5.md plugins/acme_shop/expected/expected_results.yaml S5
```

**Proving independence on stage (the swap demo).** These three moves are the strongest two minutes of the demo, because each one changes the outside world and leaves `git diff autopsy/` empty.

- **Swap the schema.** Rename `ordered_at` to `created_ts` in Acme's seed, change the two matching lines in the manifest, rerun S5: same root cause, zero platform changes.

- **Swap the project.** `plugins/sensor_readings/` is a second plug-in with one dataset of temperature readings, a ten-line manifest and one stale-feed scenario. The same tools and mode investigate it. Stretch, about an hour.

- **Swap the database.** A SQLite connector (Python's built-in `sqlite3`, roughly 80 lines) passes the same contract tests; export Acme to SQLite and change `connector: sqlite`. Stretch, only if Day 3 has time.

**Pass criteria for the test case:** S0 reports no incident, each failing scenario names the expected root dataset and check, `test_no_project_names.py` passes, and the per-scenario results are recorded in the README as an accuracy table. Five of six correct is an honest, demoable result.
