# FinSight evaluation (2026-11-13)

Questions with a result: **50/50** (50 judged, 0 network/timeout error(s), 0 not run yet).

Accuracy counts only judged answers: a network or timeout error means the agent never got to answer, so it is listed separately and retried on the next run.

| Metric | Result | Network errors |
|---|---|---|
| Routing accuracy (all questions, router only) | 44/50 (88%) | - |
| SQL execution accuracy (of 20) | 18/20 (90%) | 0 |
| Docs accuracy: key facts + right filing (of 12) | 6/12 (50%) | 0 |
| SQL + docs "why" (of 8) | 2/8 (25%) | 0 |
| Forecast / anomaly: route + no error (of 5) | 5/5 (100%) | 0 |
| Refuse / out of scope: route (of 5) | 5/5 (100%) | 0 |
| Average latency per judged question | 86.2 s | |
| Average LLM calls per judged question | 0.88 | |
| Judged answers with 0 LLM calls | 12/50 (24%) | |

Scoring: SQL = same values as the reference result (any row order / column names); docs = all key facts present and an expected 10-K cited (keyword matching, no LLM judge).

## Failures (wrong answers or wrong routes)

- **docs02** (routing) How large was the one-time income tax charge Apple recorded in fiscal 2024 because of the EU State Aid decision? - routed to ['sql'], expected ['docs'] (similarity, similarity 0.622)
- **docs04** (routing) What are Microsoft's reportable segments? - routed to ['anomaly'], expected ['docs'] (similarity, similarity 0.443)
- **docs05** (routing) What are Amazon's reportable segments? - routed to ['sql', 'docs'], expected ['docs'] (similarity, similarity 0.42)
- **docs06** (routing) What are Alphabet's reportable segments? - routed to ['sql', 'docs'], expected ['docs'] (similarity, similarity 0.378)
- **docs07** (routing) What are Nvidia's two reportable segments? - routed to ['anomaly'], expected ['docs'] (similarity, similarity 0.535)
- **docs08** (routing) What drove Nvidia's Data Center revenue growth in fiscal year 2024? - routed to ['sql', 'docs'], expected ['docs'] (keywords)
- **sql13** (sql) What was Coca-Cola's operating income in the quarter ending 2026-03-31? - row count 2 != expected 1
  - SQL: `SELECT c.name, f.period_end, f.value AS operating_income FROM fact_financials AS f JOIN dim_company AS c ON f.cik = c.cik WHERE c.name ILIKE '%coca%cola%' AND f.metric = 'OperatingIncomeLoss' AND f.qtrs = 1 AND f.period_end = '2026-03-31' LIMIT 1000`
- **sql14** (sql) What was Coca-Cola's net profit margin (net income divided by revenue) in the quarter ending 2026-06-30? - row count 2 != expected 1
  - SQL: `SELECT c.name, f.period_end, MAX(f.value) FILTER(WHERE f.metric = 'NetIncomeLoss') AS net_income, MAX(f.value) FILTER(WHERE f.metric = 'Revenue') AS revenue, MAX(f.value) FILTER(WHERE f.metric = 'NetIncomeLoss') / MAX(f.value) FILTER(WHERE f.metric = 'Revenue') AS net_margin FROM fact_financials AS f JOIN dim_company AS c ON f.cik = c.cik WHERE c.name ILIKE '%COCA%COLA%' AND f.period_end = '2026-06-30' AND f.qtrs = 1 GROUP BY c.name, f.period_end LIMIT 1000`
- **docs02** (docs) How large was the one-time income tax charge Apple recorded in fiscal 2024 because of the EU State Aid decision? - routed to ['sql'], expected ['docs']
- **docs04** (docs) What are Microsoft's reportable segments? - routed to ['anomaly'], expected ['docs']
- **docs06** (docs) What are Alphabet's reportable segments? - routed to ['sql', 'docs'], expected ['docs']
- **docs07** (docs) What are Nvidia's two reportable segments? - routed to ['anomaly'], expected ['docs']
- **docs08** (docs) What drove Nvidia's Data Center revenue growth in fiscal year 2024? - routed to ['sql', 'docs'], expected ['docs']
- **why02** (sql+docs) Why did Apple's net income fall in fiscal 2024? - docs part: Not found in the documents.
- **why03** (sql+docs) Why did Walmart's operating income jump in the quarter ending October 2023? - docs part: Not found in the documents.
- **docs05** (docs) What are Amazon's reportable segments? - routed to ['sql', 'docs'], expected ['docs']
- **why04** (sql+docs) Why did Microsoft's revenue grow in fiscal 2025? - docs part: Not found in the documents.
- **why06** (sql+docs) Why did Tesla's operating income decline in 2024? - docs part: Not found in the documents.
- **why07** (sql+docs) Why did Nike's revenue fall in fiscal 2025? - docs part: Not found in the documents.
- **why08** (sql+docs) Why did JPMorgan's revenue rise in 2024? - docs part: Not found in the documents.

## Errors (network/timeout - not counted as failures, retried on the next run)

None.
