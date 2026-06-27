import logging
import secrets
import time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

import figures
from app.providers import AnswerProvider, BedrockAnswerProvider, FixtureAnswerProvider
from app.repositories import MemoryRepository, Repository, SQLiteRepository
from app.security import SlidingWindowRateLimiter
from app.services import KnowledgeService
from config import Settings

logger = logging.getLogger(__name__)


class CurrentState(BaseModel):
    active_figure_id: (
        Literal["panel_01", "microscope_overview", "control_panel"] | None
    ) = None


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    current_state: CurrentState | None = None


class CitationResponse(BaseModel):
    source: str
    snippet: str


class VisualData(BaseModel):
    figure_id: str | None = None
    highlight_item: str | None = None


class AskResponse(BaseModel):
    answer_text: str
    next_step_hint: str | None
    visual_data: VisualData | None
    citations: list[CitationResponse]
    confidence: float
    is_gap: bool


class GapResponse(BaseModel):
    question: str
    count: int
    first_seen: str


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    role: Literal["M1", "D1"]
    field: str | None = Field(default=None, min_length=1, max_length=200)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    rating: Literal["up", "down"]
    note: str | None = Field(default=None, min_length=1, max_length=1000)


FAQ_ITEMS = [
    {
        "q": "研究室のコアタイムは何時ですか？",
        "a": (
            "コアタイムは研究室の資料を確認してください。"
            "記載がない場合は /ask で質問できます。"
        ),
    },
    {
        "q": "実験ノートはどこに保存しますか？",
        "a": "実験記録の保存場所は研究室の資料を参照してください。",
    },
]


def create_repository(settings: Settings) -> Repository:
    if settings.storage_mode == "memory":
        return MemoryRepository(settings.history_limit)
    return SQLiteRepository(
        settings.database_path,
        settings.history_limit,
        legacy_gaps_path=settings.gaps_file,
    )


def create_provider(settings: Settings) -> AnswerProvider:
    if settings.app_mode == "demo":
        return FixtureAnswerProvider()
    return BedrockAnswerProvider(settings)


def create_app(
    *,
    settings: Settings,
    provider: AnswerProvider | None = None,
    repository: Repository | None = None,
) -> FastAPI:
    provider = provider or create_provider(settings)
    repository = repository or create_repository(settings)
    service = KnowledgeService(provider, repository)
    app = FastAPI(
        title="Lab Tacit-Knowledge AI Agent",
        version="0.2.0",
        docs_url=None if settings.public_demo else "/docs",
        redoc_url=None if settings.public_demo else "/redoc",
        openapi_url=None if settings.public_demo else "/openapi.json",
    )
    app.state.settings = settings
    app.state.provider = provider
    app.state.repository = repository

    limiter = SlidingWindowRateLimiter(settings.model_rate_limit_per_minute)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started = time.perf_counter()
        path = request.url.path
        response: Response
        if settings.public_demo and path in {"/docs", "/redoc", "/openapi.json"}:
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
        elif (
            settings.public_demo
            and path != "/health"
            and request.method != "OPTIONS"
            and not secrets.compare_digest(
                request.headers.get("X-Demo-Token", ""),
                settings.demo_api_token or "",
            )
        ):
            response = JSONResponse(
                {"detail": "Invalid or missing demo token"},
                status_code=401,
                headers={"WWW-Authenticate": "DemoToken"},
            )
        elif settings.public_demo and path in {"/ask", "/onboarding"}:
            client_ip = request.headers.get("CF-Connecting-IP")
            if not client_ip:
                client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = limiter.check(client_ip)
            if allowed:
                response = await call_next(request)
            else:
                response = JSONResponse(
                    {"detail": "Model request rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        content_type = response.headers.get("content-type", "")
        if content_type.lower() == "application/json":
            response.headers["content-type"] = "application/json; charset=utf-8"
        logger.info(
            "request_complete",
            extra={
                "request_id": request_id,
                "route": request.url.path,
                "status_code": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "mode": settings.app_mode,
                "provider": provider.name,
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"] if settings.public_demo else ["*"],
        allow_headers=(
            ["Content-Type", "X-Demo-Token", "X-Request-ID"]
            if settings.public_demo
            else ["*"]
        ),
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            database = "ok" if repository.is_ready() else "error"
        except Exception:
            logger.exception("readiness_database_check_failed")
            database = "error"
        try:
            provider_status = "configured" if provider.configured() else "misconfigured"
        except Exception:
            logger.exception("readiness_provider_check_failed")
            provider_status = "misconfigured"
        status = (
            "ready"
            if database == "ok" and provider_status == "configured"
            else "degraded"
        )
        return {
            "status": status,
            "mode": settings.app_mode,
            "database": database,
            "provider": provider_status,
        }

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest):
        result = service.ask(request.message, request.session_id)
        figure_id = figures.DEFAULT_FIGURE_ID
        if request.current_state and request.current_state.active_figure_id:
            figure_id = request.current_state.active_figure_id
        return AskResponse(
            answer_text=result.answer_text,
            next_step_hint=result.next_step_hint,
            visual_data=VisualData(
                figure_id=figure_id,
                highlight_item=figures.pick_highlight(figure_id, result.answer_text),
            ),
            citations=[CitationResponse(**vars(item)) for item in result.citations],
            confidence=result.confidence,
            is_gap=result.is_gap,
        )

    @app.get("/gaps")
    def gaps():
        try:
            return {
                "gaps": [
                    GapResponse(
                        question=item.question,
                        count=item.count,
                        first_seen=item.first_seen,
                    )
                    for item in repository.list_gaps()
                ]
            }
        except Exception as exc:
            raise HTTPException(
                503, "Knowledge gaps are temporarily unavailable"
            ) from exc

    @app.post("/onboarding")
    def onboarding(request: OnboardingRequest):
        return {"guide": service.onboarding(request.role, request.field)}

    @app.get("/faq")
    def faq():
        return {"items": FAQ_ITEMS}

    @app.post("/feedback")
    def feedback(request: FeedbackRequest):
        try:
            repository.save_feedback(
                request.session_id, request.message, request.rating, request.note
            )
        except Exception as exc:
            raise HTTPException(503, "Feedback could not be recorded") from exc
        return {"ok": True}

    return app
