"""
bedrock.py — All Amazon Bedrock calls for the Lab Tacit-Knowledge AI Agent.

Public surface: ONE function, answer(message, history). It dispatches to the
EASY path (retrieve_and_generate) by default, or the ADVANCED path
(retrieve + converse) when config.ANSWER_PATH == "advanced".

Credentials: boto3 reads them from the standard AWS credential chain
(`aws configure`) or environment variables. No keys appear in this file.

Region: every client is pinned to config.REGION (us-east-1).
"""

import boto3
from botocore.exceptions import ClientError, BotoCoreError

import config
import prompts


# --- Bedrock clients (region-pinned, created once at import) ----------------
# bedrock-agent-runtime: retrieve + retrieve_and_generate (Knowledge Base).
# bedrock-runtime:       converse (direct model calls; ADVANCED path).
_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=config.REGION)
_runtime = boto3.client("bedrock-runtime", region_name=config.REGION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _source_name(location: dict) -> str:
    """
    Turn a Bedrock 'location' object into a human-readable source name.
    Falls back to a generic label if the shape is unexpected.
    """
    if not location:
        return "不明な出典"
    loc_type = location.get("type", "")
    if loc_type == "S3":
        uri = location.get("s3Location", {}).get("uri", "")
        # Show just the file name, not the full s3://bucket/key path.
        return uri.split("/")[-1] if uri else "S3ドキュメント"
    # Other source types (WEB, CONFLUENCE, ...) — return the type label.
    return loc_type or "不明な出典"


def _extract_citations(raw_citations: list) -> list[dict]:
    """Flatten retrieve_and_generate's citations into [{source, snippet}, ...]."""
    out: list[dict] = []
    for citation in raw_citations:
        for ref in citation.get("retrievedReferences", []):
            text = ref.get("content", {}).get("text", "")
            source = _source_name(ref.get("location", {}))
            out.append({"source": source, "snippet": text[:300]})
    return out


def _retrieve_top(message: str) -> tuple[float, list]:
    """
    Call the Knowledge Base 'retrieve' API.

    Returns (top_score, results):
      - top_score: highest similarity score among returned chunks (0.0 if none).
      - results:   raw retrievalResults list.

    Used for gap detection on BOTH paths, and as the context source on the
    ADVANCED path.
    """
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
    """Build the standard 'knowledge gap' result (no generation)."""
    return {
        "answer_text": prompts.GAP_MESSAGE,
        "citations": [],
        "confidence": round(top_score, 3),
        "is_gap": True,
        "top_score": top_score,
    }


# ---------------------------------------------------------------------------
# EASY path (default)
# ---------------------------------------------------------------------------
def answer_easy(message: str) -> dict:
    """
    EASY path. Two managed steps for an honest, real gap signal:

      1. retrieve top chunks + similarity scores.
      2. If top score < GAP_THRESHOLD -> knowledge gap: return the honest
         "not documented yet" message (is_gap=True) WITHOUT generating, so we
         never hallucinate past the lab's recorded knowledge.
      3. Otherwise retrieve_and_generate for a grounded answer + citations.

    Returns the core result dict (answer_text, citations, confidence, is_gap,
    top_score). main.py adds next_step_hint and visual_data.
    """
    top_score, _results = _retrieve_top(message)

    # --- Gap case: below threshold => undocumented topic -------------------
    if top_score < config.GAP_THRESHOLD:
        return _gap_result(top_score)

    # --- Confident case: generate a grounded answer -----------------------
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

    answer_text = resp.get("output", {}).get("text", "")
    citations = _extract_citations(resp.get("citations", []))

    return {
        "answer_text": answer_text,
        "citations": citations,
        "confidence": round(top_score, 3),
        "is_gap": False,
        "top_score": top_score,
    }


# ---------------------------------------------------------------------------
# ADVANCED path (stretch — set ANSWER_PATH=advanced to enable)
# ---------------------------------------------------------------------------
def answer_advanced(message: str, history: list | None = None) -> dict:
    """
    ADVANCED path. Full control over persona, citations, and confidence.

      1. retrieve chunks + scores.
      2. Gap decision from the top score (same threshold).
      3. Build a context block from the chunks and call converse with our
         Japanese SYSTEM_PROMPT plus the per-session history.

    `history` is a list of converse 'messages' dicts for this session (optional).

    TODO(advanced): also ask the model to return next_step_hint and the chosen
    highlight_item as structured output here, instead of deriving them later.
    """
    history = history or []
    top_score, results = _retrieve_top(message)

    if top_score < config.GAP_THRESHOLD:
        return _gap_result(top_score)

    # Build a context block + citations from the retrieved chunks.
    context_lines: list[str] = []
    citations: list[dict] = []
    for i, r in enumerate(results, start=1):
        text = r.get("content", {}).get("text", "")
        source = _source_name(r.get("location", {}))
        context_lines.append(f"[{i}] (出典: {source}) {text}")
        citations.append({"source": source, "snippet": text[:300]})
    context_block = "\n\n".join(context_lines)

    user_turn = (
        f"参考資料:\n{context_block}\n\n"
        f"質問: {message}\n\n"
        "上記の参考資料のみに基づいて答えてください。"
    )

    messages = history + [{"role": "user", "content": [{"text": user_turn}]}]

    resp = _runtime.converse(
        modelId=config.MODEL_SMART,
        system=[{"text": prompts.SYSTEM_PROMPT}],
        messages=messages,
        inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
    )

    answer_text = resp["output"]["message"]["content"][0]["text"]

    return {
        "answer_text": answer_text,
        "citations": citations,
        "confidence": round(top_score, 3),
        "is_gap": False,
        "top_score": top_score,
    }


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------
def answer(message: str, history: list | None = None) -> dict:
    """
    Public entry point. Dispatches to the configured path and never raises:
    on any AWS error it returns a safe result in the contract shape so the API
    stays up during the demo.
    """
    try:
        if config.ANSWER_PATH == "advanced":
            return answer_advanced(message, history)
        return answer_easy(message)
    except (ClientError, BotoCoreError) as e:
        # Common causes: KB not synced yet, wrong region, model access not
        # granted, or the on-demand-throughput validation error (switch
        # MODEL_SMART_ARN to the inference-profile ARN — see config.py).
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
