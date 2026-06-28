from dataclasses import dataclass, field


@dataclass(frozen=True)
class Citation:
    source: str
    snippet: str


@dataclass(frozen=True)
class VisualReference:
    source_uri: str
    source: str
    page_number: int
    caption: str
    score: float


@dataclass(frozen=True)
class AnswerResult:
    answer_text: str
    next_step_hint: str | None = None
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    is_gap: bool = False
    # RAGが参照したPDFのS3キーとページ番号（Rekognition用）
    source_pdf_s3_key: str | None = None
    source_page_number: int | None = None



@dataclass(frozen=True)
class HistoryTurn:
    user: str
    assistant: str


@dataclass(frozen=True)
class Interaction:
    session_id: str
    user_message: str
    assistant_message: str
    next_step_hint: str | None
    is_gap: bool
    confidence: float
    citations: list[Citation]


@dataclass(frozen=True)
class Gap:
    question: str
    count: int
    first_seen: str
    last_seen: str
