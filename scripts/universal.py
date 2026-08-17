"""Universal entry point for finance-report-analysis.

自动识别 A 股、港股、美股报告，路由到专属解析器，并包装成统一对象。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pymupdf

from extract import REPORT_CONFIGS, run_extraction
from analyze import build_schema


def _all_text(pdf_path: str | Path, limit_pages: int | None = None) -> str:
    doc = pymupdf.open(str(pdf_path))
    try:
        end = len(doc) if limit_pages is None else min(len(doc), limit_pages)
        return "\n".join(doc[i].get_text() for i in range(end))
    finally:
        doc.close()


def detect_report_type(pdf_path: str | Path) -> dict[str, Any]:
    text = _all_text(pdf_path)
    compact = re.sub(r"\s+", " ", text).lower()
    scores = {name: 0 for name in REPORT_CONFIGS}
    if "中期簡明合併損益表" in text or "中期简明合并损益表" in text:
        scores["hk_quarterly"] += 8
    if "consolidated income statement" in compact and "for the year ended" in compact:
        scores["hk_annual"] += 7
    if "consolidated statement of cash flows" in compact and "rmb" in compact:
        scores["hk_annual"] += 2
    if "合并及公司利润表" in text or "合并及公司资产负债表" in text:
        scores["cn_a_share_annual"] += 8
    if "合并利润表" in text and "合并资产负债表" in text:
        scores["cn_a_share_general"] += 7
    if "合并现金流量表" in text and "人民币" in text:
        scores["cn_a_share_general"] += 2
    if "condensed consolidated statements of operations" in compact:
        scores["us_10q"] += 8
    elif "consolidated statements of operations" in compact:
        scores["us_10k"] += 6
    if "form 10-k" in compact or "10-k" in compact:
        scores["us_10k"] += 4
    if "form 10-q" in compact or "10-q" in compact:
        scores["us_10q"] += 4
    if "归属于母公司" in text and "合并现金流量表" in text:
        scores["cn_a_share_general"] += 2
    if "RMB'000" in text and "XIAOMI CORPORATION" in text:
        scores["hk_annual"] += 2
    if "united states securities" in compact or "commission" in compact:
        scores["us_10k"] += 1
    best = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    if scores[best] == 0:
        best = None
        confidence = "low"
    elif scores[best] >= 7 and scores[best] > ordered[1]:
        confidence = "high"
    else:
        confidence = "medium"
    market = None if best is None else ("US" if best.startswith("us_") else "CN" if best.startswith("cn_") else "HK")
    language = "zh-CN" if market == "CN" else "zh-Hant" if best == "hk_quarterly" else "en" if market in ("US", "HK") else "unknown"
    return {"report_type": best, "market": market, "language": language, "confidence": confidence, "scores": scores}


def extract_universal(pdf_path: str | Path, report_type: str = "auto") -> dict[str, Any]:
    detection = detect_report_type(pdf_path) if report_type == "auto" else {
        "report_type": report_type,
        "market": report_type.split("_")[0].upper(),
        "language": "unknown",
        "confidence": "manual",
        "scores": {},
    }
    chosen = detection["report_type"]
    if not chosen or chosen not in REPORT_CONFIGS:
        raise ValueError("无法自动识别报告类型。请显式指定 report_type；支持: " + ", ".join(sorted(REPORT_CONFIGS)))
    extraction = run_extraction(str(pdf_path), chosen)
    schema = build_schema(extraction, chosen)
    return {"source": str(Path(pdf_path).resolve()), "detection": detection, "report_type": chosen, "extraction": extraction, "schema": schema}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--report-type", default="auto")
    args = parser.parse_args()
    result = extract_universal(args.pdf, args.report_type)
    print(json.dumps({k: result[k] for k in ("source", "detection", "report_type", "schema")}, ensure_ascii=False, indent=2))

