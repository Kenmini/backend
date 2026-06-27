"""
figures.py — Hand-prepared demo figures and their valid highlight hotspots.

For the MVP we do NOT auto-tag figures. We define a small known set of figures,
each with a fixed list of named hotspots. The backend constrains
`visual_data.highlight_item` to that list for the active figure, so the value is
always valid and the frontend can render a reliable overlay.

TODO(figure auto-tagging): replace this static map with real hotspot detection
from the manual PDFs / images at ingestion time, and have the model return the
chosen highlight_item as structured output (see bedrock.answer_advanced).
"""

# figure_id -> list of valid highlight_item names.
# These names must match the hotspot labels the frontend draws on each figure.
FIGURES: dict[str, list[str]] = {
    "panel_01": [
        "輝度つまみ",
        "対物レンズ",
        "フォーカスノブ",
        "ステージ",
        "電源スイッチ",
    ],
    "microscope_overview": [
        "接眼レンズ",
        "対物レンズ",
        "ステージ",
        "光源",
        "粗動ハンドル",
        "微動ハンドル",
    ],
    "control_panel": [
        "電源スイッチ",
        "輝度つまみ",
        "シャッターボタン",
        "緊急停止ボタン",
    ],
}

# Used when the request's current_state has no active_figure_id.
DEFAULT_FIGURE_ID = "panel_01"


def valid_highlights(figure_id: str) -> list[str]:
    """Return the allowed highlight_item names for a figure ([] if unknown)."""
    return FIGURES.get(figure_id, [])


def pick_highlight(figure_id: str, answer_text: str) -> str | None:
    """
    Choose a highlight_item for the active figure, constrained to the known list.

    MVP heuristic: if any of the figure's hotspot names appears in the answer
    text, return the first match. This keeps visual_data valid without an extra
    model call. Returns None if nothing matches (frontend then highlights
    nothing).

    TODO(advanced): instead of keyword matching, prompt Claude to RETURN the
    chosen highlight_item (constrained to valid_highlights) as structured output
    for more accurate selection.
    """
    for item in valid_highlights(figure_id):
        if item in answer_text:
            return item
    return None
