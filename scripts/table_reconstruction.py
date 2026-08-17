"""Coordinate-based fallback for PDF financial tables.

它不替代专用解析器，而是在文本阅读顺序被打乱、标签和数字跨列/跨页时，
利用 PyMuPDF words 的 x/y 坐标重建最小可用的「标签 + N 期数值」行。
"""
from __future__ import annotations

import re
from typing import Any

from statement_parser import to_number

_NUMERICISH = re.compile(r"^[\(（]?[-–—−]?[\$€£¥]?[\d,]+(?:\.\d+)?%?[\)）]?$|^[—–-]$")


def _is_numeric_token(token: str) -> bool:
    token = token.strip()
    if _NUMERICISH.match(token):
        return True
    # PDF 常把括号、货币符号独立成 token；只把纯数字/破折号作为数值起点。
    return bool(re.fullmatch(r"[-–—−]?\d[\d,]*(?:\.\d+)?", token))


def _token_number(tokens: list[str]) -> float | None:
    raw = "".join(tokens).replace("−", "-").replace("—", "-").replace("–", "-")
    raw = raw.replace("(", "-").replace(")", "").replace("（", "-").replace("）", "")
    raw = raw.replace("$", "").replace("€", "").replace("£", "").replace("¥", "")
    return to_number(raw)


def reconstruct_words(words: list[tuple[Any, ...]], n_periods: int, *, y_tolerance: float = 3.0) -> list[dict[str, Any]]:
    """从 ``page.get_text('words')`` 的 words 重建行项目。"""
    rows: list[dict[str, Any]] = []
    for word in sorted(words, key=lambda w: (float(w[1]), float(w[0]))):
        x0, y0, x1, y1, text = float(word[0]), float(word[1]), float(word[2]), float(word[3]), str(word[4])
        row = next((r for r in rows if abs(r["y"] - y0) <= y_tolerance), None)
        if row is None:
            row = {"y": y0, "words": []}
            rows.append(row)
        row["words"].append((x0, x1, text))
    result = []
    for row in sorted(rows, key=lambda r: r["y"]):
        tokens = [text for _, _, text in sorted(row["words"], key=lambda x: x[0])]
        if not tokens:
            continue
        groups: list[list[str]] = []
        current: list[str] = []
        for token in tokens:
            if _is_numeric_token(token) or token in {"(", ")", "（", "）", "$", "€", "£", "¥"}:
                current.append(token)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        values = [_token_number(g) for g in groups]
        values = [v for v in values if v is not None]
        if len(values) < n_periods:
            continue
        label_tokens = tokens
        # 只保留第一个数值组前的文字作为标签，避免把注释/单位吞进来。
        first_numeric = next((i for i, t in enumerate(tokens) if _is_numeric_token(t)), len(tokens))
        label = " ".join(tokens[:first_numeric]).strip()
        if len(label) < 2:
            continue
        result.append({"label": label, "values": values[:n_periods], "footnote": None, "source": "coordinate_reconstruction"})
    return result


def reconstruct_pages(pages: list[Any], n_periods: int) -> list[dict[str, Any]]:
    words: list[tuple[Any, ...]] = []
    for page in pages:
        words.extend(page.get_text("words", sort=True))
    return reconstruct_words(words, n_periods)
