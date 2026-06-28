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
from app.static_visuals import (
    S3StaticImageRenderer,
    StaticImageRenderer,
    keyword_relevant_indices as _keyword_relevant_indices,
)
from app.visuals import PdfPageRenderer, S3PdfPageRenderer
from config import Settings

logger = logging.getLogger(__name__)

# Equipment-manual pages that have a curated, rendered full-page figure stored
# under the S3 "figures/" prefix. Used as image candidates (still subject to the
# relevance gate before being shown).
MANUAL_FIGURE_PAGES = frozenset({2, 3, 6, 8, 13, 17, 19})


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


class StaticImageResponse(BaseModel):
    image_url: str
    filename: str
    name: str
    description: str
    page_number: int
    highlights: dict = {}


class VisualData(BaseModel):
    figure_id: str | None = None
    highlight_item: str | None = None
    image_url: str | None = None
    source: str | None = None
    page_number: int | None = None
    caption: str | None = None
    static_images: list[StaticImageResponse] = []
    pdf_url: str | None = None  # Presigned link to original PDF (fallback)


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
    visual_renderer: PdfPageRenderer | None = None,
    static_image_renderer: StaticImageRenderer | None = None,
) -> FastAPI:
    provider = provider or create_provider(settings)
    repository = repository or create_repository(settings)
    # Base64 page rendering is disabled — static images are used instead.
    # Keep visual_renderer=None unless explicitly passed for backwards compat.
    if (
        visual_renderer is None
        and settings.visuals_enabled
        and settings.app_mode == "live"
    ):
        # Previously: visual_renderer = S3PdfPageRenderer(settings)
        # Now disabled in favour of static images.
        visual_renderer = None
    # Static image renderer
    if (
        static_image_renderer is None
        and settings.visuals_enabled
        and settings.app_mode == "live"
    ):
        static_image_renderer = S3StaticImageRenderer(settings)
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
    app.state.visual_renderer = visual_renderer
    app.state.static_image_renderer = static_image_renderer

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
        figure_id = result.figure_id
        if not figure_id:
            figure_id = figures.DEFAULT_FIGURE_ID
            if request.current_state and request.current_state.active_figure_id:
                figure_id = request.current_state.active_figure_id

        # Static image lookup (replaces base64 page rendering)
        static_images_response: list[StaticImageResponse] = []
        source_name: str | None = None
        page_num: int | None = None
        caption: str | None = None
        pdf_url: str | None = None

        # Build candidate images for the page the top retrieval result landed on.
        # Each candidate carries a (name, description) used by the relevance gate.
        candidate_images: list[StaticImageResponse] = []
        candidate_descriptions: list[str] = []

        if static_image_renderer is not None and result.visual_reference is not None:
            vref = result.visual_reference
            source_name = vref.source
            page_num = vref.page_number
            caption = vref.caption
            # Pages with a curated full-page manual figure rendered under figures/
            is_manual = "hf2000" in vref.source.lower() or vref.source.lower().endswith(".docx")
            if is_manual and vref.page_number in MANUAL_FIGURE_PAGES:
                from urllib.parse import unquote, urlsplit

                parsed = urlsplit(vref.source_uri)
                key = unquote(parsed.path.lstrip("/"))
                s3_image_key = (
                    f"figures/{key.replace('/', '_')}"
                    f"_page_{vref.page_number:04d}.png"
                )
                try:
                    url = static_image_renderer.s3.generate_presigned_url(
                        "get_object",
                        Params={
                            "Bucket": static_image_renderer.bucket,
                            "Key": s3_image_key,
                        },
                        ExpiresIn=3600,
                    )
                    candidate_images = [
                        StaticImageResponse(
                            image_url=url,
                            filename=s3_image_key.split("/")[-1],
                            name="マニュアルの図",
                            description="Reference Page",
                            page_number=vref.page_number,
                            highlights={},
                        )
                    ]
                    # No real metadata for a full-page figure, so describe it by
                    # the retrieved chunk text — that's what the page is about.
                    candidate_descriptions = [vref.caption or ""]
                except Exception:
                    logger.exception("figures_static_image_lookup_failed")
            else:
                try:
                    static_result = static_image_renderer.render(vref)
                    if static_result:
                        candidate_images = [
                            StaticImageResponse(
                                image_url=img.image_url,
                                filename=img.filename,
                                name=img.name,
                                description=img.description,
                                page_number=img.page_number,
                                highlights=img.highlights,
                            )
                            for img in static_result.images
                        ]
                        candidate_descriptions = [
                            f"{img.name} — {img.description}"
                            for img in static_result.images
                        ]
                        source_name = static_result.source
                        page_num = static_result.page_number
                        caption = static_result.caption
                        pdf_url = static_result.pdf_url
                except Exception:
                    logger.exception(
                        "static_image_lookup_failed",
                        extra={
                            "source": vref.source,
                            "page_number": vref.page_number,
                        },
                    )

        # Relevance gate: ask the smart model which candidate images (if any)
        # genuinely illustrate THIS answer. This is the single authoritative
        # check — it rejects an equipment-manual figure on a lab-location
        # answer, a "computer resources" image on a phone-number answer, etc.
        # Falls back to keyword scoring only if the model can't decide or the
        # provider doesn't support the gate (demo/tests).
        if candidate_images:
            selected = None
            selector = getattr(provider, "select_relevant_visuals", None)
            if selector is not None:
                try:
                    picked = selector(
                        request.message,
                        result.answer_text,
                        list(zip(
                            (img.name for img in candidate_images),
                            candidate_descriptions,
                        )),
                    )
                except Exception:
                    logger.exception("visual_relevance_gate_failed")
                    picked = None
                if picked is not None:
                    selected = [candidate_images[i] for i in picked]
            if selected is None:
                query = f"{request.message} {result.answer_text}"
                keep = set(
                    _keyword_relevant_indices(
                        query, candidate_descriptions, settings.visual_relevance_min
                    )
                )
                selected = [
                    img for i, img in enumerate(candidate_images) if i in keep
                ]
            static_images_response = selected

        # If no static result at all, still populate metadata from the reference
        if source_name is None and result.visual_reference is not None:
            source_name = result.visual_reference.source
            page_num = result.visual_reference.page_number
            caption = result.visual_reference.caption

        # Decide what visual to surface. figure_id/highlight_item metadata is
        # always passed through; it never renders a page image on its own.
        #  - relevant static images found → show the image card
        #  - otherwise, if we have a source page → show the collapsed
        #    "click to view PDF" fallback so the user can still see the source
        #    page the answer came from (no relevant diagram exists for it)
        #  - no source page at all → show nothing
        # We intentionally keep the PDF fallback even when a page had images
        # that the relevance gate rejected: the source page is still useful and
        # the frontend shows it collapsed, so it is low-noise.

        visual_data_response = VisualData(
            figure_id=figure_id,
            highlight_item=figures.pick_highlight(figure_id, result.answer_text),
            image_url=None,  # base64 page rendering disabled
            source=source_name,
            page_number=page_num,
            caption=caption,
            static_images=static_images_response,
            pdf_url=pdf_url,
        )

        return AskResponse(
            answer_text=result.answer_text,
            next_step_hint=result.next_step_hint,
            visual_data=visual_data_response,
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

    @app.get("/visual/page")
    def visual_page(source: str, page: int):
        """Render a single PDF page from S3 as a JPEG image.

        This endpoint is called on-demand when the frontend needs to show
        a PDF page that has no pre-extracted static images.

        Query params:
            source: The S3 key of the PDF (e.g., "Onboarding Manual_20260306_anonymized.pdf")
            page: One-based page number
        """
        if page < 1:
            raise HTTPException(400, "Page number must be at least 1")
        if not source:
            raise HTTPException(400, "Source is required")

        from app.visuals import S3PdfPageRenderer, VisualRenderError

        # Reuse or create a page renderer with a higher size limit for on-demand use
        page_renderer = getattr(app.state, "_page_renderer", None)
        if page_renderer is None:
            page_renderer = S3PdfPageRenderer(
                settings,
                max_pdf_bytes=50 * 1024 * 1024,  # 50 MiB for on-demand rendering
            )
            app.state._page_renderer = page_renderer

        source_uri = f"s3://{settings.s3_bucket}/{source}"
        try:
            image_bytes = page_renderer._render_page_bytes(source_uri, page)
        except VisualRenderError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception:
            logger.exception("visual_page_render_failed")
            raise HTTPException(500, "Failed to render PDF page")

        return Response(
            content=image_bytes,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Disposition": f'inline; filename="page_{page}.jpg"',
            },
        )

    return app
