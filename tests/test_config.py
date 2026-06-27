import importlib

import pytest

import config as runtime_config


ENV_NAMES = (
    "APP_MODE",
    "ANSWER_PATH",
    "STORAGE_MODE",
    "ASK_MODEL_ID",
    "ONBOARDING_MODEL_ID",
    "RAG_MODEL_ARN",
    "GAP_THRESHOLD",
    "HISTORY_LIMIT",
    "MODEL_SMART",
    "MODEL_FAST",
    "MODEL_SMART_ARN",
)


@pytest.fixture(autouse=True)
def clean_settings_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_settings_have_safe_hackathon_defaults():
    config = runtime_config

    assert hasattr(config, "Settings")
    settings = config.Settings.from_env(load_dotenv_file=False)

    assert settings.app_mode == "live"
    assert settings.answer_path == "advanced"
    assert settings.storage_mode == "sqlite"
    assert settings.ask_model_id == "us.anthropic.claude-sonnet-4-6"
    assert (
        settings.onboarding_model_id
        == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    assert settings.history_limit == 10
    assert settings.gap_threshold == 0.2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_MODE", "automatic"),
        ("ANSWER_PATH", "sometimes"),
        ("STORAGE_MODE", "redis"),
        ("GAP_THRESHOLD", "1.5"),
        ("HISTORY_LIMIT", "0"),
    ],
)
def test_settings_reject_invalid_values(monkeypatch, name, value):
    config = importlib.import_module("config")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        config.Settings.from_env(load_dotenv_file=False)


def test_new_model_names_take_priority_over_compatibility_aliases(monkeypatch):
    config = importlib.import_module("config")
    monkeypatch.setenv("ASK_MODEL_ID", "new-ask")
    monkeypatch.setenv("MODEL_SMART", "old-smart")
    monkeypatch.setenv("ONBOARDING_MODEL_ID", "new-onboarding")
    monkeypatch.setenv("MODEL_FAST", "old-fast")
    monkeypatch.setenv("RAG_MODEL_ARN", "new-rag")
    monkeypatch.setenv("MODEL_SMART_ARN", "old-rag")

    settings = config.Settings.from_env(load_dotenv_file=False)

    assert settings.ask_model_id == "new-ask"
    assert settings.onboarding_model_id == "new-onboarding"
    assert settings.rag_model_arn == "new-rag"
