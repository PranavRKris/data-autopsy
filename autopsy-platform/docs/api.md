# Pipeline Autopsy service API

`autopsy serve` runs one process that serves this JSON API under `/api` and the web UI at `/`.
The API has **no authentication**. Bind it to localhost (the default) or put it behind your own access control.

Every response is JSON. Errors are `{"error": "<code>", "message": "...", ...}` with a status code:
400 bad request, 404 not found, 409 conflict (name taken, run already in progress, connection in use),
422 invalid input (the `message` says why; a `field` or `issues` list may be included), 500 unexpected.
Times are UTC ISO strings ending in `Z`.

## Connectors and connections

| Method and path | Purpose |
|---|---|
| `GET /api/connectors` | `{connectors:[{name,label,description,verified,available,install_hint?,fields:[…]}]}`. A field is `{key,label,type: text|path|number|secret|select,required,default?,options?,placeholder?,help?,env_ok?}`. `verified` is an honest note on how far the connector has been tested. |
| `POST /api/connections/test` | Body `{connector, config, secrets}`; nothing is saved. Returns `{ok, message, code?, datasets:[{name,columns}]}`. A failed connection is `ok:false`, not an HTTP error. |
| `POST /api/connections` | Body `{name, connector, config, secrets}`. 201 with the connection. |
| `GET /api/connections`, `GET /api/connections/{id}` | `{id,name,connector,config,secrets_set:[keys],used_by:[projects],last_test,created_at}`. |
| `PUT /api/connections/{id}` | Same body; a blank secret keeps the stored value. |
| `DELETE /api/connections/{id}` | 409 while a project uses it. |
| `POST /api/connections/{id}/test` | Re-test a saved connection; records `last_test`. |
| `GET /api/connections/{id}/schema` | `{datasets:[{name,columns:[{name,type,kind,nullable}]}],total,truncated}`. `kind` is numeric, temporal, text, boolean or other. |
| `POST /api/connections/{id}/suggest` | Body `{sources:[…]}`. Returns `{suggestions:{source:{rows,event_time,key,measure,required,notes}}}`; one aggregate pass per table. |
| `POST /api/connections/{id}/sample` | Body `{source, n}` (n up to 20). Returns `{source,columns,rows}`. |

**Secrets.** A `secret` field goes in `secrets`, never in `config`. The service stores the value in
`<state>/secrets.json`, exports it to its own environment, and puts only the variable name in the connection config
(`password_env`) and in the manifest. No endpoint returns a secret. Fields with `env_ok` may instead be given as
`<key>_env` naming an environment variable of the service process.

## Projects

| Method and path | Purpose |
|---|---|
| `POST /api/projects` | Body `{name, connection_id, datasets, thresholds?}`. Parsed as a manifest, then checked against the live database (`mapping_mismatch` with `issues:[{level,dataset,message}]`). 201. |
| `PUT /api/projects/{name}` | Same body without `name`; edits the mapping and keeps history and baseline. |
| `POST /api/projects/import` | Body `{yaml, connection_id?, connection_name?}`. Creates the connection from the manifest if none is given. Returns `{project, validation}`. |
| `GET /api/projects`, `GET /api/overview` | Project summaries; the overview adds `open_incidents` and `recent_runs`. |
| `GET /api/projects/{name}` | Full detail: `datasets`, `thresholds`, `schedule`, `baseline`, `status`, `open_incidents`, `last_run`. |
| `DELETE /api/projects/{name}` | Removes the project, its runs, incidents, baseline and manifest file. |
| `GET /api/projects/{name}/manifest` | `{yaml}`; `/manifest.yaml` is the same as a download. The file is an ordinary manifest that `autopsy` and Bob can use. |
| `GET /api/projects/{name}/mcp-config` | The MCP server entry to register in Bob for this project. Secrets are named, not shown. |
| `POST /api/projects/{name}/validate` | `{ok, message, issues}`. |
| `POST /api/projects/{name}/baseline` | Body `{since?, until?}`; learns normal values from the current data. Learn it from healthy data. |
| `PUT /api/projects/{name}/schedule` | Body `{enabled, interval_minutes, auto_investigate}`. |

A dataset in the body is `{name, source, roles:{event_time?,key?,measure?,required?}, business_visible?, feeds?, expected?}`;
`expected` may hold `max_age_hours`, `max_null_rate`, `value_range:{column:[low,high]}`. Thresholds may hold
`max_age_hours`, `max_null_rate`, `volume_change_ratio`, `median_shift_factor`.

## Runs, findings, incidents

| Method and path | Purpose |
|---|---|
| `POST /api/projects/{name}/runs` | Body `{kind: monitor|investigation, dataset?, auto_investigate?}`. Runs synchronously; 409 if a run is in progress. Returns the run with its findings. |
| `GET /api/projects/{name}/runs`, `GET /api/runs` | `{runs:[…]}` newest first; filters `kind`, `project`, `limit`. |
| `GET /api/runs/{id}` | `{id,project,kind,trigger,status,started_at,finished_at,duration_ms,summary,counts,root_dataset,root_check,severity,report,findings:[{dataset,tool,status,summary,finding}]}`. `finding` is the check's full evidence. |
| `GET /api/projects/{name}/history?limit=` | `{runs:[{id,started_at,status,trigger}],cells:[{dataset,tool,statuses:[…one per run, null if absent]}]}` for monitor runs, oldest first. |
| `GET /api/projects/{name}/lineage` | `{nodes:[{name,source,business_visible,level,status,incident_root,roles}],edges:[{from,to}]}`; `level` is the distance from the sources. |
| `GET /api/projects/{name}/datasets/{dataset}/trend?days=` | Daily `volume`, per-column `null_rate` and `median` points (null for days without rows) and the learned `baseline`; `today` is the partial day. |
| `GET /api/incidents?status=open|resolved|all&project=` | `{incidents:[{id,project,root_dataset,root_check,severity,status,acknowledged,first_seen,last_seen,resolved_at,occurrences,summary}]}`. |
| `GET /api/incidents/{id}` | The incident plus `run` (with the report) and `related_runs`. |
| `POST /api/incidents/{id}/ack` | Body `{acknowledged}`. |
| `GET /api/health` | `{ok,version,time,state_dir,scheduler:{running,last_tick}}`. |

**Statuses.** A finding is `ok`, `warn`, `fail`, `skipped` (not applicable) or `error` (the check could not run, for
example the database was unreachable). A run's status is the worst finding. Severities `SEV1`–`SEV4` come from the
same rubric as `autopsy investigate`.

**Incident lifecycle.** A monitor run checks every dataset. If any check fails and `auto_investigate` is on, an
investigation starts from the failing datasets, finds the most upstream failing dataset, and opens an incident
(or increments `occurrences` on the open incident with the same root dataset and check). A later monitor run
with no failures resolves open incidents. A run that could not reach the database (`error`) leaves incidents alone.
A manual investigation can open or update an incident but never resolves one.

## State

Everything the service remembers is under the state directory (`--state-dir`, `AUTOPSY_STATE_DIR`, default `state/`):
`service.db` (connections, projects, runs, findings, incidents), `secrets.json`, `manifests/<project>.yaml`,
and `<project>.json` baselines (the same files `autopsy baseline` writes). Nothing is ever written to a project's database.
