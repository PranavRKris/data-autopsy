# Investigation steps (follow in this order)

1. Call `describe_project`. It is the only source of dataset names, roles, lineage and possible checks.
2. Starting point: the dataset named in the prompt, otherwise every `business_visible` dataset.
3. On each dataset, run the possible checks cheapest first: `check_freshness`, `check_volume`, `check_schema`,
   `profile_dataset`, `find_duplicates`. Skip any check `describe_project` does not list for that dataset.
4. Walk upstream through `fed_by` and check every upstream dataset too. Do not stop at a clean dataset:
   aggregated datasets hide problems that are obvious upstream (doubled rows, dropped rows).
5. Root cause = the most upstream dataset with a failing check. Everything downstream of it is impact.
   If several checks fail there, prefer duplicates, then schema, then profile, then freshness, then volume
   (volume and freshness are often symptoms). Finish the remaining checks on that dataset to rule out a second cause.
6. With no lineage declared, report each failing dataset separately and set confidence to medium at most.
7. Never use a name that did not come from a tool result. Never open logs or data files in full.
