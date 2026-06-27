"""Central config. Non-secret identifiers only; all overridable via env.

See PROJECT_CONTEXT.md for the why behind these values (region, model ARNs,
gap threshold) and the known AWS gotchas.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Region is us-east-1 everywhere — a Tokyo (ap-northeast-1) reference is a bug.
AWS_ACCOUNT_ID = _get("AWS_ACCOUNT_ID", "465239007752")
REGION = _get("AWS_REGION", "us-east-1")

KB_ID = _get("KB_ID", "AJVVEPYMSH")

MODEL_SMART = _get("MODEL_SMART", "us.anthropic.claude-sonnet-4-6")
MODEL_FAST = _get("MODEL_FAST", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# modelArn for retrieve_and_generate. If on-demand throughput is rejected,
# override with the inference-profile ARN (see PROJECT_CONTEXT.md gotchas).
MODEL_SMART_ARN = _get(
    "MODEL_SMART_ARN",
    f"arn:aws:bedrock:{REGION}::foundation-model/anthropic.claude-sonnet-4-6",
)
MODEL_SMART_INFERENCE_PROFILE_ARN = (
    f"arn:aws:bedrock:{REGION}:{AWS_ACCOUNT_ID}:"
    "inference-profile/us.anthropic.claude-sonnet-4-6"
)

# Top retrieval score below this => treat the topic as undocumented (gap).
GAP_THRESHOLD = float(_get("GAP_THRESHOLD", "0.4"))

# "easy" = retrieve_and_generate, "advanced" = retrieve + converse.
ANSWER_PATH = _get("ANSWER_PATH", "easy")
NUM_RESULTS = int(_get("NUM_RESULTS", "5"))

GAPS_FILE = _get("GAPS_FILE", "gaps.json")
