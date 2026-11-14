# FinSight evaluation: v1 vs v2 (2026-11-14)

v2 answered **36/50** v1 questions and **2/12** held-out questions (3 network/timeout error(s), retried on the next run). Accuracy counts judged answers only.

## v1 questions (50): v1 vs v2

| Metric | v1 (baseline b3c146e) | v2 |
|---|---|---|
| Routing accuracy (router only) | 44/50 (88%) | 50/50 (100%) |
| SQL execution accuracy | 18/20 (90%) | 17/17 (100%) (of 20) |
| Docs: key facts + right filing | 6/12 (50%) | 5/6 (83%) (of 12) |
| SQL + docs "why" | 2/8 (25%) | not run yet |
| Forecast / anomaly | 5/5 (100%) | 5/5 (100%) |
| Refuse / out of scope | 5/5 (100%) | 5/5 (100%) |
| Average latency per judged question | 86.2 s | 13.2 s |
| Average LLM calls per judged question | 0.88 | 0.67 |

**Grading change (v2):** docs08 ("What drove Nvidia's Data Center revenue growth in fiscal year 2024?") accepts the route ["docs"] or ["sql", "docs"], because it asks for a number and its explanation. In v1 only ["docs"] counted, so v1's docs08 result was graded under the stricter rule.

v1 latency is inflated by a slow network during that run (one question took 478 s).

## Held-out questions (12): v2 only

Frozen before any v2 fix (commit 1dcdaf9) and never used for tuning.

| Metric | v2 |
|---|---|
| Routing accuracy (router only) | 11/12 (92%) |
| SQL execution accuracy | not run yet |
| Docs: key facts + right filing | not run yet |
| SQL + docs "why" | not run yet |
| Refuse / out of scope | 2/2 (100%) |
| Average latency per judged question | 0.0 s |
| Average LLM calls per judged question | 0.00 |

## Retrieval rank tables (no Gemini, v1 questions only)

<!-- Output of: python -m eval.retrieval_check (commit c92ab10, v1 questions only, no Gemini) -->

### 'Why' questions (top 6 reach Gemini)

| Question | Before step 2 (v1) | After step 2 | Now (step 2b) | In top 6 now? |
|---|---|---|---|---|
| why02 | 90 | 3 | 3 | yes |
| why03 | 46 | 9 | 13 | no |
| why04 | 8 | 1 | 1 | yes |
| why06 | 29 | 6 | 3 | yes |
| why07 | 1 | 4 | 6 | yes |
| why08 | 47 | 1 | 1 | yes |

### v1 docs questions: rank of the expected passage (✓ = in the top 6)

| Question | Before step 2 (v1) | After step 2 | Now (step 2b) |
|---|---|---|---|
| docs01 What does Apple say about its reliance on outsourcing p | 2 ✓ | 2 ✓ | 2 ✓ |
| docs02 How large was the one-time income tax charge Apple reco | 1 ✓ | 1 ✓ | 1 ✓ |
| docs03 What risks does Tesla mention about competition? | 4 ✓ | 12 | 10 |
| docs04 What are Microsoft's reportable segments? | 1 ✓ | 1 ✓ | 1 ✓ |
| docs05 What are Amazon's reportable segments? | 1 ✓ | 1 ✓ | 1 ✓ |
| docs06 What are Alphabet's reportable segments? | 15 | 1 ✓ | 1 ✓ |
| docs07 What are Nvidia's two reportable segments? | 3 ✓ | 1 ✓ | 1 ✓ |
| docs08 What drove Nvidia's Data Center revenue growth in fisca | 3 ✓ | 1 ✓ | 3 ✓ |
| docs09 How does Coca-Cola describe its relationship with its b | 3 ✓ | 2 ✓ | 1 ✓ |
| docs10 What are Walmart's reportable segments? | 1 ✓ | 1 ✓ | 1 ✓ |
| docs11 What reportable business segments does JPMorgan describ | 1 ✓ | 1 ✓ | 1 ✓ |
| docs12 Which brands does Nike sell besides the Nike brand? | 6 ✓ | 2 ✓ | 2 ✓ |

### docs03: the "established and new automobile manufacturers" passage

before step 2: 4 ✓ | after step 2: 16 | now: 14

## Failures: v1 questions, v2 run

- **docs03** (docs) What risks does Tesla mention about competition? - missing key facts: manufacturers
- **sql04** (sql) network/timeout error, will be retried
- **sql06** (sql) network/timeout error, will be retried
- **sql09** (sql) network/timeout error, will be retried

## Failures: held-out questions

- **h_docs04** (routing) How does Microsoft return capital to its shareholders? - routed to ['sql']

## Not answered yet

docs07, docs08, docs09, docs10, docs11, docs12, why01, why02, why03, why04, why05, why06, why07, why08, h_docs01, h_docs02, h_docs03, h_docs04, h_sql01, h_sql02, h_why01, h_why02, h_why03, h_why04
