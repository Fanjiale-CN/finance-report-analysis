"""
财报提取流水线 v0.1
定位关键页 -> PyMuPDF提取文本 -> 逐行解析为结构化数据

用法示例见文件底部 __main__。
依赖: pip install pymupdf --break-system-packages
"""
import json
import pymupdf
from statement_parser import parse_statement, clean_lines, VALUE_RE


def find_pages(doc, keywords):
    """在全篇文档中按关键词定位页码（1-indexed）。返回 {keyword: [page_no, ...]}"""
    hits = {}
    for i, page in enumerate(doc):
        text = page.get_text()
        for kw in keywords:
            if kw in text:
                hits.setdefault(kw, []).append(i + 1)
    return hits


def extract_statement(doc, page_nos, n_periods, strip_before=None, strip_after=None):
    """给定一个或多个连续页码（1-indexed），拼接文本后解析为结构化行项目。
    strip_before / strip_after: 可选的文本锚点，只保留锚点之间的内容（用于剔除
    页眉页脚或表后附注等噪音）。
    """
    text = "\n".join(doc[p - 1].get_text() for p in page_nos)
    if strip_before:
        idx = text.find(strip_before)
        if idx != -1:
            text = text[idx:]
    if strip_after:
        idx = text.find(strip_after)
        if idx != -1:
            text = text[:idx]
    items = parse_statement(text, n_periods)
    # 过滤明显的页眉页码噪音：label很短且footnote标了IRREGULAR(1)、value像页码(<500)
    clean_items = []
    dropped = []
    for it in items:
        if (it["footnote"] and "IRREGULAR" in str(it["footnote"])
                and len(it["values"]) <= 1):
            dropped.append(it)
        else:
            clean_items.append(it)
    return {"items": clean_items, "dropped_noise": dropped}


# ---- 每种报告类型的定位配置 ----
# n_periods: 该报表每行数据的期数（跟随报表版式，需要人工确认一次）
REPORT_CONFIGS = {
    "us_10k": {
        "income_statement": {"keyword": "CONSOLIDATED STATEMENTS OF OPERATIONS", "n_periods": 3},
        "balance_sheet": {"keyword": "CONSOLIDATED BALANCE SHEETS", "n_periods": 2},
        "cash_flow": {"keyword": "CONSOLIDATED STATEMENTS OF CASH FLOWS", "n_periods": 3},
    },
    "us_10q": {
        "income_statement": {"keyword": "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS", "n_periods": 4},
        "balance_sheet": {"keyword": "CONDENSED CONSOLIDATED BALANCE SHEETS", "n_periods": 2},
        "cash_flow": {"keyword": "CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS", "n_periods": 2},
    },
    "cn_a_share_annual": {
        "income_statement": {"keyword": "合并及公司利润表", "n_periods": 4},
        "balance_sheet": {"keyword": "合并及公司资产负债表", "n_periods": 4, "span_pages": 2},
        "cash_flow": {"keyword": "合并及公司现金流量表", "n_periods": 4, "span_pages": 2},
        "key_ratios": {"all_keywords": ["净利息收益率", "不良贷款率", "资本充足率"],
                       "n_periods": 3, "strip_after": "分季度财务数据"},
    },
    "hk_quarterly": {
        "income_statement": {"keyword": "中期簡明合併損益表", "n_periods": 2},
    },
}


def _numeric_density(doc, page_no):
    """粗略判断一页里"看起来像数据"的行有多少——用来在多个关键词命中页中
    挑出真正的报表正文页，排除目录/引用提及等噪音页。"""
    lines = clean_lines(doc[page_no - 1].get_text())
    return sum(1 for l in lines if VALUE_RE.match(l))


def _find_page_by_all_keywords(doc, keywords):
    """要求多个关键词在同一页同时出现才算命中——用于关键词本身在全文重复
    出现（如"不良贷款率"在多张明细表里都会提到）、单关键词无法唯一定位的场景。"""
    for i, page in enumerate(doc):
        text = page.get_text()
        if all(kw in text for kw in keywords):
            return i + 1
    return None


def run_extraction(pdf_path, report_type):
    doc = pymupdf.open(pdf_path)
    config = REPORT_CONFIGS[report_type]
    result = {}
    for stmt_name, cfg in config.items():
        if "all_keywords" in cfg:
            start_page = _find_page_by_all_keywords(doc, cfg["all_keywords"])
            if start_page is None:
                result[stmt_name] = {"error": f"未找到关键词组合: {cfg['all_keywords']}"}
                continue
        else:
            hits = find_pages(doc, [cfg["keyword"]])
            pages = hits.get(cfg["keyword"], [])
            if not pages:
                result[stmt_name] = {"error": f"未找到关键词: {cfg['keyword']}"}
                continue
            # 多个命中页时（目录引用、附注中提及、正文本身可能横跨多页），
            # 用数字密度筛出"看起来像正文"的页，取其中最靠前的一页作为起点
            # ——报表正文常常横跨2页（如资产 vs 负债+权益分两页），只取密度
            # 最高的单页会漏掉前一页。
            densities = {p: _numeric_density(doc, p) for p in pages}
            max_density = max(densities.values())
            threshold = max(max_density * 0.5, 10)
            candidates = [p for p in pages if densities[p] >= threshold]
            start_page = min(candidates)
        span = cfg.get("span_pages", 1)
        page_range = list(range(start_page, start_page + span))
        result[stmt_name] = extract_statement(
            doc, page_range, cfg["n_periods"],
            strip_after=cfg.get("strip_after"),
        )
    doc.close()
    return result


if __name__ == "__main__":
    import sys
    tests = [
        ("_10-K-2025-As-Filed.pdf", "us_10k"),
        ("10Q-Q3-2026-as-filed.pdf", "us_10q"),
        ("2025AnnualReportA.pdf", "cn_a_share_annual"),
        ("8bf22346-dc4f-473c-bfac-a748db90f4d2.pdf", "hk_quarterly"),
    ]
    for path, rtype in tests:
        print(f"\n{'='*20} {path} ({rtype}) {'='*20}")
        out = run_extraction(path, rtype)
        for stmt, data in out.items():
            if "error" in data:
                print(f"  [{stmt}] {data['error']}")
            else:
                print(f"  [{stmt}] {len(data['items'])} 项数据, "
                      f"{len(data['dropped_noise'])} 项噪音已过滤")
