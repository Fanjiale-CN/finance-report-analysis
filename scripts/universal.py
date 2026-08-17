"""Universal entry point for finance-report-analysis.

负责：自动识别、调用兼容解析器、包装统一 FinancialReport 契约。
表格重建和 HTML 入口会在后续模块接入；旧版文本解析器仍作为 fallback。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pymupdf

from analyze import build_schema
from extract import REPORT_CONFIGS, run_extraction
from models import FinancialLineItem, FinancialReport, FinancialStatement, issue, safe_failure


def _all_text(pdf_path: str | Path, limit_pages: int | None = None) -> str:
    doc = pymupdf.open(str(pdf_path))
    try:
        end = len(doc) if limit_pages is None else min(len(doc), limit_pages)
        return "\n".join(doc[i].get_text() for i in range(end))
    finally:
        doc.close()


def _score_market_and_type(text: str) -> dict[str, int]:
    compact = re.sub(r"\s+", " ", text).lower()
    scores = {name: 0 for name in REPORT_CONFIGS}
    # A 股：先判市场，再由行业信号决定 bank/general；不再把所有合并报表当银行。
    cn_signal = sum(token in text for token in ("合并资产负债表", "合并利润表", "合并现金流量表", "人民币"))
    bank_signal = sum(token in text for token in ("净利息收益率", "不良贷款率", "拨备覆盖率", "资本充足率", "银行业监督管理"))
    if cn_signal >= 2:
        scores["cn_a_share_general"] += 5 + min(cn_signal, 3)
        scores["cn_a_share_annual"] += min(bank_signal, 3)
    if bank_signal >= 2:
        scores["cn_a_share_annual"] += 5
    # 港股英文年报与繁中公告：允许 IFRS 标题变体。
    hk_income = any(token in compact for token in (
        "consolidated income statement", "consolidated statement of profit or loss",
        "consolidated statement of comprehensive income", "簡明合併損益表", "合併損益表",
    ))
    hk_annual_anchor = any(token in compact for token in ("for the year ended", "annual report", "年度報告"))
    hk_quarter_anchor = any(token in text for token in ("中期簡明", "季度業績", "三個月止", "六個月止"))
    if hk_income and hk_annual_anchor:
        scores["hk_annual"] += 7
    if hk_quarter_anchor:
        # 业绩公告可能同时出现 annual report/年度报告字样；明确的季度或中期锚点优先。
        scores["hk_quarterly"] += 9
    if any(token in compact for token in ("hong kong exchanges", "hkex", "hk$", "hkd")):
        scores["hk_annual"] += 1
    # 美股：10-K/10-Q 备案锚点 + 标题变体。
    us_income = any(token in compact for token in (
        "consolidated statements of operations", "consolidated statements of income",
        "consolidated statements of earnings", "statements of operations and comprehensive income",
    ))
    if us_income:
        scores["us_10k"] += 5
        scores["us_10q"] += 2
    if "form 10-k" in compact or "10-k" in compact:
        scores["us_10k"] += 4
    if "form 10-q" in compact or "10-q" in compact:
        scores["us_10q"] += 4
    if "united states securities and exchange commission" in compact:
        scores["us_10k"] += 1
    return scores


def detect_report_type(pdf_path: str | Path) -> dict[str, Any]:
    text = _all_text(pdf_path)
    scores = _score_market_and_type(text)
    ordered = sorted(scores.values(), reverse=True)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        best = None
        confidence = "low"
    elif scores[best] >= 7 and scores[best] > (ordered[1] if len(ordered) > 1 else 0):
        confidence = "high"
    elif scores[best] >= 4:
        confidence = "medium"
    else:
        confidence = "low"
    if best is None:
        market = language = None
    else:
        market = "US" if best.startswith("us_") else "CN" if best.startswith("cn_") else "HK"
        language = "zh-CN" if market == "CN" else "zh-Hant" if best == "hk_quarterly" else "en"
    return {"report_type": best, "market": market, "language": language, "confidence": confidence, "scores": scores}


def _statement_from_legacy(name: str, data: dict[str, Any], report: dict[str, Any]) -> FinancialStatement:
    kind = name if name in ("income_statement", "balance_sheet", "cash_flow", "key_ratios") else "income_statement"
    statement = FinancialStatement(
        kind=kind, title=name, unit=report.get("unit"), currency=report.get("currency"),
        accounting_standard=report.get("accounting_standard"),
    )
    if "error" in data:
        statement.issues.append(issue("statement_not_found", data["error"], "error", statement=name))
        return statement
    for item in data.get("items", []):
        statement.items.append(FinancialLineItem(
            canonical=None, label=item.get("label", ""), values=item.get("values", []),
            unit=report.get("unit"), currency=report.get("currency"), raw=item,
        ))
    statement.complete = len(statement.items) >= 3
    return statement


def _legacy_to_contract(pdf_path: str | Path, detection: dict[str, Any], extraction: dict[str, Any], schema: dict[str, Any]) -> FinancialReport:
    report = FinancialReport(
        source=str(Path(pdf_path).resolve()), company=None, market=detection.get("market"),
        report_type=detection.get("report_type"), language=detection.get("language"),
        fiscal_period=None, currency=None, unit=None, accounting_standard=None,
        consolidation="consolidated", detection_confidence=detection.get("confidence", "low"),
        metadata={"parser": "legacy_text_fallback"},
    )
    for name, data in extraction.items():
        report.statements[name] = _statement_from_legacy(name, data, report.__dict__)
    completeness = report.completeness()
    if not completeness["complete"]:
        report.issues.append(issue("incomplete_report", "至少一个标准报表未完整解析；比较层将阻止不可比计算。", "warning", details=completeness))
    return report


def extract_universal(pdf_path: str | Path, report_type: str = "auto", *, strict: bool = False) -> dict[str, Any]:
    detection = detect_report_type(pdf_path) if report_type == "auto" else {
        "report_type": report_type, "market": report_type.split("_")[0].upper(),
        "language": "unknown", "confidence": "manual", "scores": {},
    }
    chosen = detection["report_type"]
    if not chosen or chosen not in REPORT_CONFIGS:
        result = safe_failure(str(pdf_path), "无法自动识别报告类型。支持: " + ", ".join(sorted(REPORT_CONFIGS)), "unknown_report_type")
        if strict:
            raise ValueError(result["error"]["message"])
        result["detection"] = detection
        return result
    try:
        extraction = run_extraction(str(pdf_path), chosen)
        schema = build_schema(extraction, chosen)
        contract = _legacy_to_contract(pdf_path, detection, extraction, schema)
        result = contract.to_dict()
        completeness = contract.completeness()
        result.update({"status": "ok" if completeness["complete"] else "incomplete", "completeness": completeness, "extraction": extraction, "schema": schema, "detection": detection})
        if strict and result["status"] != "ok":
            raise ValueError("报告解析不完整：" + str(contract.completeness()))
        return result
    except Exception as exc:
        if strict:
            raise
        result = safe_failure(str(pdf_path), str(exc), "parse_failed")
        result["detection"] = detection
        return result


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--report-type", default="auto")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = extract_universal(args.pdf, args.report_type, strict=args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))
