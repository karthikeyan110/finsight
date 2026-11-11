# FinSight — AI Financial Analyst Agent
## Goal
Agent that answers questions about US public-company financials: numbers via text-to-SQL (Vanna), explanations via RAG over 10-K PDFs, plus revenue forecasting and anomaly detection. Built locally first (DuckDB), later moved to Microsoft Fabric.

## About me
I am a beginner. After every change, explain in 3–5 simple sentences what you built and why. Add short comments in code.

## Stack
Python 3.11, pandas, DuckDB, Vanna 2.x, ChromaDB, sentence-transformers, LangGraph, Streamlit, scikit-learn, Prophet, pytest.

## Folder layout
data/bronze, data/silver, data/gold, data/docs (PDFs), src/ingest, src/sql_agent, src/rag, src/ml, src/agent, app/, tests/, eval/

## Rules
- Secrets only in .env (never commit it; keep .env.example with key names only).
- Generated SQL must be SELECT-only; reject anything else.
- The LLM never does arithmetic; numbers come from SQL or Python.
- Only make changes I ask for. No extra features.
- Before installing a new package or deleting any file, tell me and wait for my OK.
- Every phase ends with a runnable command and a passing test.
