"""
main.py — FastAPI app for the Lab Tacit-Knowledge AI Agent backend.

Wires the API contract (see API.md) to the modules:
  bedrock.py  -> answering (easy/advanced paths)
  gaps.py     -> knowledge-gap store
  figures.py  -> constrained visual_data
  prompts.py  -> onboarding template
  config.py   -> central config

Run:   uvicorn main:app --reload --port 8000
Check: GET http://localhost:8000/health  ->  {"status": "ok"}
Docs:  http://localhost:8000/docs  (interactive Swagger UI, auto-generated)
"""

from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import bedrock
import figures
import gaps
import prompts

app = FastAPI(title="Lab Tacit-Knowledge AI Agent", version="0.1.0")

# CORS wide open for the hackathon so any frontend dev port can call us.
# TODO(security): restrict allow_origins to the real frontend origin before any
# public deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Pydantic models — one per request/response shape in the contract.
# ===========================================================================
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
    role: str  # "M1" | "D1"
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
    rating: str  # "up" | "down"
    note: Optional[str] = None


class FeedbackResponse(BaseModel):
    ok: bool


# ===========================================================================
# Routes
# ===========================================================================
@app.get("/health", response_model=dict)
def health():
    """Liveness check. Returns immediately — no AWS calls."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """
    Main RAG endpoint. Retrieves from the Knowledge Base, answers grounded in
    lab documents, and runs gap detection (the signature feature).
    """
    # TODO(advanced): look up converse history by req.session_id and pass it to
    # bedrock.answer() so the ADVANCED path has per-session memory.
    result = bedrock.answer(req.message)

    # Signature feature: if this was a knowledge gap, log it for the professor.
    if result.get("is_gap"):
        gaps.log_gap(req.message)

    # Build visual_data, constrained to a known figure's hotspots (figures.py).
    active_figure_id = None
    if req.current_state:
        active_figure_id = req.current_state.get("active_figure_id")
    active_figure_id = active_figure_id or figures.DEFAULT_FIGURE_ID
    highlight = figures.pick_highlight(active_figure_id, result["answer_text"])
    visual_data = VisualData(figure_id=active_figure_id, highlight_item=highlight)

    # TODO(advanced): generate next_step_hint from the model (structured output
    # in answer_advanced). Left null on the easy path for now.
    return AskResponse(
        answer_text=result["answer_text"],
        next_step_hint=None,
        visual_data=visual_data,
        citations=result.get("citations", []),
        confidence=result.get("confidence", 0.0),
        is_gap=result.get("is_gap", False),
    )


@app.get("/gaps", response_model=GapsResponse)
def get_gaps():
    """List detected knowledge gaps for professor review, most-asked first."""
    return {"gaps": gaps.list_gaps()}


@app.post("/onboarding", response_model=OnboardingResponse)
def onboarding(req: OnboardingRequest):
    """
    Generate a role-specific onboarding guide grounded in lab documents.
    Builds a prompt from the onboarding template and runs it through the same
    RAG pipeline so the guide is based on real lab material.
    """
    field_line = f"研究分野: {req.field}" if req.field else ""
    prompt = prompts.ONBOARDING_TEMPLATE.format(role=req.role, field_line=field_line)
    result = bedrock.answer(prompt)
    return {"guide": result["answer_text"]}


# In-memory FAQ for the MVP.
# TODO: generate these from the most-upvoted answers / most-common questions.
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
    """Return a small set of frequently asked questions and answers."""
    return {"items": _FAQ_ITEMS}


# In-memory feedback log for the MVP.
# TODO: persist feedback (e.g. DynamoDB) and use it to improve answers / FAQ.
_FEEDBACK_LOG: list[dict] = []


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest):
    """Record a thumbs up/down on an answer."""
    _FEEDBACK_LOG.append(req.model_dump())
    return {"ok": True}
