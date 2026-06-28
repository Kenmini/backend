import json
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import boto3
from botocore.config import Config as BotoConfig

import prompts
from app.models import AnswerResult, Citation, HistoryTurn, VisualReference
from config import Settings

ONBOARDING_GAP_GUIDE = (
    "オンボーディング資料がまだ登録されていません。"
    "資料が同期された後にもう一度お試しください。"
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_text": {"type": "string"},
        "next_step_hint": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "is_supported": {
            "type": "boolean",
            "description": (
                "True only when the retrieved text directly supports the answer"
            ),
        },
        "figure_id": {
            "type": "string",
            "enum": ["panel_01", "microscope_overview", "control_panel"],
            "description": "The ID of the most appropriate image to show alongside the answer.",
        },
    },
    "required": ["answer_text", "next_step_hint", "is_supported", "figure_id"],
    "additionalProperties": False,
}


class AnswerProvider(Protocol):
    name: str

    def configured(self) -> bool: ...
    def ask(self, message: str, history: list[HistoryTurn]) -> AnswerResult: ...
    def onboarding(self, role: str, field: str | None) -> str: ...


def _source_name(location: dict) -> str:
    if not location:
        return "不明な出典"
    if location.get("type") == "S3":
        uri = location.get("s3Location", {}).get("uri", "")
        return uri.rsplit("/", 1)[-1] if uri else "S3ドキュメント"
    return location.get("type") or "不明な出典"


def _retrieval_citations(results: list[dict]) -> list[Citation]:
    return [
        Citation(
            source=_source_name(item.get("location", {})),
            snippet=item.get("content", {}).get("text", "")[:300],
        )
        for item in results
    ]


def _generated_citations(raw: list[dict]) -> list[Citation]:
    citations: list[Citation] = []
    for item in raw:
        citations.extend(
            Citation(
                source=_source_name(reference.get("location", {})),
                snippet=reference.get("content", {}).get("text", "")[:300],
            )
            for reference in item.get("retrievedReferences", [])
        )
    return citations


def _visual_reference(results: list[dict]) -> VisualReference | None:
    for item in results:
        location = item.get("location", {})
        if location.get("type") != "S3":
            continue
        uri = location.get("s3Location", {}).get("uri", "")
        if not urlsplit(uri).path.lower().endswith(".pdf"):
            continue
        page = item.get("metadata", {}).get("x-amz-bedrock-kb-document-page-number")
        if not isinstance(page, (int, float)) or page < 1 or int(page) != page:
            continue
        caption = item.get("content", {}).get("text", "")
        if not isinstance(caption, str):
            caption = ""
        return VisualReference(
            source_uri=uri,
            source=_source_name(location),
            page_number=int(page),
            caption=" ".join(caption.split())[:300],
            score=round(float(item.get("score", 0.0)), 3),
        )
    return None


