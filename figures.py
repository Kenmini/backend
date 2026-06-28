"""figures.py — 図IDとホットスポット名の管理。

起動時は手作業で定義したデフォルト値を使用し、
/admin/extract-figures エンドポイントを叩くことで
Amazon Rekognition の結果を元に動的更新される。
"""
from __future__ import annotations

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


def update_from_extraction(figure_infos: list) -> dict[str, list[str]]:
    """Rekognition の抽出結果を元に FIGURES を動的更新する。

    Parameters
    ----------
    figure_infos:
        app.figure_extractor.FigureInfo のリスト

    Returns
    -------
    dict[str, list[str]]
        更新後の FIGURES の内容
    """
    for info in figure_infos:
        # ラベルが存在するページだけ登録（空ページは除外）
        if info.labels_ja:
            # 重複を除いて既存エントリを上書き or 新規追加
            FIGURES[info.figure_id] = list(dict.fromkeys(info.labels_ja))

    return dict(FIGURES)

