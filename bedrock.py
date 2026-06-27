"""Bedrock calls. Public entry point: answer(message, history).

Easy path (default) = retrieve_and_generate. Advanced path = retrieve +
converse, enabled with ANSWER_PATH=advanced. boto3 reads credentials from the
environment; no keys here. See PROJECT_CONTEXT.md for the path rationale.
"""

import boto3
from botocore.exceptions import ClientError, BotoCoreError

import config
import prompts

_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=config.REGION)
_runtime = boto3.client("bedrock-runtime", region_name=config.REGION)


def _source_name(location: dict) -> str:
    if not location:
        return "不明な出典"
    if location.get("type") == "S3":
        uri = location.get("s3Location", {}).get("uri", "")
        return uri.split("/")[-1] if uri else "S3ドキュメント"
    return location.get("type") or "不明な出典"


def _extract_citations(raw_citations: list) -> list[dict]:
    out: list[dict] = []
    for citation in raw_citations:
        for ref in citation.get("retrievedReferences", []):
            out.append({
                "source": _source_name(ref.get("location", {})),
                "snippet": ref.get("content", {}).get("text", "")[:300],
            })
    return out


def _retrieve_top(message: str) -> tuple[float, list]:
    """Retrieve chunks; return (top similarity score, raw results)."""
    resp = _agent_runtime.retrieve(
        knowledgeBaseId=config.KB_ID,
        retrievalQuery={"text": message},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": config.NUM_RESULTS}
        },
    )
    results = resp.get("retrievalResults", [])
    top_score = max((r.get("score", 0.0) for r in results), default=0.0)
    return top_score, results


def _gap_result(top_score: float) -> dict:
    return {
        "answer_text": prompts.GAP_MESSAGE,
        "citations": [],
        "confidence": round(top_score, 3),
        "is_gap": True,
        "top_score": top_score,
    }


def answer_easy(message: str) -> dict:
    # Score first so the gap signal is real; skip generation on a gap.
    top_score, _results = _retrieve_top(message)
    if top_score < config.GAP_THRESHOLD:
        return _gap_result(top_score)

    resp = _agent_runtime.retrieve_and_generate(
        input={"text": message},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": config.KB_ID,
                "modelArn": config.MODEL_SMART_ARN,
                "generationConfiguration": {
                    "promptTemplate": {
                        "textPromptTemplate": prompts.RAG_PROMPT_TEMPLATE
                    }
                },
            },
        },
    )
    return {
        "answer_text": resp.get("output", {}).get("text", ""),
        "citations": _extract_citations(resp.get("citations", [])),
        "confidence": round(top_score, 3),
        "is_gap": False,
        "top_score": top_score,
    }


def answer_advanced(message: str, history: list | None = None) -> dict:
    history = history or []
    top_score, results = _retrieve_top(message)
    if top_score < config.GAP_THRESHOLD:
        return _gap_result(top_score)

    context_lines: list[str] = []
    citations: list[dict] = []
    for i, r in enumerate(results, start=1):
        text = r.get("content", {}).get("text", "")
        source = _source_name(r.get("location", {}))
        context_lines.append(f"[{i}] (出典: {source}) {text}")
        citations.append({"source": source, "snippet": text[:300]})

    user_turn = (
        "参考資料:\n" + "\n\n".join(context_lines) + f"\n\n質問: {message}\n\n"
        "上記の参考資料のみに基づいて答えてください。"
    )
    messages = history + [{"role": "user", "content": [{"text": user_turn}]}]

    resp = _runtime.converse(
        modelId=config.MODEL_SMART,
        system=[{"text": prompts.SYSTEM_PROMPT}],
        messages=messages,
        inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
    )
    return {
        "answer_text": resp["output"]["message"]["content"][0]["text"],
        "citations": citations,
        "confidence": round(top_score, 3),
        "is_gap": False,
        "top_score": top_score,
    }


def answer(message: str, history: list | None = None) -> dict:
    """Dispatch to the configured path; return a safe result on AWS errors."""
    try:
        if config.ANSWER_PATH == "advanced":
            return answer_advanced(message, history)
        return answer_easy(message)
    except (ClientError, BotoCoreError) as e:
        return {
            "answer_text": (
                "現在、知識ベースに接続できませんでした。"
                "しばらくしてからもう一度お試しいただくか、管理者にご確認ください。"
            ),
            "citations": [],
            "confidence": 0.0,
            "is_gap": False,
            "top_score": 0.0,
            "error": str(e),
        }
