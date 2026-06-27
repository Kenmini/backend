"""
config.py — Central configuration for the Lab Tacit-Knowledge AI Agent backend.

Every value here is a NON-SECRET identifier (account id, region, KB id, model
ids, thresholds). Each one can be overridden with an environment variable, so a
teammate can point the app at their own resources without editing code.

No AWS access keys or secrets live here. boto3 reads credentials from the
standard AWS credential chain (`aws configure`) or from a local .env file.
"""

import os

from dotenv import load_dotenv

# Load a local .env file if present (it is gitignored). Real environment
# variables that are already set take precedence over .env entries.
load_dotenv()


def _get(name: str, default: str) -> str:
    """Read an environment override, falling back to the hackathon default."""
    return os.environ.get(name, default)


# --- AWS account / region --------------------------------------------------
# IMPORTANT: everything lives in us-east-1 (N. Virginia). A reference to
# ap-northeast-1 (Tokyo) anywhere is a bug — the Knowledge Base, the models,
# and the S3 data source are all in us-east-1.
AWS_ACCOUNT_ID = _get("AWS_ACCOUNT_ID", "465239007752")
REGION = _get("AWS_REGION", "us-east-1")

# --- Knowledge Base --------------------------------------------------------
# Bedrock Knowledge Base id. The KB manages Titan Text Embeddings v2 and the
# Aurora vector store internally; we never call the embeddings model directly.
KB_ID = _get("KB_ID", "AJVVEPYMSH")

# --- Models ----------------------------------------------------------------
# Smart model for main answers; fast model for FAQ / bulk work.
# Sonnet 4.6 is an INFERENCE_PROFILE model: use the "us." prefixed id for the
# converse API and a foundation-model ARN for retrieve_and_generate.
MODEL_SMART = _get("MODEL_SMART", "us.anthropic.claude-sonnet-4-6")
MODEL_FAST = _get("MODEL_FAST", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# modelArn used by retrieve_and_generate (EASY path).
# GOTCHA: if this raises a validation error about on-demand throughput, set the
# MODEL_SMART_ARN env var to the inference-profile ARN instead:
#   arn:aws:bedrock:us-east-1:465239007752:inference-profile/us.anthropic.claude-sonnet-4-6
MODEL_SMART_ARN = _get(
    "MODEL_SMART_ARN",
    f"arn:aws:bedrock:{REGION}::foundation-model/anthropic.claude-sonnet-4-6",
)

# Convenience: the inference-profile ARN, ready to drop into MODEL_SMART_ARN if
# the foundation-model ARN above is rejected.
MODEL_SMART_INFERENCE_PROFILE_ARN = (
    f"arn:aws:bedrock:{REGION}:{AWS_ACCOUNT_ID}:"
    "inference-profile/us.anthropic.claude-sonnet-4-6"
)

# --- Gap detection (the signature feature) ---------------------------------
# If the top retrieval similarity score is below this threshold, we treat the
# topic as undocumented: answer honestly, set is_gap=true, and log the question.
# 0.4 is a starting guess — calibrate once real documents are synced.
GAP_THRESHOLD = float(_get("GAP_THRESHOLD", "0.4"))

# --- Answer path switch ----------------------------------------------------
#   "easy"     -> retrieve_and_generate  (default; one managed call)
#   "advanced" -> retrieve + converse    (stretch; full control of persona/score)
ANSWER_PATH = _get("ANSWER_PATH", "easy")

# How many chunks to retrieve for the score / context.
NUM_RESULTS = int(_get("NUM_RESULTS", "5"))

# --- Local stores ----------------------------------------------------------
# Path to the local knowledge-gap store (JSON). Gitignored.
GAPS_FILE = _get("GAPS_FILE", "gaps.json")
