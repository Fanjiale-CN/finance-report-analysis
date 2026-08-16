"""
财报提取流水线 v0.1
定位关键页 -> PyMuPDF提取文本 -> 逐行解析为结构化数据

用法示例见文件底部 __main__。
依赖: pip install pymupdf --break-system-packages
"""
import json
import pymupdf
from statement_parser import parse_statement, clean_lines, VALUE_RE, to_number


def find_pages(doc, keywords):
    """在全篇文档中按关键词定位页码（1-indexed）。返回 {keyword: [page_no, ...]}。
    支持跨行标题：若关键词内部无换行且单页未命中，会按行拆分后检查关键词是否
    以"前缀在行尾、后缀在下一行"的形式跨行出现（如 "CONSOLIDATED INCOME\nSTATEMENT"）。"""
    hits = {}
    for i, page in enumerate(doc):
        text = page.get_text()
        for kw in keywords:
            if kw in text:
                hits.setdefault(kw, []).append(i + 1)
                continue
            # 跨行匹配：关键词按空格拆分后，相邻行拼起来包含关键词
            # （"CONSOLIDATED STATEMENT OF\nCASH FLOWS" 即相邻行拼接命中）
            if " " in kw:
                parts = kw.split(" ")
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                joined = " ".join(lines)
                if kw in joined:
                    hits.setdefault(kw, []).append(i + 1)
                    continue
                # 放宽：行与行之间拼接（去掉空格）也可能命中
                for a, b in zip(lines, lines[1:]):
                    if a.endswith(parts[0]) and b.startswith(parts[-1]):
                        hits.setdefault(kw, []).append(i + 1)
                        break
    return hits


