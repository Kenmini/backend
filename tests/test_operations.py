from dataclasses import replace
import importlib
import importlib.util
import json
import logging
from pathlib import Path

import pytest

from config import Settings


def _module(name):
    assert importlib.util.find_spec(name) is not None
    return importlib.import_module(name)


class FakeSts:
    def get_caller_identity(self):
        return {"Account": "465239007752", "Arn": "arn:aws:iam::465239007752:user/test"}


class FakeAgent:
    def retrieve(self, **kwargs):
        return {"retrievalResults": [{"score": 0.8, "content": {"text": "doc"}}]}


class EmptyAgent:
    def retrieve(self, **kwargs):
        return {"retrievalResults": []}


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["modelId"] == "preflight-sonnet":
            text = json.dumps({"answer_text": "ok", "next_step_hint": None})
        else:
            text = "ok"
        return {"output": {"message": {"content": [{"text": text}]}}}


def test_live_preflight_checks_account_retrieval_and_both_models():
    preflight = _module("app.preflight")
    settings = replace(
        Settings.from_env(load_dotenv_file=False),
        aws_account_id="465239007752",
        ask_model_id="preflight-sonnet",
        onboarding_model_id="preflight-haiku",
    )
    runtime = FakeRuntime()

    result = preflight.run_preflight(
        settings, sts=FakeSts(), agent_runtime=FakeAgent(), runtime=runtime
    )

    assert result["status"] == "ok"
    assert result["retrieval_results"] == 1
    assert [call["modelId"] for call in runtime.calls] == [
        "preflight-sonnet",
        "preflight-haiku",
    ]
    assert "outputConfig" in runtime.calls[0]
    assert "outputConfig" not in runtime.calls[1]


def test_live_preflight_rejects_wrong_aws_account():
    preflight = _module("app.preflight")
    settings = replace(
        Settings.from_env(load_dotenv_file=False), aws_account_id="different"
    )

    with pytest.raises(RuntimeError, match="AWS account"):
        preflight.run_preflight(
            settings, sts=FakeSts(), agent_runtime=FakeAgent(), runtime=FakeRuntime()
        )


def test_live_preflight_checks_models_before_reporting_empty_retrieval():
    preflight = _module("app.preflight")
    settings = replace(
        Settings.from_env(load_dotenv_file=False),
        aws_account_id="465239007752",
        ask_model_id="preflight-sonnet",
        onboarding_model_id="preflight-haiku",
    )
    runtime = FakeRuntime()

    with pytest.raises(RuntimeError, match="no documents"):
        preflight.run_preflight(
            settings, sts=FakeSts(), agent_runtime=EmptyAgent(), runtime=runtime
        )

    assert [call["modelId"] for call in runtime.calls] == [
        "preflight-sonnet",
        "preflight-haiku",
    ]


def test_json_formatter_emits_operational_fields_without_prompt_data():
    observability = _module("app.observability")
    formatter = observability.JsonFormatter()
    record = logging.LogRecord(
        "api",
        logging.INFO,
        __file__,
        1,
        "request_complete",
        (),
        None,
    )
    record.request_id = "request-1"
    record.route = "/ask"
    record.status_code = 200
    record.latency_ms = 12.5
    record.mode = "live"
    record.provider = "bedrock"

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "request_complete"
    assert payload["request_id"] == "request-1"
    assert payload["route"] == "/ask"
    assert "prompt" not in payload
    assert "history" not in payload


def test_chart_sources_and_windows_scripts_are_reproducible():
    root = Path(__file__).parents[1]
    expected = {
        "system-components.mmd",
        "ask-sequence.mmd",
        "model-routing.mmd",
        "contingency-flow.mmd",
        "backup-restore.mmd",
    }
    chart_dir = root / "docs" / "architecture"

    assert {path.name for path in chart_dir.glob("*.mmd")} == expected
    renderer = (root / "scripts" / "render-charts.ps1").read_text(encoding="utf-8")
    assert "@mermaid-js/mermaid-cli@" in renderer
    assert "images/charts" in (root / ".gitignore").read_text(encoding="utf-8")
    live_runner = (root / "scripts" / "run-live-advanced.ps1").read_text(
        encoding="utf-8"
    )
    assert '$env:GAP_THRESHOLD = "0.79"' in live_runner
    for script in (
        "run-demo.ps1",
        "run-live-advanced.ps1",
        "run-live-easy.ps1",
        "smoke.ps1",
        "smoke-live.ps1",
        "backup.ps1",
        "restore.ps1",
        "preflight.ps1",
        "test.ps1",
    ):
        assert (root / "scripts" / script).is_file()
