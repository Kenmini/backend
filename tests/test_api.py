from dataclasses import replace
import importlib
import importlib.util

from fastapi.testclient import TestClient

from app.models import AnswerResult, Citation
from app.repositories import MemoryRepository
from config import Settings


def _api():
    assert importlib.util.find_spec("app.api") is not None
    return importlib.import_module("app.api")


class FakeProvider:
    name = "fake"

    def __init__(self, *, gap=False, fail=False):
        self.gap = gap
        self.fail = fail
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


def client(provider=None, repository=None):
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
    assert response.json()["items"]
    assert provider.ask_calls == []
    assert provider.onboarding_calls == []
