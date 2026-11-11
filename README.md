# FinSight — AI Financial Analyst Agent

## How to run Phase 1

Phase 1 turns the raw SEC EDGAR Financial Statement Data Sets into a small DuckDB star schema.

1. Download the last 12 quarters of SEC files into `data/bronze/YYYYqN/` (already-downloaded quarters are skipped):
   ```
   python -m src.ingest.download_fsds
   ```
2. Install the packages:
   ```
   pip install -r requirements.txt
   ```
3. Clean the raw files into Parquet (`data/silver/`):
   ```
   python src/ingest/bronze_to_silver.py
   ```
4. Build the star schema (`data/gold/finsight.duckdb`):
   ```
   python src/ingest/silver_to_gold.py
   ```
5. Run the tests:
   ```
   pytest tests/test_gold.py
   ```

Gold tables:
- `dim_company` (cik, name, sector, country)
- `dim_date` (period_end, quarter, year)
- `fact_financials` (cik, period_end, metric, qtrs, value, source_tag, is_derived).
  `qtrs` = 0 (balance on period_end), 1 (one quarter) or 4 (full year).
  All revenue tags are mapped to metric `Revenue` (original tag in `source_tag`).
  Missing fiscal Q4 values of Revenue, NetIncomeLoss and OperatingIncomeLoss are derived as
  annual − (Q1+Q2+Q3) and marked `is_derived = true`.

## How to run Phase 2 (text-to-SQL)

1. Copy `.env.example` to `.env` and fill in `LLM_API_KEY` (a Google Gemini API key). `LLM_MODEL` is optional (default `gemini-3.8-flash`).
2. Teach the agent the schema, glossary and the examples in `src/sql_agent/training_examples.json`:
   ```
   python -m src.sql_agent.train
   ```
3. Ask a question:
   ```
   python -m src.sql_agent.agent "Which 5 companies have the most total assets?"
   ```
4. Run the tests:
   ```
   pytest tests/test_sql_agent.py -s
   ```

## How to run Phase 3 (document RAG)

1. Download the latest 10-K for each company into `data/docs/`:
   ```
   python -m src.rag.download_10k
   ```
2. Split, embed and store the documents in ChromaDB (`data/chroma_docs/`, takes ~6 minutes):
   ```
   python -m src.rag.ingest
   ```
3. Ask a question (the ticker at the end is optional):
   ```
   python -m src.rag.ask "What risks does Apple mention about supply chains?" AAPL
   ```
4. Run the tests:
   ```
   pytest tests/test_rag.py
   ```

## How to run Phase 4 (forecasting + anomaly detection)

No LLM calls in this phase.

1. Print the report (also saved to `eval/ml_results.md`):
   ```
   python -m eval.ml_report
   ```
2. Run the tests:
   ```
   pytest tests/test_ml.py
   ```

- `src/ml/forecast.py` - `forecast_revenue(cik, quarters=2)`: Prophet vs naive vs seasonal-naive, backtested on the last 4 quarters (MAPE).
- `src/ml/anomaly.py` - `find_anomalies(cik=None)`: year-over-year % change judged against the company's own history (robust z-score). Flagged when |z| > 4 AND at least 15 percentage points from its usual change. Isolation Forest per size bucket is shown as information only. Negative derived Q4 *revenue* is listed separately as "possible restatement" (a negative derived Q4 net/operating income can be a real loss, so it is not).

### Anomaly verification

The top flagged anomalies for our 10 companies were traced back to the original SEC filings (Silver/Bronze data): period length (`qtrs`), XBRL tag, and the filing they came from (adsh, form, filed date). All checked values were found to be **real business events, not data errors**: they come from the company's own 10-Q, use standard `us-gaap` tags with the right period length, the quarters add up to the reported year-to-date totals, and the year-ago values were repeated unchanged in later filings. Examples:

- **Alphabet net income, Q2 2026: $28.20B → $112.19B.** Filing 0001652044-26-000071 (10-Q, filed 2026-07-23). The jump comes from non-operating income ($97.98B vs $2.66B a year earlier); operating profit grew normally. Q1 + Q2 equals the reported 6-month total ($174.77B).
- **Walmart operating income, fiscal Q3 2024 (Oct 2023): $2.69B → $6.20B.** Filing 0000104169-23-000132 (10-Q, filed 2023-11-30). The year-ago quarter was unusually low; Q1+Q2+Q3 equals the reported 9-month total ($19.758B).
- **Amazon total assets, Jun 2026: $682B → $1.10T.** Filing 0001018724-26-000026 (10-Q, filed 2026-07-31). Steady quarterly growth ($818B → $917B → $1,096B); main drivers are other non-current assets (+$162B since Dec 2025), property and equipment (+$89B) and long-term debt (+$63B).

**Derived Q4 values** (Q4 = annual from the 10-K − Q1−Q2−Q3 from the 10-Qs) were checked the same way. In every case Q1+Q2+Q3 equals the 9-month total reported in the Q3 10-Q, so the derived Q4 is exactly what the company's own figures imply:

- **Apple net income, fiscal Q4 2024 (Sep 2024): $14.74B, −36% vs $22.96B a year earlier.** $93.74B (10-K 0000320193-25-000079) − $79.00B (Q1–Q3). Apple's 10-K (Note 8, Income Taxes) states that in Q4 2024 it "recorded a one-time income tax charge of $10.2 billion" after the EU State Aid ruling.
- **Apple net income, fiscal Q4 2025 (Sep 2025): $27.47B, +86% vs $14.74B.** $112.01B (same 10-K) − $84.54B (Q1–Q3). The jump is mostly the year-ago quarter being lowered by that one-time tax charge.
- **Nike net income, fiscal Q4 2026 (May 2026): $1.07B, +407% vs $0.21B a year earlier.** $3.108B (10-K 0000320187-26-000088) − $2.039B (Q1–Q3). The year-ago Q4 was very weak: $3.219B annual − $3.008B Q1–Q3 = $0.211B.

## How to run Phase 5 (agent + chat app)

Designed for the Gemini free tier: at most 2 LLM calls per question, cached answers cost 0.

1. In `.env`, list the models to try in order (optional, this is the default):
   ```
   LLM_MODELS=gemini-3.8-flash,gemini-3.5-flash
   ```
2. Start the chat app (opens http://localhost:8501):
   ```
   streamlit run app/streamlit_app.py
   ```
   Or ask from the terminal:
   ```
   python -m src.agent.agent "Forecast Walmart's revenue for the next 2 quarters"
   ```
3. Run the tests (no Gemini calls):
   ```
   pytest tests/test_agent.py tests/test_llm.py
   ```

- `src/llm.py` - shared LLM client for every tool: SQLite cache (`data/llm_cache.db`, keyed by model + prompt), model fallback on 429, "Daily free limit reached, try again tomorrow" when all models are exhausted, LLM call counting (max 2 per question).
- `src/agent/router.py` - picks the route without the LLM: keyword rules, then similarity to example questions (local embedding model). Routes: sql, docs, sql+docs ("why" questions about numbers), forecast, anomaly.
- `src/agent/agent.py` - `answer(question)` runs only the needed tools and builds the answer from a template (no extra LLM call). Forecast and anomaly use 0 LLM calls.
- `app/streamlit_app.py` - chat UI with answer, SQL, table, time chart, citations and "LLM calls used".

Note: the Gemini free tier allows about 20 requests per day per model. `src/llm.py` automatically moves to the next model in `LLM_MODELS` when one is over its limit.
