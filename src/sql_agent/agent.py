"""Vanna 2.x text-to-SQL agent over data/gold/finsight.duckdb.

Main entry point:  ask_sql(question) -> (sql, dataframe)

How it works:
  1. Before the LLM is called, our context enhancer adds the DDL, glossary and
     the 5 most similar example question->SQL pairs to the system prompt.
  2. The LLM (Gemini) calls the `run_sql` tool with a SQL query.
  3. Our SafeDuckDBRunner checks the SQL (SELECT only, LIMIT added) and runs it
     on a READ-ONLY DuckDB connection. The last good query + result are kept.
  4. Shared LLM client rules (src/llm.py): the SQL for each question is cached,
     and if one Gemini model fails (e.g. daily limit) the next model is tried.
"""
import asyncio
import logging
import os
import uuid
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

from vanna import Agent, AgentConfig
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.enhancer import LlmContextEnhancer
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt import SystemPromptBuilder
from vanna.core.tool import ToolContext
from vanna.core.user import RequestContext, User, UserResolver
from vanna.integrations.chromadb import ChromaAgentMemory
from vanna.integrations.google import GeminiLlmService
from vanna.integrations.local import LocalFileSystem
from vanna.tools import RunSqlTool

from src import llm
from src.sql_agent.safety import make_safe

log = logging.getLogger(__name__)
# Vanna logs full tracebacks for LLM errors (e.g. daily limit) that our model
# fallback already handles; keep its log quiet and report problems ourselves.
logging.getLogger("vanna").setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "gold" / "finsight.duckdb"
MEMORY_DIR = ROOT / "data" / "vanna_memory"     # ChromaDB training memory
RESULTS_DIR = ROOT / "data" / "vanna_results"   # CSVs that Vanna's run_sql tool writes

load_dotenv(ROOT / ".env")

# One fixed local user (we have no login system)
LOCAL_USER = User(id="local", username="local", group_memberships=["user"])

SYSTEM_PROMPT = """You are FinSight's SQL assistant. The database is DuckDB.
For every question, call the run_sql tool exactly once with ONE read-only SELECT query.
Use only the tables and columns in the DDL below. Do not do any arithmetic yourself:
all calculations must happen inside the SQL. After the tool returns, reply with one short sentence."""


class SafeDuckDBRunner(SqlRunner):
    """Runs only safe SQL, on a read-only connection, and remembers the last result."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.last_sql: str | None = None
        self.last_df: pd.DataFrame | None = None

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        sql = make_safe(args.sql)  # raises UnsafeSQLError -> the LLM sees the error
        con = duckdb.connect(str(self.db_path), read_only=True)
        try:
            df = con.execute(sql).df()
        finally:
            con.close()
        self.last_sql, self.last_df = sql, df
        return df


class FixedPrompt(SystemPromptBuilder):
    """Our own short system prompt instead of Vanna's generic one."""

    async def build_system_prompt(self, user, tools):
        return SYSTEM_PROMPT


class TrainingEnhancer(LlmContextEnhancer):
    """Adds the training memories (DDL, glossary, similar examples) to the prompt."""

    def __init__(self, memory: ChromaAgentMemory):
        self.memory = memory

    async def enhance_system_prompt(self, system_prompt, user_message, user):
        ctx = make_context(self.memory)
        # DDL + glossary are few, so we always include all of them
        notes = await self.memory.get_recent_text_memories(ctx, limit=100)
        # The 5 example questions most similar to the user's question
        examples = await self.memory.search_similar_usage(
            user_message, ctx, limit=5, similarity_threshold=0.0, tool_name_filter="run_sql")

        parts = [system_prompt, "\n## Schema and glossary"]
        parts += [f"- {n.content}" for n in notes]
        parts.append("\n## Example questions and correct SQL")
        for ex in examples:
            parts.append(f"Q: {ex.memory.question}\nSQL: {ex.memory.args['sql']}")
        return "\n".join(parts)

    async def enhance_user_messages(self, messages, user):
        return messages


class LocalUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return LOCAL_USER


def build_memory() -> ChromaAgentMemory:
    return ChromaAgentMemory(persist_directory=str(MEMORY_DIR), collection_name="finsight_sql")


def make_context(memory: ChromaAgentMemory) -> ToolContext:
    """Small helper: Vanna's memory functions need a ToolContext."""
    return ToolContext(user=LOCAL_USER, conversation_id="setup",
                       request_id=str(uuid.uuid4()), agent_memory=memory)


