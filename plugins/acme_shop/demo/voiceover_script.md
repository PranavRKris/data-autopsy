# Pipeline Autopsy: 3 minute demo, voice-over script

About 430 spoken words, roughly 3:00 at a relaxed pace. The left column is what is on screen; read only the right column.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00 | Title card, or the Autopsy overview page | When a dashboard is wrong, the real problem is never the dashboard. It is somewhere upstream, in a table nobody looked at, caused by a change nobody announced. Finding it usually takes hours of digging through queries and logs. |
| 0:15 | Autopsy project page, Lineage tab | Pipeline Autopsy does that investigation for you. It connects to your data with read-only access, learns what normal looks like, and when something breaks, it traces the problem upstream and names the root cause. Nothing in it knows your table names. A short manifest describes the project. |
| 0:35 | Shop on one side, Autopsy on the other. Place one order in the shop. Autopsy Health tab, all green | Here is the demo. On one side, Acme Shop: a small online store with its own database and pipeline. On the other, Pipeline Autopsy, watching it. Right now everything is healthy: eighteen checks, all green. |
| 0:50 | Shop, Operations, Incident lab. Press Make it happen on "Pricing deploy sends cents", then open the Finance tab | Let's break it the way production breaks. A pricing deploy starts sending amounts in cents. Finance sees the damage straight away: revenue is a hundred times too high. But why? The dashboard can't tell us. |
| 1:08 | Autopsy: press Run checks, open the new incident, then the Lineage tab | In Autopsy, one click on Run checks. It finds an incident: severity one. The root cause isn't the finance report. It's the raw orders table, where the amount column holds values far outside its normal range. Raw orders feeds clean orders, which feeds daily revenue. The problem starts at the source, and the report says what to fix first. |
| 1:34 | Shop: roll back the cents incident. Then press Make it happen on "Mobile release adds guest checkout" | Now a quieter one. A mobile release adds guest checkout, and sends no customer ID. Nothing errors. The pipeline's join just silently drops those orders, and revenue falls by about forty percent. |
| 1:58 | Autopsy: Run checks, open the incident, point at the evidence | Autopsy catches it anyway: over forty percent of customer IDs are empty in the recent data. Severity two, again at the source, not in the report. The revenue table passes every check on its own, which is why Autopsy checks the whole chain upstream, not just the table that looks wrong. |
| 2:15 | Shop: Roll back. Autopsy: the incident turns Resolved | Fixing it is just as visible. Roll back the release, and the next check resolves the incident automatically. A schedule runs every minute, so nobody has to remember to look. |
| 2:28 | Autopsy: Connections, Add connection form, then the New project wizard with suggested roles | And this isn't tied to Acme. You add a connection: DuckDB, SQLite or a folder of CSV files. You confirm the suggested mapping, learn a baseline from healthy data, and you're monitoring. The same checks are exposed as six read-only tools, built for an AI assistant like IBM Bob, with no SQL access. |
| 2:50 | Back to the overview, or a closing card | Different database, different tables, same investigator. Pipeline Autopsy: from a wrong number to a root cause, in a minute. |

## Before you record

1. Start everything: `python plugins/acme_shop/demo/run_demo.py`. If your own `autopsy serve` is still on port 8765, stop it first or add `--autopsy-port 8766` (the Autopsy address in the table is then `:8766`).
2. Open two browser windows side by side: the shop's Operations tab and the Autopsy project page. Do a full dry run once, because the first trigger shows you the timing.
3. Don't wait for the schedule on camera. After each *Make it happen*, switch to Autopsy and press **Run checks**. The result is instant, and the schedule is only worth mentioning in words.
4. Roll back every incident after a take. The next take starts from green only once Autopsy has re-run and resolved it.
5. Move the mouse slowly and pause on the numbers you mention (the finance bars, the severity badge, the lineage graph).

## What the script deliberately leaves out

- **PostgreSQL.** It exists, but has never run against a live server, so the script lists only the three connectors that are tested.
- **Bob running live.** The six tools are tested over a real MCP connection, but nobody has run Bob against them. The script says the tools are "built for" an assistant like Bob. Don't show a Bob run unless you have tried it.
- **Who does the investigating.** On screen, the investigation is done by the platform's built-in investigator, the same one the tests use. Say "Autopsy finds" and not "Bob finds".
