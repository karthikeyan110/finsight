# FinSight — AI Financial Analyst Agent

## How to run Phase 1

Phase 1 turns the raw SEC EDGAR Financial Statement Data Sets into a small DuckDB star schema.

1. Put the SEC files (`sub.txt`, `num.txt`, `tag.txt`, `pre.txt`) in `data/bronze/`.
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
- `fact_financials` (cik, period_end, metric, value). Income metrics are quarterly for 10-Q filings and full-year for 10-K filings. Balance-sheet metrics are the value on period_end.

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

Note: the Gemini free tier allows about 20 requests per day per model. If you hit the limit, set a different `LLM_MODEL` in `.env` (e.g. `gemini-3.5-flash`).
