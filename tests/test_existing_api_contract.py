from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_ready_endpoint_is_additive():
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "mode": "live",
        "database": "ok",
        "provider": "configured",
    }


def test_onboarding_rejects_unknown_role():
    response = client.post("/onboarding", json={"role": "professor"})

    assert response.status_code == 422


def test_feedback_rejects_unknown_rating():
    response = client.post(
        "/feedback",
        json={"session_id": "s1", "message": "answer", "rating": "sideways"},
    )

    assert response.status_code == 422


def test_ask_rejects_blank_message_before_calling_provider():
    response = client.post("/ask", json={"message": "   "})

    assert response.status_code == 422
