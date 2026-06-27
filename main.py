"""FastAPI app. Routes follow the contract in API.md.

Run: uvicorn main:app --reload --port 8000   (then GET /health)
"""

import json
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

import bedrock
import figures
import gaps
import prompts

app = FastAPI(title="Lab Tacit-Knowledge AI Agent", version="0.1.0")


def json_response(data) -> Response:
    """UTF-8を明示したJSONレスポンスを返す。PowerShellなど一部クライアントの文字化けを防ぐ。"""
    content = json.dumps(data, ensure_ascii=False)
    return Response(content=content, media_type="application/json; charset=utf-8")

# Open CORS for the hackathon; restrict before any public deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    current_state: Optional[dict[str, Any]] = None


class Citation(BaseModel):
    source: str
    snippet: str


class VisualData(BaseModel):
    figure_id: Optional[str] = None
    highlight_item: Optional[str] = None


class AskResponse(BaseModel):
    answer_text: str
    next_step_hint: Optional[str] = None
    visual_data: Optional[VisualData] = None
    citations: list[Citation] = []
    confidence: float
    is_gap: bool


class GapItem(BaseModel):
    question: str
    count: int
    first_seen: str


class GapsResponse(BaseModel):
    gaps: list[GapItem]


class OnboardingRequest(BaseModel):
    role: str
    field: Optional[str] = None


class OnboardingResponse(BaseModel):
    guide: str


class FaqItem(BaseModel):
    q: str
    a: str


class FaqResponse(BaseModel):
    items: list[FaqItem]


class FeedbackRequest(BaseModel):
    session_id: str
    message: str
    rating: str
    note: Optional[str] = None


class FeedbackResponse(BaseModel):
    ok: bool


@app.get("/health")
def health():
    return json_response({"status": "ok"})


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    result = bedrock.answer(req.message)

    if result.get("is_gap"):
        gaps.log_gap(req.message)

    active_figure_id = None
    if req.current_state:
        active_figure_id = req.current_state.get("active_figure_id")
    active_figure_id = active_figure_id or figures.DEFAULT_FIGURE_ID
    highlight = figures.pick_highlight(active_figure_id, result["answer_text"])

    return AskResponse(
        answer_text=result["answer_text"],
        next_step_hint=None,
        visual_data=VisualData(figure_id=active_figure_id, highlight_item=highlight),
        citations=result.get("citations", []),
        confidence=result.get("confidence", 0.0),
        is_gap=result.get("is_gap", False),
    )


@app.get("/gaps", response_model=GapsResponse)
def get_gaps():
    return json_response({"gaps": gaps.list_gaps()})


@app.post("/onboarding", response_model=OnboardingResponse)
def onboarding(req: OnboardingRequest):
    field_line = f"研究分野: {req.field}" if req.field else ""
    prompt = prompts.ONBOARDING_TEMPLATE.format(role=req.role, field_line=field_line)
    return {"guide": bedrock.answer(prompt)["answer_text"]}


_FAQ_ITEMS = [
    {
        "q": "研究室のコアタイムは何時ですか？",
        "a": "コアタイムは研究室の資料を確認してください。記載がない場合は /ask で質問できます。",
    },
    {
        "q": "実験ノートはどこに保存しますか？",
        "a": "実験記録の保存場所は研究室の資料を参照してください。",
    },
]


@app.get("/faq", response_model=FaqResponse)
def faq():
    return json_response({"items": _FAQ_ITEMS})


_FEEDBACK_LOG: list[dict] = []


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest):
    _FEEDBACK_LOG.append(req.model_dump())
    return {"ok": True}
