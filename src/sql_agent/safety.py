"""Safety check for SQL written by the LLM.

Only ONE plain SELECT statement is allowed. Anything else (DROP, DELETE,
UPDATE, INSERT, several statements, ...) is rejected. If the query has no
LIMIT, we add LIMIT 1000 so a query can never return millions of rows.
"""
import sqlglot
from sqlglot import exp

MAX_ROWS = 1000

# Statement types that change data or the database itself
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
             exp.Alter, exp.Merge, exp.Command)


class UnsafeSQLError(ValueError):
    """Raised when SQL is not a single, read-only SELECT."""


def make_safe(sql: str) -> str:
    """Return a safe version of `sql`, or raise UnsafeSQLError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQLError(f"Could not parse SQL: {e}") from e

    if len(statements) != 1:
        raise UnsafeSQLError(f"Expected exactly 1 statement, got {len(statements)}")

    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise UnsafeSQLError(f"Only SELECT is allowed, got {tree.key.upper()}")

    # Extra check: nothing dangerous hidden inside (e.g. inside a CTE)
    if any(isinstance(node, FORBIDDEN) for node in tree.walk()):
        raise UnsafeSQLError("Query contains a data-changing statement")

    # Add a row limit if the query does not already have one
    if tree.args.get("limit") is None:
        tree = tree.limit(MAX_ROWS)

    return tree.sql(dialect="duckdb")
