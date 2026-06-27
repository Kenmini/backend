import logging

from app.models import AnswerResult, Interaction
from app.providers import AnswerProvider
from app.repositories import Repository

logger = logging.getLogger(__name__)

SAFE_ANSWER = (
    "現在、知識ベースに接続できませんでした。"
    "しばらくしてからもう一度お試しいただくか、管理者にご確認ください。"
)
SAFE_ONBOARDING = (
    "現在、知識ベースに接続できませんでした。"
    "オンボーディング資料を管理者にご確認ください。"
)


class KnowledgeService:
    def __init__(self, provider: AnswerProvider, repository: Repository):
        self.provider = provider
        self.repository = repository

    def ask(self, message: str, session_id: str | None) -> AnswerResult:
        history = []
        if session_id:
            try:
                history = self.repository.get_history(session_id)
            except Exception:
                logger.exception("history_read_failed")
        try:
            result = self.provider.ask(message, history)
        except Exception:
            logger.exception("answer_provider_failed")
            return AnswerResult(answer_text=SAFE_ANSWER)

        try:
            if result.is_gap:
                self.repository.log_gap(message)
            if session_id:
                self.repository.save_interaction(
                    Interaction(
                        session_id=session_id,
                        user_message=message,
                        assistant_message=result.answer_text,
                        next_step_hint=result.next_step_hint,
                        is_gap=result.is_gap,
                        confidence=result.confidence,
                        citations=result.citations,
                    )
                )
        except Exception:
            logger.exception("interaction_write_failed")
        return result

    def onboarding(self, role: str, field: str | None) -> str:
        try:
            return self.provider.onboarding(role, field)
        except Exception:
            logger.exception("onboarding_provider_failed")
            return SAFE_ONBOARDING
