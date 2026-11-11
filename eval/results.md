# FinSight evaluation (2026-11-11)

Questions answered so far: **18/50** (32 remaining - the Gemini free tier allows a limited number of calls per day).

| Metric | Result |
|---|---|
| Routing accuracy (all questions, router only) | 44/50 (88%) |
| SQL execution accuracy | 8/8 (100%) of 20 |
| Docs accuracy (key facts + right filing) | not run yet of 12 |
| SQL + docs ("why") | not run yet of 8 |
| Forecast / anomaly (route + no error) | 5/5 (100%) of 5 |
| Refuse / out of scope (route) | 5/5 (100%) of 5 |
| Average latency per question | 3.8 s |
| Average LLM calls per question | 0.44 |
| Answered with 0 LLM calls | 10/18 (56%) |

Scoring: SQL = same values as the reference result (any row order / column names); docs = all key facts present and an expected 10-K cited (keyword matching, no LLM judge).

## Failures

- **docs02** (routing) How large was the one-time income tax charge Apple recorded in fiscal 2024 because of the EU State Aid decision? - routed to ['sql'], expected ['docs'] (similarity, similarity 0.622)
- **docs04** (routing) What are Microsoft's reportable segments? - routed to ['anomaly'], expected ['docs'] (similarity, similarity 0.443)
- **docs05** (routing) What are Amazon's reportable segments? - routed to ['sql', 'docs'], expected ['docs'] (similarity, similarity 0.42)
- **docs06** (routing) What are Alphabet's reportable segments? - routed to ['sql', 'docs'], expected ['docs'] (similarity, similarity 0.378)
- **docs07** (routing) What are Nvidia's two reportable segments? - routed to ['anomaly'], expected ['docs'] (similarity, similarity 0.535)
- **docs08** (routing) What drove Nvidia's Data Center revenue growth in fiscal year 2024? - routed to ['sql', 'docs'], expected ['docs'] (keywords)

## Not answered yet

docs01, docs02, docs03, docs04, docs05, docs06, docs07, docs08, docs09, docs10, docs11, docs12, sql09, sql10, sql11, sql12, sql13, sql14, sql15, sql16, sql17, sql18, sql19, sql20, why01, why02, why03, why04, why05, why06, why07, why08
