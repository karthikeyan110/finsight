"""Tests for the shared LLM client (src/llm.py) using fake models - NO Gemini calls."""
import pytest

from src import llm


class QuotaError(Exception):
    code = 429  # like Gemini's "daily free limit exceeded"


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "CACHE_PATH", tmp_path / "llm_cache.db")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODELS", "model-a,model-b")
    llm.reset_calls()


def test_fallback_on_429_and_cache(monkeypatch, fake_env):
    calls = []

    def fake(model, prompt):
        calls.append(model)
        if model == "model-a":
            raise QuotaError("daily limit")
        return f"answer from {model}"

    monkeypatch.setattr(llm, "_call_model", fake)
    assert llm.generate("hello") == "answer from model-b"   # moved to the next model
    assert llm.calls_used() == 1                            # only the successful call counts
    assert llm.generate("hello") == "answer from model-b"   # second time: from cache
    assert calls == ["model-a", "model-b"]                  # ... no new API calls
    assert llm.calls_used() == 1


def test_all_models_exhausted_returns_message(monkeypatch, fake_env):
    def always_429(model, prompt):
        raise QuotaError("daily limit")

    monkeypatch.setattr(llm, "_call_model", always_429)
    assert llm.generate("hello") == llm.LIMIT_MESSAGE      # no crash


def test_network_error_moves_to_next_model(monkeypatch, fake_env):
    def flaky(model, prompt):
        if model == "model-a":
            raise ConnectionResetError("connection forcibly closed")
        return "ok"

    monkeypatch.setattr(llm, "_call_model", flaky)
    assert llm.generate("hi") == "ok"


def test_real_bugs_are_not_hidden(monkeypatch, fake_env):
    def broken(model, prompt):
        raise ValueError("a real bug")

    monkeypatch.setattr(llm, "_call_model", broken)
    with pytest.raises(ValueError):
        llm.generate("hi")


def test_max_two_calls_per_question(monkeypatch, fake_env):
    monkeypatch.setattr(llm, "_call_model", lambda model, prompt: "ok")
    llm.generate("q1")
    llm.generate("q2")
    with pytest.raises(llm.CallBudgetExceeded):
        llm.generate("q3")  # a 3rd call in the same question is refused


def test_forecast_question_uses_no_llm(monkeypatch, fake_env):
    from src.agent.agent import answer

    def no_llm(*args, **kwargs):
        raise AssertionError("forecast must not call the LLM")

    monkeypatch.setattr(llm, "_call_model", no_llm)
    monkeypatch.setattr("src.sql_agent.agent.ask_sql", no_llm)
    out = answer("Forecast Walmart's revenue for the next 3 quarters")
    assert out["routes"] == ["forecast"]
    assert len(out["forecast"]["forecast"]) == 3
    assert out["llm_calls"] == 0
