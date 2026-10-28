# Severity rubric

Decide from the check type, `business_visible` and lineage; never from a table name. Assign the highest level
that applies and justify it in the Impact section.

- SEV1: wrong values in a business-visible dataset, or upstream of one, with a large error
  (a measure's median shifts by a large factor; a repeated load doubles totals).
- SEV2: wrong values with a partial effect (null keys dropping rows from a join; a renamed column replaced by a default),
  or wrong values only in datasets no business user sees.
- SEV3: data is late or missing, but the values present are correct.
- SEV4: a quality or schema warning with no measurable effect yet (for example an unexpected new column).

A plug-in states the severity it expects in its own expected results file. Never hard-code one.