class CountingGemini(GeminiLlmService):
    """Vanna's Gemini service + the shared client's rules: call budget, call counting,
    and remembering the last error (Vanna hides errors, but we need them for fallback)."""

    last_error: Exception | None = None

    def __init__(self, model: str, api_key: str, **kwargs):
        super().__init__(model=model, api_key=api_key, **kwargs)
        # Same client as Vanna's, plus a 60 s timeout per request (src/llm.py)
        from google import genai
        self._client = genai.Client(api_key=api_key,
                                    http_options={"timeout": llm.REQUEST_TIMEOUT_MS})

    async def send_request(self, request):
        self.last_error = None
        try:
            llm.check_budget()
            response = await super().send_request(request)
        except Exception as e:
            self.last_error = e
            if llm.error_kind(e) is not None:
                llm.record_call(self.model_name, ok=False)  # e.g. 429: no quota used
            raise
        llm.record_call(self.model_name, ok=True)
        return response


def build_agent(model: str) -> tuple[Agent, SafeDuckDBRunner, CountingGemini]:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is missing. Add it to the .env file.")

    llm_service = CountingGemini(model=model, api_key=api_key)
    memory = build_memory()
    runner = SafeDuckDBRunner(DB_PATH)

    tools = ToolRegistry()
    tools.register_local_tool(
        RunSqlTool(sql_runner=runner, file_system=LocalFileSystem(str(RESULTS_DIR))),
        access_groups=["user"])

    agent = Agent(
        llm_service=llm_service,
        tool_registry=tools,
        user_resolver=LocalUserResolver(),
        agent_memory=memory,
        # max_tool_iterations=1: stop right after the SQL tool runs. We only need the SQL
        # and its result; a second LLM turn would just summarise it, and current Gemini
        # models reject Vanna's tool-result message format ("Role 'function' is not
        # supported"), so that turn only wasted a request and printed an error.
        config=AgentConfig(stream_responses=False, temperature=0.0, max_tool_iterations=1),
        system_prompt_builder=FixedPrompt(),
        llm_context_enhancer=TrainingEnhancer(memory),
    )
    return agent, runner, llm_service


_agents = {}  # one agent per model, built once and reused


def run_safe_sql(sql: str) -> tuple[str, pd.DataFrame]:
    """Check SQL with the safety rules and run it read-only (no LLM involved)."""
    safe = make_safe(sql)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return safe, con.execute(safe).df()
    finally:
        con.close()


async def _ask(agent: Agent, runner: SafeDuckDBRunner, question: str) -> str | None:
    """Let one agent answer; return the SQL it ran successfully (or None)."""
    runner.last_sql, runner.last_df = None, None
    # Run the agent until it finishes (we ignore the UI components it yields).
    # Vanna catches LLM errors itself, so a failed model just leaves last_sql empty.
    async for _ in agent.send_message(RequestContext(), question,
                                      conversation_id=str(uuid.uuid4())):
        pass
    return runner.last_sql


def ask_sql(question: str) -> tuple[str, pd.DataFrame]:
    """Turn a question into safe SQL, run it, and return (sql, dataframe).

    1. Cache (src/llm.py, keyed by model + question): re-run the saved SQL, 0 LLM calls.
    2. Otherwise try each model in order. Only move to the next model when one is
       unavailable (429 daily limit, overloaded, network). If a model answered but
       wrote no usable SQL, stop: trying again would use more free quota.

    Raises llm.DailyLimitReached (friendly message) when every model is over its limit.
    """
    key = "SQL: " + question
    cached_sql = llm.cached_any(key)
    if cached_sql is not None:
        return run_safe_sql(cached_sql)  # re-checked + re-run on today's data

    kinds = []
    for model in llm.models():
        if model not in _agents:
            _agents[model] = build_agent(model)
        agent, runner, service = _agents[model]
        sql = asyncio.run(_ask(agent, runner, question))
        if sql is not None:
            llm.cache_set(model, key, sql)
            return sql, runner.last_df

        err = service.last_error
        if isinstance(err, llm.CallBudgetExceeded):
            raise err
        kind = llm.error_kind(err) if err is not None else None
        if kind is None:  # the model answered (or hit a real error) but gave no SQL
            raise RuntimeError("Could not turn this question into SQL"
                               + (f" ({err})" if err is not None else "") + ".")
        log.warning("Model %s unavailable (%s), trying the next model", model, kind)
        kinds.append(kind)

    if kinds and all(k == "limit" for k in kinds):
        raise llm.DailyLimitReached()
    raise RuntimeError(llm.UNAVAILABLE_MESSAGE)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What are Microsoft's total assets?"
    sql, df = ask_sql(q)
    print(sql)
    print(df.head(10).to_string(index=False))
