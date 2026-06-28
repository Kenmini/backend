import importlib
import importlib.util
from dataclasses import replace

from fastapi.testclient import TestClient

from app.models import AnswerResult, Citation, VisualReference
from app.repositories import MemoryRepository
from app.visuals import RenderedVisual
from config import Settings


def _api():
    assert importlib.util.find_spec("app.api") is not None
    return importlib.import_module("app.api")


class FakeProvider:
    name = "fake"

    def __init__(self, *, gap=False, fail=False, visual=False):
        self.gap = gap
        self.fail = fail
        self.visual = visual
        self.ask_calls = []
        self.onboarding_calls = []

    def configured(self):
        return True

    def ask(self, message, history):
        self.ask_calls.append((message, history))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return AnswerResult(
            answer_text="輝度つまみを確認してください。",
            next_step_hint="フォーカスを確認してください。",
            citations=[Citation("manual.pdf", "source")],
            confidence=0.8,
            is_gap=self.gap,
            visual_reference=(
                VisualReference(
                    source_uri="s3://lab-docs/manual.pdf",
                    source="manual.pdf",
                    page_number=3,
                    caption="試料ホルダーの挿入方法",
                    score=0.8,
                )
                if self.visual and not self.gap
                else None
            ),
        )

    def onboarding(self, role, field):
        self.onboarding_calls.append((role, field))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return f"{role} onboarding"


class BrokenRepository(MemoryRepository):
    def list_gaps(self):
        raise OSError("database unavailable")

    def save_feedback(self, session_id, message, rating, note):
        raise OSError("database unavailable")


class UnreadyRepository(MemoryRepository):
    def is_ready(self):
        raise OSError("database unavailable")


class FakeVisualRenderer:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def render(self, reference):
        self.calls.append(reference)
        if self.fail:
            raise RuntimeError("render failed")
        return RenderedVisual(
            image_url="data:image/jpeg;base64,/9j/",
            source=reference.source,
            page_number=reference.page_number,
            caption=reference.caption,
        )


def client(provider=None, repository=None, visual_renderer=None):
    api = _api()
    settings = replace(
        Settings.from_env(load_dotenv_file=False),
        app_mode="demo",
        storage_mode="memory",
    )
    return TestClient(
        api.create_app(
            settings=settings,
            provider=provider or FakeProvider(),
            repository=repository or MemoryRepository(history_limit=10),
            visual_renderer=visual_renderer,
        )
    )


def public_client(provider=None, repository=None, *, rate_limit=2):
    api = _api()
    settings = replace(
        Settings.from_env(load_dotenv_file=False),
        app_mode="demo",
        storage_mode="memory",
        public_demo=True,
        demo_api_token="t" * 32,
        model_rate_limit_per_minute=rate_limit,
        cors_origins=("https://frontend.example",),
    )
    return TestClient(
        api.create_app(
            settings=settings,
            provider=provider or FakeProvider(),
            repository=repository or MemoryRepository(history_limit=10),
        )
    )


