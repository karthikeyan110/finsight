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

