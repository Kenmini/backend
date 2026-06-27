import importlib

import pytest

import config as runtime_config

ENV_NAMES = (
    "AWS_REGION",
    "KB_ID",
    "APP_MODE",
    "ANSWER_PATH",
    "STORAGE_MODE",
    "ASK_MODEL_ID",
    "ONBOARDING_MODEL_ID",
    "RAG_MODEL_ARN",
    "GAP_THRESHOLD",
    "HISTORY_LIMIT",
    "PUBLIC_DEMO",
    "DEMO_API_TOKEN",
    "MODEL_RATE_LIMIT_PER_MINUTE",
    "CORS_ORIGINS",
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
    assert settings.onboarding_model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert settings.history_limit == 10
    assert settings.gap_threshold == 0.2
    assert settings.public_demo is False
    assert settings.demo_api_token is None
    assert settings.model_rate_limit_per_minute == 30


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


def test_public_demo_requires_specific_cors_and_strong_token(monkeypatch):
    config = runtime_config
    monkeypatch.setenv("PUBLIC_DEMO", "true")

    with pytest.raises(ValueError, match="DEMO_API_TOKEN"):
        config.Settings.from_env(load_dotenv_file=False)

    monkeypatch.setenv("DEMO_API_TOKEN", "short")
    monkeypatch.setenv("CORS_ORIGINS", "https://frontend.example")
    with pytest.raises(ValueError, match="32 characters"):
        config.Settings.from_env(load_dotenv_file=False)

    monkeypatch.setenv("DEMO_API_TOKEN", "x" * 32)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="wildcard CORS"):
        config.Settings.from_env(load_dotenv_file=False)


def test_public_demo_accepts_explicit_origins_and_rate_limit(monkeypatch):
    config = runtime_config
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("DEMO_API_TOKEN", "x" * 32)
    monkeypatch.setenv("CORS_ORIGINS", "https://frontend.example,http://localhost:5173")
    monkeypatch.setenv("MODEL_RATE_LIMIT_PER_MINUTE", "12")

    settings = config.Settings.from_env(load_dotenv_file=False)

    assert settings.public_demo is True
    assert settings.demo_api_token == "x" * 32
    assert settings.cors_origins == (
        "https://frontend.example",
        "http://localhost:5173",
    )
    assert settings.model_rate_limit_per_minute == 12


def test_settings_reject_region_outside_bedrock_resources(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")

    with pytest.raises(ValueError, match="AWS_REGION must be us-east-1"):
        runtime_config.Settings.from_env(load_dotenv_file=False)


@pytest.mark.parametrize("name", ["KB_ID", "ASK_MODEL_ID", "ONBOARDING_MODEL_ID"])
def test_settings_reject_empty_required_identifiers(monkeypatch, name):
    monkeypatch.setenv(name, "")

    with pytest.raises(ValueError, match=name):
        runtime_config.Settings.from_env(load_dotenv_file=False)


@pytest.mark.parametrize(
    "origin",
    [
        "https://frontend.example/path",
        "https://frontend.example?query=yes",
        "https://user:password@frontend.example",
        "ftp://frontend.example",
    ],
)
def test_public_demo_rejects_values_that_are_not_origins(monkeypatch, origin):
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("DEMO_API_TOKEN", "x" * 32)
    monkeypatch.setenv("CORS_ORIGINS", origin)

    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        runtime_config.Settings.from_env(load_dotenv_file=False)