def test_health_readiness_and_request_id():
    response = client().get("/ready", headers={"X-Request-ID": "known-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "known-id"
    assert response.json() == {
        "status": "ready",
        "mode": "demo",
        "database": "ok",
        "provider": "configured",
    }
    assert client().get("/health").json() == {"status": "ok"}


def test_readiness_reports_degraded_when_repository_check_raises():
    response = client(repository=UnreadyRepository(history_limit=10)).get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "error"


def test_ask_returns_contract_and_passes_session_history():
    provider = FakeProvider()
    test_client = client(provider=provider)
    payload = {
        "message": "輝度つまみはどこですか？",
        "session_id": "s1",
        "current_state": {"active_figure_id": "panel_01"},
    }

    first = test_client.post("/ask", json=payload)
    second = test_client.post("/ask", json=payload)

    assert first.status_code == 200
    assert first.json()["next_step_hint"] == "フォーカスを確認してください。"
    assert first.json()["visual_data"]["highlight_item"] == "輝度つまみ"
    assert provider.ask_calls[0][1] == []
    assert provider.ask_calls[1][1][0].assistant == "輝度つまみを確認してください。"
    assert second.status_code == 200


def test_ask_returns_rendered_pdf_page_visual():
    renderer = FakeVisualRenderer()
    response = client(
        provider=FakeProvider(visual=True), visual_renderer=renderer
    ).post("/ask", json={"message": "試料ホルダーはどこですか？"})

    assert response.status_code == 200
    visual = response.json()["visual_data"]
    # Base64 page rendering is disabled; image_url is always None now.
    # Static images would be returned if a static_image_renderer was provided.
    assert visual["image_url"] is None
    assert visual["source"] == "manual.pdf"
    assert visual["page_number"] == 3
    assert visual["caption"] == "試料ホルダーの挿入方法"
    assert visual["static_images"] == []


def test_visual_render_failure_keeps_safe_answer_contract():
    response = client(
        provider=FakeProvider(visual=True),
        visual_renderer=FakeVisualRenderer(fail=True),
    ).post("/ask", json={"message": "試料ホルダーはどこですか？"})

    assert response.status_code == 200
    assert response.json()["answer_text"] == "輝度つまみを確認してください。"
    assert response.json()["visual_data"]["image_url"] is None


def test_gap_is_persisted_and_listed():
    repo = MemoryRepository(history_limit=10)
    test_client = client(provider=FakeProvider(gap=True), repository=repo)

    response = test_client.post("/ask", json={"message": "unknown"})
    gaps = test_client.get("/gaps")

    assert response.json()["is_gap"] is True
    assert gaps.json()["gaps"][0]["question"] == "unknown"


def test_provider_failure_returns_safe_ask_and_onboarding_responses():
    test_client = client(provider=FakeProvider(fail=True))

    ask = test_client.post("/ask", json={"message": "question"})
    onboarding = test_client.post("/onboarding", json={"role": "M1"})

    assert ask.status_code == 200
    assert ask.json()["confidence"] == 0.0
    assert "接続できません" in ask.json()["answer_text"]
    assert onboarding.status_code == 200
    assert "接続できません" in onboarding.json()["guide"]


def test_feedback_and_gaps_return_503_on_storage_failure():
    test_client = client(repository=BrokenRepository(history_limit=10))

    feedback = test_client.post(
        "/feedback",
        json={"session_id": "s1", "message": "answer", "rating": "up"},
    )
    gaps = test_client.get("/gaps")

    assert feedback.status_code == 503
    assert gaps.status_code == 503


def test_validation_rejects_invalid_inputs_and_unknown_figure():
    test_client = client()

    assert test_client.post("/ask", json={"message": "   "}).status_code == 422
    assert (
        test_client.post(
            "/ask",
            json={
                "message": "question",
                "current_state": {"active_figure_id": "made-up"},
            },
        ).status_code
        == 422
    )
    assert test_client.post("/onboarding", json={"role": "M2"}).status_code == 422
    assert (
        test_client.post(
            "/feedback",
            json={"session_id": "s1", "message": "a", "rating": "sideways"},
        ).status_code
        == 422
    )


def test_faq_is_static_and_does_not_call_provider():
    provider = FakeProvider()

    response = client(provider=provider).get("/faq")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert "研究室" in response.content.decode("utf-8")
    assert response.json()["items"]
    assert provider.ask_calls == []
    assert provider.onboarding_calls == []


def test_public_demo_requires_token_but_keeps_health_public():
    test_client = public_client()

    assert test_client.get("/health").status_code == 200
    assert test_client.get("/ready").status_code == 401
    assert (
        test_client.get("/ready", headers={"X-Demo-Token": "wrong"}).status_code == 401
    )
    assert (
        test_client.get("/ready", headers={"X-Demo-Token": "t" * 32}).status_code == 200
    )


def test_public_demo_hides_docs_and_applies_strict_cors():
    test_client = public_client()

    assert test_client.get("/docs").status_code == 404
    assert test_client.get("/redoc").status_code == 404
    assert test_client.get("/openapi.json").status_code == 404

    allowed = test_client.options(
        "/ask",
        headers={
            "Origin": "https://frontend.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-demo-token,content-type",
        },
    )
    denied = test_client.options(
        "/ask",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://frontend.example"
    assert "access-control-allow-origin" not in denied.headers


def test_public_demo_rate_limits_model_routes_per_client():
    provider = FakeProvider()
    test_client = public_client(provider=provider, rate_limit=2)
    headers = {"X-Demo-Token": "t" * 32, "CF-Connecting-IP": "203.0.113.10"}

    first = test_client.post("/ask", json={"message": "one"}, headers=headers)
    second = test_client.post("/ask", json={"message": "two"}, headers=headers)
    limited = test_client.post("/ask", json={"message": "three"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert len(provider.ask_calls) == 2
