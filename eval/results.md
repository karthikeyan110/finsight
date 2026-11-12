# FinSight evaluation (2026-11-13)

Questions with a result: **44/50** (42 judged, 2 network/timeout error(s), 6 not run yet).

Accuracy counts only judged answers: a network or timeout error means the agent never got to answer, so it is listed separately and retried on the next run.

| Metric | Result | Network errors |
|---|---|---|
| Routing accuracy (all questions, router only) | 44/50 (88%) | - |
| SQL execution accuracy (of 20) | 16/18 (89%) | 2 |
| Docs accuracy: key facts + right filing (of 12) | 6/11 (55%) | 0 |
| SQL + docs "why" (of 8) | 1/3 (33%) | 0 |
| Forecast / anomaly: route + no error (of 5) | 5/5 (100%) | 0 |
| Refuse / out of scope: route (of 5) | 5/5 (100%) | 0 |
| Average latency per judged question | 93.3 s | |
| Average LLM calls per judged question | 0.83 | |
| Judged answers with 0 LLM calls | 12/42 (29%) | |

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

## Errors (network/timeout - not counted as failures, retried on the next run)

- **sql19** (sql) What was Nike's net income for the fiscal year ending May 2026? - no SQL result: Numbers (SQL): Could not turn this question into SQL ([WinError 10054] An existing connection was forcibly closed by the remote host).
- **sql20** (sql) Which 5 companies had the largest total assets on 2026-06-30? - no SQL result: Numbers (SQL): Could not turn this question into SQL ([WinError 10054] An existing connection was forcibly closed by the remote host).

## Not answered yet

docs05, why04, why05, why06, why07, why08
