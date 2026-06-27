import importlib
import importlib.util
import json
import logging
import subprocess
from dataclasses import replace
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
    assert '$env:GAP_THRESHOLD = "0.20"' in live_runner
    for script in (
        "run-demo.ps1",
        "run-live-advanced.ps1",
        "run-live-easy.ps1",
        "smoke.ps1",
        "smoke-live.ps1",
        "smoke-deep.ps1",
        "smoke-public.ps1",
        "start-public-demo.ps1",
        "backup.ps1",
        "restore.ps1",
        "preflight.ps1",
        "test.ps1",
    ):
        assert (root / "scripts" / script).is_file()


def test_deep_smoke_runner_covers_offline_operational_scenarios():
    root = Path(__file__).parents[1]
    runner = root / "scripts" / "deep_smoke.py"

    assert runner.is_file()
    content = runner.read_text(encoding="utf-8")
    for scenario in (
        "authentication",
        "strict_cors",
        "utf8_json",
        "validation_errors",
        "gap_deduplication",
        "concurrent_requests",
        "bounded_history",
        "rate_limit",
        "backup_restore",
    ):
        assert scenario in content
    assert 'bind(("127.0.0.1", 0))' in content


def test_public_launcher_requires_explicit_mode_origin_and_tokenized_smoke():
    root = Path(__file__).parents[1]
    launcher = root / "scripts" / "start-public-demo.ps1"
    smoke = root / "scripts" / "smoke-public.ps1"

    assert launcher.is_file()
    assert smoke.is_file()
    launcher_text = launcher.read_text(encoding="utf-8")
    smoke_text = smoke.read_text(encoding="utf-8")
    assert 'ValidateSet("demo", "live")' in launcher_text
    assert "Mandatory = $true" in launcher_text
    assert "FrontendOrigin" in launcher_text
    assert "cloudflared tunnel --url" in launcher_text
    assert "DEMO_API_TOKEN" in launcher_text
    assert "publicReady" in launcher_text
    assert "Resolve-DnsName" in launcher_text
    assert 'Invoke-WebRequest "$publicUrl/health"' in launcher_text
    assert "X-Demo-Token" in smoke_text
    assert "/openapi.json" in smoke_text
    assert '[bool]$health.Headers["X-Request-ID"]' in smoke_text
    assert "-contains $FrontendOrigin" in smoke_text
    assert "-notcontains $untrustedOrigin" in smoke_text
    assert 'throw "Public smoke tests failed."' not in launcher_text


def test_public_launcher_restores_caller_environment_on_failure():
    root = Path(__file__).parents[1]
    launcher = root / "scripts" / "start-public-demo.ps1"
    original = {
        "APP_MODE": "original-mode",
        "ANSWER_PATH": "original-path",
        "PUBLIC_DEMO": "original-public",
        "DEMO_API_TOKEN": "original-token",
        "CORS_ORIGINS": "original-origin",
        "STORAGE_MODE": "original-storage",
        "DATABASE_PATH": "original.db",
    }
    assignments = "; ".join(
        f"$env:{name}='{value}'" for name, value in original.items()
    )
    properties = ";".join(f"{name}=$env:{name}" for name in original)
    command = (
        f"{assignments}; "
        "function cloudflared { }; "
        "function Start-Process { throw 'synthetic start failure' }; "
        f"try {{ & '{launcher}' -Mode demo "
        "-FrontendOrigin http://localhost:5173 } catch { }; "
        f"[pscustomobject]@{{{properties}}} | ConvertTo-Json -Compress"
    )

    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert json.loads(completed.stdout.strip().splitlines()[-1]) == original


def test_public_launcher_rejects_a_url_path_before_starting_processes():
    root = Path(__file__).parents[1]
    launcher = root / "scripts" / "start-public-demo.ps1"
    command = (
        "function cloudflared { }; "
        "function Start-Process { throw 'process was started' }; "
        f"try {{ & '{launcher}' -Mode demo "
        "-FrontendOrigin https://frontend.example/path } "
        "catch { $_.Exception.Message }"
    )

    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.stdout.strip() == (
        "Invalid frontend origin: https://frontend.example/path"
    )


def test_runtime_scripts_restore_environment_and_propagate_native_failures():
    root = Path(__file__).parents[1]
    scripts = root / "scripts"
    environment_scripts = (
        "preflight.ps1",
        "run-demo.ps1",
        "run-live-advanced.ps1",
        "run-live-easy.ps1",
        "smoke.ps1",
        "smoke-live.ps1",
        "smoke-deep.ps1",
        "test.ps1",
    )
    for name in environment_scripts:
        content = (scripts / name).read_text(encoding="utf-8")
        assert "runtime-env.ps1" in content, name
        assert "Save-ProcessEnvironment" in content, name
        assert "Restore-ProcessEnvironment" in content, name

    for name in (
        "backup.ps1",
        "restore.ps1",
        "preflight.ps1",
        "run-demo.ps1",
        "run-live-advanced.ps1",
        "run-live-easy.ps1",
    ):
        content = (scripts / name).read_text(encoding="utf-8")
        assert "$LASTEXITCODE -ne 0" in content, name

    for name in ("run-demo.ps1", "run-live-advanced.ps1", "run-live-easy.ps1"):
        content = (scripts / name).read_text(encoding="utf-8")
        assert "Push-Location $root" in content, name
        assert "Pop-Location" in content, name


def test_windows_smoke_scripts_send_japanese_as_utf8_bytes():
    root = Path(__file__).parents[1]
    helper = (root / "scripts" / "runtime-env.ps1").read_text(encoding="utf-8")
    assert "[Text.Encoding]::UTF8.GetBytes" in helper
    for name in ("smoke.ps1", "smoke-live.ps1"):
        content = (root / "scripts" / name).read_text(encoding="utf-8")
        assert "ConvertTo-Utf8JsonBytes" in content, name


def test_powershell_utf8_json_helper_returns_one_byte_array():
    root = Path(__file__).parents[1]
    helper = root / "scripts" / "runtime-env.ps1"
    command = (
        f". '{helper}'; "
        "$bytes = ConvertTo-Utf8JsonBytes @{ message = '日本語' }; "
        "[pscustomobject]@{ Type = $bytes.GetType().FullName; "
        "Text = [Text.Encoding]::UTF8.GetString($bytes) } | ConvertTo-Json -Compress"
    )

    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout.strip())

    assert result["Type"] == "System.Byte[]"
    assert json.loads(result["Text"]) == {"message": "日本語"}


def test_presentation_diagrams_are_bilingual_and_theme_reproducible():
    root = Path(__file__).parents[1]
    presentation = root / "docs" / "presentation"
    expected = {
        "system-architecture.mmd",
        "answer-trust-flow.mmd",
        "temporary-hosting.mmd",
        "demo-contingency.mmd",
    }

    for language in ("en", "ja"):
        assert {
            path.name for path in (presentation / language).glob("*.mmd")
        } == expected
    for theme in ("light", "dark"):
        config = presentation / "themes" / f"{theme}.json"
        assert config.is_file()
        assert json.loads(config.read_text(encoding="utf-8"))["theme"] == "base"

    renderer = root / "scripts" / "render-presentation-charts.ps1"
    assert renderer.is_file()
    renderer_text = renderer.read_text(encoding="utf-8")
    assert "@mermaid-js/mermaid-cli@11.12.0" in renderer_text
    assert 'foreach ($language in @("en", "ja"))' in renderer_text
    assert 'foreach ($theme in @("light", "dark"))' in renderer_text
    assert '".svg", ".png"' in renderer_text
