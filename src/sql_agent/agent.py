"""Vanna 2.x text-to-SQL agent over data/gold/finsight.duckdb.

Main entry point:  ask_sql(question) -> (sql, dataframe)

How it works:
  1. Before the LLM is called, our context enhancer adds the DDL, glossary and
     the 5 most similar example question->SQL pairs to the system prompt.
  2. The LLM (Gemini) calls the `run_sql` tool with a SQL query.
  3. Our SafeDuckDBRunner checks the SQL (SELECT only, LIMIT added) and runs it
     on a READ-ONLY DuckDB connection. The last good query + result are kept.
"""
import asyncio
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

from src.sql_agent.safety import make_safe

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


def build_agent() -> tuple[Agent, SafeDuckDBRunner]:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is missing. Add it to the .env file.")

    llm = GeminiLlmService(model=os.getenv("LLM_MODEL", "gemini-3.8-flash"), api_key=api_key)
    memory = build_memory()
    runner = SafeDuckDBRunner(DB_PATH)

    tools = ToolRegistry()
    tools.register_local_tool(
        RunSqlTool(sql_runner=runner, file_system=LocalFileSystem(str(RESULTS_DIR))),
        access_groups=["user"])

    agent = Agent(
        llm_service=llm,
        tool_registry=tools,
        user_resolver=LocalUserResolver(),
        agent_memory=memory,
        config=AgentConfig(stream_responses=False, temperature=0.0, max_tool_iterations=3),
        system_prompt_builder=FixedPrompt(),
        llm_context_enhancer=TrainingEnhancer(memory),
    )
    return agent, runner


_agent = None  # built once, reused for every question


async def _ask(question: str) -> tuple[str, pd.DataFrame]:
    global _agent
    if _agent is None:
        _agent = build_agent()
    agent, runner = _agent
    runner.last_sql, runner.last_df = None, None

    # Run the agent until it finishes (we ignore the UI components it yields)
    async for _ in agent.send_message(RequestContext(), question,
                                      conversation_id=str(uuid.uuid4())):
        pass

    if runner.last_sql is None:
        raise RuntimeError(f"The agent did not produce a valid SQL query for: {question}")
    return runner.last_sql, runner.last_df


def ask_sql(question: str) -> tuple[str, pd.DataFrame]:
    """Turn a question into safe SQL, run it, and return (sql, dataframe)."""
    return asyncio.run(_ask(question))


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What are Microsoft's total assets?"
    sql, df = ask_sql(q)
    print(sql)
    print(df.head(10).to_string(index=False))
