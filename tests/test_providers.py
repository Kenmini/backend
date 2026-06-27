import importlib
import importlib.util
import json
from dataclasses import replace

import pytest

from app.models import HistoryTurn
from config import Settings


def _providers():
    assert importlib.util.find_spec("app.providers") is not None
    return importlib.import_module("app.providers")


class FakeAgentRuntime:
    def __init__(self, score=0.9):
        self.score = score
        self.retrieve_calls = []
        self.generate_calls = []

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        return {
            "retrievalResults": [
                {
                    "score": self.score,
                    "content": {"text": "輝度つまみは右上です。"},
                    "location": {
                        "type": "S3",
                        "s3Location": {"uri": "s3://bedrock-docs/manual.pdf"},
                    },
                }
            ]
        }

    def retrieve_and_generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return {
            "output": {"text": "easy answer"},
            "citations": [
                {
                    "retrievedReferences": [
                        {
                            "content": {"text": "source text"},
                            "location": {
                                "type": "S3",
                                "s3Location": {"uri": "s3://bedrock-docs/manual.pdf"},
                            },
                        }
                    ]
                }
            ],
        }


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["modelId"].endswith("haiku"):
            text = "M1向けオンボーディングガイド"
        else:
            text = json.dumps(
                {
                    "answer_text": "パネル右上の輝度つまみです。",
                    "next_step_hint": "フォーカスを確認してください。",
                    "is_supported": True,
                },
                ensure_ascii=False,
            )
        return {
            "output": {"message": {"content": [{"text": text}]}},
            "ResponseMetadata": {"RequestId": "request-1"},
        }


class UnsupportedRuntime(FakeRuntime):
    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "answer_text": "資料には回答がありません。",
                                    "next_step_hint": "先生に確認してください。",
                                    "is_supported": False,
                                },
                                ensure_ascii=False,
                            )
                        }
                    ]
                }
            }
        }


def settings(**changes):
    base = Settings.from_env(load_dotenv_file=False)
    values = {
        "answer_path": "advanced",
        "ask_model_id": "test-sonnet",
        "onboarding_model_id": "test-haiku",
    }
    values.update(changes)
    return replace(base, **values)


def test_advanced_ask_uses_sonnet_structured_output_and_history():
    providers = _providers()
    agent = FakeAgentRuntime()
    runtime = FakeRuntime()
    provider = providers.BedrockAnswerProvider(settings(), agent, runtime)

    result = provider.ask(
        "つまみはどこ？", [HistoryTurn(user="前の質問", assistant="前の回答")]
    )

    assert result.answer_text == "パネル右上の輝度つまみです。"
    assert result.next_step_hint == "フォーカスを確認してください。"
    assert result.confidence == 0.9
    assert result.citations[0].source == "manual.pdf"
    call = runtime.calls[0]
    assert call["modelId"] == "test-sonnet"
    assert "outputConfig" in call
    assert call["messages"][0]["role"] == "user"
    assert call["messages"][1]["role"] == "assistant"


def test_gap_skips_converse():
    providers = _providers()
    runtime = FakeRuntime()
    provider = providers.BedrockAnswerProvider(
        settings(gap_threshold=0.4), FakeAgentRuntime(score=0.1), runtime
    )

    result = provider.ask("undocumented", [])

    assert result.is_gap is True
    assert result.citations == []
    assert runtime.calls == []


def test_high_score_but_unsupported_context_becomes_gap():
    providers = _providers()
    runtime = UnsupportedRuntime()
    provider = providers.BedrockAnswerProvider(settings(), FakeAgentRuntime(), runtime)

    result = provider.ask("研究室の安全ルール", [])

    assert result.is_gap is True
    assert result.answer_text == providers.prompts.GAP_MESSAGE
    assert result.next_step_hint is None
    assert result.citations == []
    assert result.confidence == 0.0


def test_onboarding_uses_haiku_without_history_or_output_schema():
    providers = _providers()
    runtime = FakeRuntime()
    provider = providers.BedrockAnswerProvider(settings(), FakeAgentRuntime(), runtime)

    guide = provider.onboarding("M1", "光学")

    assert guide == "M1向けオンボーディングガイド"
    call = runtime.calls[0]
    assert call["modelId"] == "test-haiku"
    assert "outputConfig" not in call
    assert len(call["messages"]) == 1


def test_onboarding_gap_returns_deterministic_guide():
    providers = _providers()
    runtime = FakeRuntime()
    provider = providers.BedrockAnswerProvider(
        settings(), FakeAgentRuntime(score=0.0), runtime
    )

    guide = provider.onboarding("D1", None)

    assert "資料がまだ登録されていません" in guide
    assert runtime.calls == []


def test_easy_path_remains_explicit_fallback():
    providers = _providers()
    agent = FakeAgentRuntime()
    provider = providers.BedrockAnswerProvider(
        settings(answer_path="easy"), agent, FakeRuntime()
    )

    result = provider.ask("question", [])

    assert result.answer_text == "easy answer"
    assert agent.generate_calls


def test_easy_path_rejects_an_empty_generated_answer():
    providers = _providers()
    agent = FakeAgentRuntime()
    agent.retrieve_and_generate = lambda **kwargs: {}
    provider = providers.BedrockAnswerProvider(
        settings(answer_path="easy"), agent, FakeRuntime()
    )

    with pytest.raises(ValueError, match="empty answer"):
        provider.ask("question", [])


def test_fixture_provider_has_known_answer_and_default_gap():
    providers = _providers()
    provider = providers.FixtureAnswerProvider()

    known = provider.ask("輝度つまみはどこですか？", [])
    unknown = provider.ask("completely unknown", [])

    assert known.is_gap is False
    assert known.citations
    assert unknown.is_gap is True
    assert "資料に記録" in unknown.answer_text
    assert "オンボーディング" in provider.onboarding("M1", "光学")


def test_fixture_provider_default_path_is_independent_of_working_directory(
    tmp_path, monkeypatch
):
    providers = _providers()
    monkeypatch.chdir(tmp_path)

    provider = providers.FixtureAnswerProvider()

    assert provider.ask("輝度つまみはどこですか？", []).is_gap is False