class BedrockAnswerProvider:
    name = "bedrock"

    def __init__(self, settings: Settings, agent_runtime=None, runtime=None):
        self.settings = settings
        sdk_config = BotoConfig(
            connect_timeout=settings.aws_connect_timeout,
            read_timeout=settings.aws_read_timeout,
            retries={"max_attempts": settings.aws_max_attempts, "mode": "standard"},
        )
        self.agent_runtime = agent_runtime or boto3.client(
            "bedrock-agent-runtime",
            region_name=settings.region,
            config=sdk_config,
        )
        self.runtime = runtime or boto3.client(
            "bedrock-runtime", region_name=settings.region, config=sdk_config
        )

    def configured(self) -> bool:
        return bool(
            self.settings.kb_id
            and self.settings.ask_model_id
            and self.settings.onboarding_model_id
            and self.settings.region == "us-east-1"
        )

    def _retrieve(self, query: str) -> tuple[float, list[dict]]:
        response = self.agent_runtime.retrieve(
            knowledgeBaseId=self.settings.kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": self.settings.num_results
                }
            },
        )
        results = response.get("retrievalResults", [])
        score = max((item.get("score", 0.0) for item in results), default=0.0)
        return score, results

    def ask(self, message: str, history: list[HistoryTurn]) -> AnswerResult:
        score, results = self._retrieve(message)
        if score < self.settings.gap_threshold:
            return AnswerResult(
                answer_text=prompts.get_gap_message(message),
                confidence=0.0,
                is_gap=True,
            )

        if self.settings.answer_path == "easy":
            return self._ask_easy(message, score)
        return self._ask_advanced(message, history, score, results)


    def _ask_easy(self, message: str, score: float) -> AnswerResult:
        response = self.agent_runtime.retrieve_and_generate(
            input={"text": message},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": self.settings.kb_id,
                    "modelArn": self.settings.rag_model_arn,
                    "generationConfiguration": {
                        "promptTemplate": {
                            "textPromptTemplate": prompts.RAG_PROMPT_TEMPLATE
                        }
                    },
                },
            },
        )
        answer_text = response.get("output", {}).get("text", "")
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise ValueError("Bedrock returned an empty answer")
        return AnswerResult(
            answer_text=answer_text,
            citations=_generated_citations(response.get("citations", [])),
            confidence=round(score, 3),
        )

    def _ask_advanced(
        self,
        message: str,
        history: list[HistoryTurn],
        score: float,
        results: list[dict],
    ) -> AnswerResult:
        context = "\n\n".join(
            f"[{index}] (出典: {_source_name(item.get('location', {}))}) "
            f"{item.get('content', {}).get('text', '')}"
            for index, item in enumerate(results, start=1)
        )
        messages: list[dict] = []
        for turn in history:
            messages.extend(
                [
                    {"role": "user", "content": [{"text": turn.user}]},
                    {"role": "assistant", "content": [{"text": turn.assistant}]},
                ]
            )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"参考資料:\n{context}\n\n質問: {message}\n\n"
                            "参考資料のみに基づいて回答してください。\n"
                            "参考資料が質問へ直接回答している場合のみ、"
                            "is_supportedをtrueにしてください。"
                            "ただし、ユーザーが「画像を見せて」「全体図を見せて」などの画像表示を求めた場合で、"
                            "適切なfigure_idを選択できた時は、テキストの参考資料がなくてもis_supportedをtrueにしてください。\n\n"
                            "IMPORTANT: Your answer_text MUST be written in the same "
                            "language as the 質問 above. If the question is in English, "
                            "answer in English. If in Japanese, answer in Japanese."
                        )
                    }
                ],
            }
        )
        response = self.runtime.converse(
            modelId=self.settings.ask_model_id,
            system=[{"text": prompts.SYSTEM_PROMPT}],
            messages=messages,
            inferenceConfig={
                "maxTokens": self.settings.ask_max_tokens,
                "temperature": self.settings.model_temperature,
            },
            outputConfig={
                "textFormat": {
                    "type": "json_schema",
                    "structure": {
                        "jsonSchema": {
                            "name": "lab_answer",
                            "description": "Grounded answer and next action",
                            "schema": json.dumps(ANSWER_SCHEMA),
                        }
                    },
                }
            },
        )
        text = _response_text(response)
        parsed = json.loads(text)
        answer_text = parsed.get("answer_text")
        next_step_hint = parsed.get("next_step_hint")
        is_supported = parsed.get("is_supported")
        figure_id = parsed.get("figure_id")
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise ValueError("Bedrock returned an empty structured answer")
        if next_step_hint is not None and not isinstance(next_step_hint, str):
            raise ValueError("Bedrock returned an invalid next step")
        if not isinstance(is_supported, bool):
            raise ValueError("Bedrock returned an invalid support decision")
        if not is_supported:
            return AnswerResult(
                answer_text=prompts.get_gap_message(message),
                confidence=0.0,
                is_gap=True,
            )
        return AnswerResult(
            answer_text=answer_text,
            next_step_hint=next_step_hint,
            citations=_retrieval_citations(results),
            confidence=round(score, 3),
            visual_reference=_visual_reference(results),
            figure_id=figure_id,
        )

    def onboarding(self, role: str, field: str | None) -> str:
        field_line = f"研究分野: {field}" if field else ""
        query = f"{role} 研究室 オンボーディング {field or ''}".strip()
        score, results = self._retrieve(query)
        if score < self.settings.gap_threshold:
            return ONBOARDING_GAP_GUIDE
        context = "\n\n".join(
            item.get("content", {}).get("text", "") for item in results
        )
        prompt = prompts.ONBOARDING_TEMPLATE.format(role=role, field_line=field_line)
        response = self.runtime.converse(
            modelId=self.settings.onboarding_model_id,
            system=[{"text": prompts.SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": f"参考資料:\n{context}\n\n{prompt}"}],
                }
            ],
            inferenceConfig={
                "maxTokens": self.settings.onboarding_max_tokens,
                "temperature": self.settings.model_temperature,
            },
        )
        guide = _response_text(response).strip()
        if not guide:
            raise ValueError("Bedrock returned an empty onboarding guide")
        return guide


def _response_text(response: dict) -> str:
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if isinstance(block.get("text"), str):
            return block["text"]
    raise ValueError("Bedrock response did not contain text")


class FixtureAnswerProvider:
    name = "fixture"

    def __init__(self, fixture_path: str | Path | None = None):
        path = (
            Path(fixture_path)
            if fixture_path is not None
            else Path(__file__).resolve().parents[1] / "fixtures" / "demo_answers.json"
        )
        self.fixtures = json.loads(path.read_text(encoding="utf-8"))

    def configured(self) -> bool:
        return bool(self.fixtures.get("answers") and self.fixtures.get("onboarding"))

    def ask(self, message: str, history: list[HistoryTurn]) -> AnswerResult:
        key = " ".join(message.strip().split())
        raw = self.fixtures["answers"].get(key, self.fixtures["default_gap"])
        return AnswerResult(
            answer_text=raw["answer_text"],
            next_step_hint=raw.get("next_step_hint"),
            citations=[Citation(**item) for item in raw.get("citations", [])],
            confidence=float(raw.get("confidence", 0.0)),
            is_gap=bool(raw.get("is_gap", False)),
        )

    def onboarding(self, role: str, field: str | None) -> str:
        guide = self.fixtures["onboarding"].get(role)
        return guide or ONBOARDING_GAP_GUIDE