def extract_statement(doc, page_nos, n_periods, strip_before=None, strip_after=None):
    """给定一个或多个连续页码（1-indexed），拼接文本后解析为结构化行项目。
    strip_before / strip_after: 可选的文本锚点，只保留锚点之间的内容（用于剔除
    页眉页脚或表后附注等噪音）。当报表横跨多页（span>1）时，每页会先单独剔除
    该页自身的页头噪音再拼接，避免第二页以后的页眉被当成数据。
    """
    texts = []
    for i, p in enumerate(page_nos):
        t = doc[p - 1].get_text()
        # 每页单独裁掉页头：strip_before 只在首页全文应用一次；后续页若包含
        # strip_before 锚点（如第二页重复的表头段），同样裁掉锚点之前内容。
        if i > 0 and strip_before:
            idx = t.find(strip_before)
            if idx != -1:
                t = t[idx:]
        texts.append(t)
    text = "\n".join(texts)
    if strip_before:
        idx = text.find(strip_before)
        if idx != -1:
            text = text[idx:]
    if strip_after:
        idx = text.find(strip_after)
        if idx != -1:
            text = text[:idx]
    items = parse_statement(text, n_periods)
    # 过滤噪音：
    # 1) 页眉页码噪音（label短 + IRREGULAR(1) + 值像页码<500）
    # 2) 年份表头行：值全部落在 1950-2099 之间（"2025 / 2024" 被当成数据）
    # 3) 跨页拼接时页码混入数据行：报表正文末尾紧跟的页码（如 271）会被解析
    #    器判为 footnote，真实首值被贬为 footnote、其余值整体错位。修复：
    #    若行有 footnote 且最后一值落在页码量级（100, 1000）之间，把 footnote
    #    挪回 values 首位、丢弃该页码尾部值。
    # 4) 表头单位行混并：label 含 "RMB" 的行（港股）或 "000" 单位字样的行，
    #    其数值来自表头行（2025/2024），不是报表数据。
    clean_items = []
    dropped = []
    for it in items:
        if (it["footnote"] and "IRREGULAR" in str(it["footnote"])
                and len(it["values"]) <= 1):
            dropped.append(it)
            continue
        vals = [v for v in it["values"] if v is not None]
        if vals and all(1950 <= v <= 2099 for v in vals) and len(vals) >= 2:
            dropped.append(it)
            continue
        # 页码混入修复
        if it["footnote"] is not None and len(it["values"]) >= 2:
            last = it["values"][-1]
            if last is not None and 100 < last < 1000:
                fn = it["footnote"]
                fn_num = to_number(str(fn))
                if fn_num is not None:
                    it["values"] = [fn_num] + it["values"][:-1]
                    it["footnote"] = None
        # 表头单位行丢弃：label 以单位字样（RMB'000 等）开头且长度很短
        # （<8 字符，如 "RMB'000RMB'000Liabilities..." 这种被 strip_before
        # 漏掉的整段合并行），或者 label 本身就是纯单位字样。含真实科目名的
        # 长标签（如 "RMB'000Revenue5"）在下面单独剥除单位前缀后保留。
        import re as _re
        _raw_label = it["label"]
        stripped = _re.sub(r"^(RMB’?000|RMB’?000RMB’?000)\s*", "", _raw_label)
        if _raw_label != stripped:
            # 单位与首个科目行合并：剥掉单位前缀
            if len(stripped) >= 3:
                it["label"] = stripped
            else:
                dropped.append(it)
                continue
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
    "hk_annual": {
        # 港股年报英文报表标题常跨行（"CONSOLIDATED INCOME\nSTATEMENT"），
        # 用 all_keywords 要求 "INCOME STATEMENT" 与年度锚点同页出现才命中。
        "income_statement": {
            "all_keywords": ["INCOME STATEMENT", "For the year ended December 31"],
            "n_periods": 2, "strip_after": "The notes",
        },
        "balance_sheet": {
            "keyword": "CONSOLIDATED BALANCE SHEET", "n_periods": 2,
            "span_pages": 2, "strip_before": "Assets",
            "strip_after": "The notes",
        },
        "cash_flow": {
            "keyword": "CONSOLIDATED STATEMENT OF CASH FLOWS", "n_periods": 2,
            "span_pages": 2,
            "strip_before": "Cash flows from operating",
            "strip_after": "The notes",
        },
    },
    "cn_a_share_general": {
        "income_statement": {
            "keyword": "合并利润表", "n_periods": 2,
            "strip_before": "合并利润表",
            "strip_after": "后附财务报表附注",
        },
        "balance_sheet": {
            "keyword": "合并资产负债表", "n_periods": 2, "span_pages": 3,
            "strip_before": "合并资产负债表",
            "strip_after": "后附财务报表附注",
        },
        "cash_flow": {
            "keyword": "合并现金流量表", "n_periods": 2, "span_pages": 2,
            "strip_before": "合并现金流量表",
            "strip_after": "后附财务报表附注",
        },
    },
}


def _numeric_density(doc, page_no):
    """粗略判断一页里"看起来像数据"的行有多少——用来在多个关键词命中页中
    挑出真正的报表正文页，排除目录/引用提及等噪音页。"""
    lines = clean_lines(doc[page_no - 1].get_text())
    return sum(1 for l in lines if VALUE_RE.match(l))


def _keyword_in_text(kw, text):
    """检查关键词是否在文本中（含跨行标题匹配）。"""
    if kw in text:
        return True
    if " " in kw:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if kw in " ".join(lines):
            return True
        parts = kw.split(" ")
        for a, b in zip(lines, lines[1:]):
            if a.endswith(parts[0]) and b.startswith(parts[-1]):
                return True
    return False


def _find_page_by_all_keywords(doc, keywords):
    """要求多个关键词在同一页同时出现才算命中——用于关键词本身在全文重复
    出现（如"不良贷款率"在多张明细表里都会提到）、单关键词无法唯一定位的场景。
    支持跨行标题匹配。"""
    for i, page in enumerate(doc):
        text = page.get_text()
        if all(_keyword_in_text(kw, text) for kw in keywords):
            return i + 1
    return None


def run_extraction(pdf_path, report_type):
    if report_type not in REPORT_CONFIGS:
        raise ValueError(
            f"未知的 report_type: {report_type}。"
            f"支持的类型: {sorted(REPORT_CONFIGS.keys())}"
        )
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
        ("xiaomi_ar_2025.pdf", "hk_annual"),
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
