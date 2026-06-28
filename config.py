"""Validated runtime configuration with compatibility aliases."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def _env(name: str, default: str, *aliases: str) -> str:
    if name in os.environ:
        return os.environ[name]
    for alias in aliases:
        if alias in os.environ:
            return os.environ[alias]
    return default


def _choice(name: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        values = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {values}")
    return value


def _bounded_float(name: str, value: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1")
    return parsed


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _required(name: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _validate_origin(origin: str) -> None:
    try:
        parsed = urlsplit(origin)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"CORS_ORIGINS contains an invalid origin: {origin}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"CORS_ORIGINS contains an invalid origin: {origin}")


@dataclass(frozen=True)
class Settings:
    app_mode: str
    answer_path: str
    storage_mode: str
    aws_account_id: str
    region: str
    kb_id: str
    ask_model_id: str
    onboarding_model_id: str
    rag_model_arn: str
    gap_threshold: float
    num_results: int
    history_limit: int
    database_path: Path
    gaps_file: Path
    aws_connect_timeout: int
    aws_read_timeout: int
    aws_max_attempts: int
    ask_max_tokens: int
    onboarding_max_tokens: int
    model_temperature: float
    cors_origins: tuple[str, ...]
    public_demo: bool
    demo_api_token: str | None
    model_rate_limit_per_minute: int
    # S3 / Rekognition 用設定
    aws_region: str
    s3_bucket: str
    pdf_s3_key: str

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True) -> "Settings":
        if load_dotenv_file:
            load_dotenv()

        region = _required("AWS_REGION", _env("AWS_REGION", "us-east-1"))
        if region != "us-east-1":
            raise ValueError(
                "AWS_REGION must be us-east-1 for the configured resources"
            )
        account_id = _required("AWS_ACCOUNT_ID", _env("AWS_ACCOUNT_ID", "465239007752"))
        default_rag_arn = (
            f"arn:aws:bedrock:{region}::foundation-model/anthropic.claude-sonnet-4-6"
        )
        origins = tuple(
            item.strip()
            for item in _env("CORS_ORIGINS", "*").split(",")
            if item.strip()
        )
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        public_demo = _boolean("PUBLIC_DEMO", _env("PUBLIC_DEMO", "false"))
        demo_api_token = _env("DEMO_API_TOKEN", "").strip() or None
        if public_demo:
            if demo_api_token is None:
                raise ValueError("DEMO_API_TOKEN is required in public-demo mode")
            if len(demo_api_token) < 32:
                raise ValueError("DEMO_API_TOKEN must be at least 32 characters")
            if "*" in origins:
                raise ValueError("PUBLIC_DEMO does not allow wildcard CORS origins")
            for origin in origins:
                _validate_origin(origin)

        return cls(
            app_mode=_choice("APP_MODE", _env("APP_MODE", "live"), {"live", "demo"}),
            answer_path=_choice(
                "ANSWER_PATH",
                _env("ANSWER_PATH", "advanced"),
                {"advanced", "easy"},
            ),
            storage_mode=_choice(
                "STORAGE_MODE",
                _env("STORAGE_MODE", "sqlite"),
                {"sqlite", "memory"},
            ),
            aws_account_id=account_id,
            region=region,
            kb_id=_required("KB_ID", _env("KB_ID", "AJVVEPYMSH")),
            ask_model_id=_required(
                "ASK_MODEL_ID",
                _env(
                    "ASK_MODEL_ID",
                    "us.anthropic.claude-sonnet-4-6",
                    "MODEL_SMART",
                ),
            ),
            onboarding_model_id=_required(
                "ONBOARDING_MODEL_ID",
                _env(
                    "ONBOARDING_MODEL_ID",
                    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    "MODEL_FAST",
                ),
            ),
            rag_model_arn=_required(
                "RAG_MODEL_ARN",
                _env("RAG_MODEL_ARN", default_rag_arn, "MODEL_SMART_ARN"),
            ),
            gap_threshold=_bounded_float(
                "GAP_THRESHOLD", _env("GAP_THRESHOLD", "0.20"), 0.0, 1.0
            ),
            num_results=_positive_int("NUM_RESULTS", _env("NUM_RESULTS", "5")),
            history_limit=_positive_int("HISTORY_LIMIT", _env("HISTORY_LIMIT", "10")),
            database_path=Path(_env("DATABASE_PATH", "data/app.db")),
            gaps_file=Path(_env("GAPS_FILE", "gaps.json")),
            aws_connect_timeout=_positive_int(
                "AWS_CONNECT_TIMEOUT", _env("AWS_CONNECT_TIMEOUT", "3")
            ),
            aws_read_timeout=_positive_int(
                "AWS_READ_TIMEOUT", _env("AWS_READ_TIMEOUT", "30")
            ),
            aws_max_attempts=_positive_int(
                "AWS_MAX_ATTEMPTS", _env("AWS_MAX_ATTEMPTS", "3")
            ),
            ask_max_tokens=_positive_int(
                "ASK_MAX_TOKENS", _env("ASK_MAX_TOKENS", "1024")
            ),
            onboarding_max_tokens=_positive_int(
                "ONBOARDING_MAX_TOKENS", _env("ONBOARDING_MAX_TOKENS", "1400")
            ),
            model_temperature=_bounded_float(
                "MODEL_TEMPERATURE", _env("MODEL_TEMPERATURE", "0.2"), 0.0, 1.0
            ),
            cors_origins=origins,
            public_demo=public_demo,
            demo_api_token=demo_api_token,
            model_rate_limit_per_minute=_positive_int(
                "MODEL_RATE_LIMIT_PER_MINUTE",
                _env("MODEL_RATE_LIMIT_PER_MINUTE", "30"),
            ),
            aws_region=region,
            s3_bucket=_env("S3_BUCKET", "bedrock-docs-ttanaka-202606"),
            pdf_s3_key=_env(
                "PDF_S3_KEY", "hf2000_manual_tem_edx_nbd_dstem.pdf"
            ),
        )


SETTINGS = Settings.from_env()

AWS_ACCOUNT_ID = SETTINGS.aws_account_id
REGION = SETTINGS.region
KB_ID = SETTINGS.kb_id
MODEL_SMART = SETTINGS.ask_model_id
MODEL_FAST = SETTINGS.onboarding_model_id
MODEL_SMART_ARN = SETTINGS.rag_model_arn
MODEL_SMART_INFERENCE_PROFILE_ARN = (
    f"arn:aws:bedrock:{REGION}:{AWS_ACCOUNT_ID}:inference-profile/{MODEL_SMART}"
)
GAP_THRESHOLD = SETTINGS.gap_threshold
ANSWER_PATH = SETTINGS.answer_path
NUM_RESULTS = SETTINGS.num_results
GAPS_FILE = str(SETTINGS.gaps_file)
