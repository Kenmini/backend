"""Demo figures and their valid hotspots, used to constrain visual_data.

Hand-prepared for the MVP (no auto-tagging) — see PROJECT_CONTEXT.md.
"""

# figure_id -> hotspot names the frontend can draw.
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

DEFAULT_FIGURE_ID = "panel_01"


def valid_highlights(figure_id: str) -> list[str]:
    return FIGURES.get(figure_id, [])


def pick_highlight(figure_id: str, answer_text: str) -> str | None:
    """First hotspot of the figure that appears in the answer, else None."""
    for item in valid_highlights(figure_id):
        if item in answer_text:
            return item
    return None
