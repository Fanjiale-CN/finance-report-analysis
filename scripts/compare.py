"""跨市场财报比较层。

输入任意 A 股、港股或美股报告，自动识别并调用 universal.extract_universal，
把常见字段标准化为人民币百万元后比较。不会把不同币种静默混算；缺少汇率时保留原币并标记不可比。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pymupdf

from universal import extract_universal

CANONICAL = {
    "revenue": ("revenue",),
    "gross_profit": ("gross_profit",),
    "operating_income": ("operating_income",),
    "net_income": ("net_income", "net_income_group"),
    "total_assets": ("total_assets",),
    "total_equity": ("total_equity",),
    "cash_from_operations": ("cash_from_operations",),
    "cash_from_investing": ("cash_from_investing",),
    "cash_from_financing": ("cash_from_financing",),
    "rd_expense": ("rd_expense",),
}


def _text(pdf: str) -> str:
    doc = pymupdf.open(pdf)
    try:
        return "\n".join(p.get_text() for p in doc)
    finally:
        doc.close()


def infer_measurement(text: str) -> dict[str, Any]:
    compact = re.sub(r"\s+", " ", text).lower()
    currency = "CNY" if any(x in text for x in ("人民币", "RMB", "Renminbi", "人民幣")) else "HKD" if any(x in text for x in ("港币", "港元", "港幣", "HK$", "HKD")) or ("HKEX" in text and re.search(r"\$m|\$ million", text, re.I)) else "USD" if any(x in text for x in ("US$", "USD", "dollar", "dollars")) else "unknown"
    # 先判断百万级，避免 RMB'000'000 被千元规则前缀误匹配。
    if re.search(r"rmb['’]?0{3}['’]?0{3}|rmb['’]?m|百万元|millions?", text, re.I):
        scale = 1_000_000.0
        unit = "million"
    elif re.search(r"rmb['’]?000|千元|thousand yuan|人民币千元", text, re.I):
        scale = 1_000.0
        unit = "thousand"
    elif re.search(r"亿元|亿人民币", text):
        scale = 100_000_000.0
        unit = "hundred_million"
    else:
        scale = 1.0
        unit = "base"
    standard = infer_accounting_standard(text)
    return {"currency": currency, "scale_to_base": scale, "display_unit": unit, "accounting_standard": standard}


def infer_accounting_standard(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).lower()
    if any(x in compact for x in ("u.s. gaap", "us gaap", "accounting principles generally accepted in the united states")):
        return "US_GAAP"
    if any(x in text for x in ("香港财务报告准则", "香港財務報告準則", "hkfrs")) or "hkfrs" in compact:
        return "HKFRS"
    if any(x in text for x in ("中国企业会计准则", "中國企業會計準則", "企业会计准则")) or "prc gaap" in compact:
        return "PRC_ASBE"
    if "ifrs" in compact or "国际财务报告准则" in text or "國際財務報告準則" in text:
        return "IFRS"
    return "unknown"


def _fx_to_cny(currency: str, fx: dict[str, float] | None) -> float | None:
    if currency == "CNY":
        return 1.0
    return None if not fx else fx.get(currency)


def normalize_report(report: dict[str, Any], fx_to_cny: dict[str, float] | None = None) -> dict[str, Any]:
    source_text = _text(report["source"])
    measurement = infer_measurement(source_text)
    rate = _fx_to_cny(measurement["currency"], fx_to_cny)
    factor = measurement["scale_to_base"] * rate if rate is not None else None
    normalized: dict[str, Any] = {}
    warnings = []
    if report.get("status") != "ok":
        warnings.append("报告三大报表未完整解析，比较结果仅作结构化预览，不参与跨报告结论。")
    if rate is None and measurement["currency"] != "unknown":
        warnings.append(f"缺少 {measurement['currency']}→CNY 汇率，保留原币，不参与跨币种金额比较")
    if measurement["currency"] == "unknown":
        warnings.append("无法识别币种，金额不可跨报告比较")
    for canonical, aliases in CANONICAL.items():
        data = next((report["schema"].get(a) for a in aliases if report["schema"].get(a)), None)
        if not data:
            continue
        values = data.get("values", [])[:2]
        normalized[canonical] = {
            "source_field": data.get("label", canonical),
            "native_values": values,
            "values_cny_million": [round(v * factor / 1_000_000, 4) if factor is not None and v is not None else None for v in values],
        }
    return {"source": report["source"], "status": report.get("status"), "report_type": report["report_type"], "detection": report["detection"], "measurement": measurement, "normalized": normalized, "warnings": warnings}


def compare_reports(paths: list[str], fx_to_cny: dict[str, float] | None = None) -> dict[str, Any]:
    reports = []
    for path in paths:
        reports.append(normalize_report(extract_universal(path, "auto"), fx_to_cny))
    fields = {}
    for field in CANONICAL:
        rows = []
        vals = []
        for report in reports:
            item = report["normalized"].get(field)
            value = item["values_cny_million"][0] if item and item["values_cny_million"] else None
            rows.append({"source": Path(report["source"]).name, "value_cny_million": value, "native": item["native_values"] if item else None})
            if value is not None:
                vals.append(value)
        if rows and any(r["value_cny_million"] is not None for r in rows):
            fields[field] = {"rows": rows, "spread_cny_million": round(max(vals) - min(vals), 4) if len(vals) > 1 else 0.0}
    warnings = [w for r in reports for w in r["warnings"]]
    standards = {r["measurement"].get("accounting_standard") for r in reports if r["measurement"].get("accounting_standard") != "unknown"}
    if len(standards) > 1:
        warnings.append("报告使用的会计准则不同（" + ", ".join(sorted(standards)) + "），未进行准则重述，跨市场结论需人工复核。")
    warnings.append("跨公司或跨市场比较前，必须确认财年、合并范围、会计准则及币种汇率一致；本工具只做数字标准化，不替代会计重述。")
    return {"reports": reports, "fields": fields, "warnings": warnings}


def render_markdown(result: dict[str, Any]) -> str:
    lines = ["# 跨市场财报比较", "", "## 报告识别与计量口径", "", "| 报告 | 自动类型 | 币种 | 原始单位 | 识别置信度 |", "|---|---|---|---|---|"]
    for r in result["reports"]:
        d, m = r["detection"], r["measurement"]
        lines.append(f"| {Path(r['source']).name} | {r['report_type']} | {m['currency']} | {m['display_unit']} | {d['confidence']} |")
    lines += ["", "## 统一后关键字段（人民币百万元）", "", "| 字段 | 报告 | 数值 |", "|---|---|---:|"]
    for field, info in result["fields"].items():
        for row in info["rows"]:
            if row["value_cny_million"] is not None:
                lines.append(f"| {field} | {row['source']} | {row['value_cny_million']:,.2f} |")
    lines += ["", "## 口径警示", ""] + [f"> {w}" for w in result["warnings"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdfs", nargs="+")
    parser.add_argument("--fx", default="{}", help="JSON，例如 {'USD': 7.2, 'HKD': 0.92}")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = compare_reports(args.pdfs, json.loads(args.fx))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_markdown(result))

