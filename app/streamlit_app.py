"""FinSight chat app.

Run:  streamlit run app/streamlit_app.py      (opens http://localhost:8501)

For each answer you see: the answer text, the SQL (expandable), the result table,
a chart when the result has a time column, citations, forecasts with their range,
and a small "LLM calls used: N" note.
"""
import sys
from pathlib import Path

# Streamlit starts in app/, so make the project root importable ("from src...")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.agent.agent import answer

st.set_page_config(page_title="FinSight", page_icon="📊", layout="wide")
st.title("📊 FinSight - AI Financial Analyst")
st.caption("Numbers from SEC data, explanations from 10-K filings, revenue forecasts and "
           "anomaly checks. Runs on the Gemini free tier (max 2 LLM calls per question).")

EXAMPLES = [
    "What was Microsoft's quarterly revenue over the last 2 years?",
    "What risks does Tesla mention about competition?",
    "Forecast Walmart's revenue for the next 2 quarters",
    "Any unusual changes at Nvidia?",
    "Why did Alphabet's net income jump in Q2 2026?",
]


def time_chart(df: pd.DataFrame):
    """Line chart when the table has a time column and a number column; else None."""
    time_cols = [c for c in df.columns if "period" in c.lower() or "date" in c.lower()]
    num_cols = [c for c in df.select_dtypes("number").columns
                if c.lower() not in ("cik", "qtrs", "year", "quarter")]
    if not time_cols or not num_cols or len(df) < 2:
        return None
    t, y = time_cols[0], num_cols[0]
    data = df.assign(**{t: pd.to_datetime(df[t])}).sort_values(t)
    fig = go.Figure()
    groups = data.groupby("name") if "name" in data.columns and data["name"].nunique() > 1 else [(y, data)]
    for label, part in groups:  # one line per company if there are several
        fig.add_trace(go.Scatter(x=part[t], y=part[y], mode="lines+markers", name=str(label)))
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10), title=y)
    return fig


def forecast_chart(result: dict, ticker: str):
    """Actual quarterly revenue + forecast with its 80% range."""
    hist, fc = result["history"], result["forecast"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["ds"], y=hist["y"], mode="lines+markers", name="Actual"))
    fig.add_trace(go.Scatter(x=list(fc["ds"]) + list(fc["ds"])[::-1],
                             y=list(fc["yhat_upper"]) + list(fc["yhat_lower"])[::-1],
                             fill="toself", line=dict(width=0), opacity=0.25,
                             name="80% range", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fc["ds"], y=fc["yhat"], mode="lines+markers",
                             line=dict(dash="dash"), name="Forecast"))
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10),
                      title=f"{ticker} quarterly revenue (USD)")
    return fig


def show(out: dict):
    """Render one answer."""
    st.markdown(out["answer"])

    if out.get("table") is not None:
        fig = time_chart(out["table"])
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(out["table"], use_container_width=True, hide_index=True)
    if out.get("sql"):
        with st.expander("SQL used"):
            st.code(out["sql"], language="sql")
    if out.get("forecast"):
        st.plotly_chart(forecast_chart(out["forecast"], out["ticker"]), use_container_width=True)
    if out.get("anomalies") is not None and not out["anomalies"].empty:
        cols = ["name", "metric", "period_end", "pct_change", "z_score", "category"]
        st.dataframe(out["anomalies"][cols], use_container_width=True, hide_index=True)

    route = "+".join(out["routes"]) + (f" · {out['ticker']}" if out.get("ticker") else "")
    st.caption(f"Route: {route} ({out['route_method']}) · LLM calls used: {out['llm_calls']}")


# ---------- chat ----------
if "history" not in st.session_state:
    st.session_state.history = []  # list of (question, answer dict)

with st.sidebar:
    st.subheader("Try an example")
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True):
            st.session_state.pending = ex
    st.divider()
    st.caption("Documents and forecasts: AAPL, MSFT, AMZN, GOOGL, NVDA, TSLA, KO, WMT, "
               "JPM, NKE. Numbers (SQL): all ~7,000 companies in the SEC data.")

for q, out in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        show(out)

question = st.chat_input("Ask about a company's financials...") or st.session_state.pop("pending", None)
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            out = answer(question)
        show(out)
    st.session_state.history.append((question, out))
