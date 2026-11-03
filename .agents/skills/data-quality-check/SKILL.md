---
name: data-quality-check
description: Check a data set and the KPI code that uses it for data quality problems such as duplicate keys, missing values, invalid values, and wrong denominators. Use when data is generated or imported, or when a KPI changes. Not for layout or styling questions.
---

# Data quality check

Do not change any files. Only investigate and report.

1. Read `docs/data-dictionary.md` for columns, types, required fields, and allowed values. If it is missing or incomplete, state that as a limitation and infer cautiously from the available code and data.
2. Check the data column by column for unique keys, missing values, and valid values. Compare the data against the dictionary and relevant generation or import code. Distinguish confirmed defects from assumptions.
3. Find each KPI that uses the data and check whether it counts rows or distinct keys, whether missing values are silently treated as zero or excluded, and whether its denominator matches the KPI definition. Trace calculations to their source where possible.
4. Report findings in one table with these columns: `Problem | Rows or code line | Affected KPI | Suggested fix`. Include concrete row identifiers or file and line references where available. If no issues are found, say so and describe the checks performed.
5. List open questions about KPI definitions and state what you could not check, including missing documentation or unavailable data.

Keep the report concise and evidence based. Do not modify source data, KPI code, or documentation as part of the check.
