import json

import boto3
from botocore.config import Config as BotoConfig

from app.providers import ANSWER_SCHEMA, _response_text
from config import SETTINGS, Settings


def _clients(settings: Settings):
    sdk_config = BotoConfig(
        connect_timeout=settings.aws_connect_timeout,
        read_timeout=settings.aws_read_timeout,
        retries={"max_attempts": settings.aws_max_attempts, "mode": "standard"},
    )
    return (
        boto3.client("sts", region_name=settings.region, config=sdk_config),
        boto3.client(
            "bedrock-agent-runtime", region_name=settings.region, config=sdk_config
        ),
        boto3.client("bedrock-runtime", region_name=settings.region, config=sdk_config),
    )


def run_preflight(
    settings: Settings,
    *,
    sts=None,
    agent_runtime=None,
    runtime=None,
    query: str = "研究室の安全ルール",
) -> dict:
    if sts is None or agent_runtime is None or runtime is None:
        default_sts, default_agent, default_runtime = _clients(settings)
        sts = sts or default_sts
        agent_runtime = agent_runtime or default_agent
        runtime = runtime or default_runtime

    identity = sts.get_caller_identity()
    if identity.get("Account") != settings.aws_account_id:
        raise RuntimeError(
            f"AWS account mismatch: expected {settings.aws_account_id}, "
            f"got {identity.get('Account')}"
        )
    retrieval = agent_runtime.retrieve(
        knowledgeBaseId=settings.kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": settings.num_results}
        },
    )
    results = retrieval.get("retrievalResults", [])

    schema_response = runtime.converse(
        modelId=settings.ask_model_id,
        messages=[{"role": "user", "content": [{"text": "Return a short status."}]}],
        inferenceConfig={"maxTokens": 64, "temperature": 0},
        outputConfig={
            "textFormat": {
                "type": "json_schema",
                "structure": {
                    "jsonSchema": {
                        "name": "lab_answer",
                        "description": "Preflight schema warm-up",
                        "schema": json.dumps(ANSWER_SCHEMA),
                    }
                },
            }
        },
    )
    parsed = json.loads(_response_text(schema_response))
    if not parsed.get("answer_text"):
        raise RuntimeError("Sonnet structured-output preflight returned no answer")

    onboarding_response = runtime.converse(
        modelId=settings.onboarding_model_id,
        messages=[{"role": "user", "content": [{"text": "Reply with ok."}]}],
        inferenceConfig={"maxTokens": 16, "temperature": 0},
    )
    if not _response_text(onboarding_response).strip():
        raise RuntimeError("Haiku preflight returned no text")
    if not results:
        raise RuntimeError("Knowledge Base retrieval returned no documents")

    return {
        "status": "ok",
        "account": identity["Account"],
        "region": settings.region,
        "retrieval_results": len(results),
        "ask_model": settings.ask_model_id,
        "onboarding_model": settings.onboarding_model_id,
    }


def main() -> int:
    print(json.dumps(run_preflight(SETTINGS), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
