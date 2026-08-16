import re
import pymupdf  # 本模块不直接使用 fitz；__main__ 中的示例保留 pymupdf 打开 PDF

VALUE_RE = re.compile(r'^\$?\s*\(?-?[\d,]+\.?\d*\)?%?$|^[-–—]$')

def clean_lines(text):
    lines = [l.strip() for l in text.split('\n')]
    # drop pure "$" or empty lines
    return [l for l in lines if l and l != '$']

def to_number(tok):
    neg = tok.startswith('(') and tok.endswith(')')
    t = tok.strip('()$ %').replace(',', '')
    if t in ('-', '–', ''):
        return 0.0
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v

def parse_statement(text, n_periods):
    """Parse a label-then-N-numbers style financial statement page.
    Returns list of dicts: {label, footnote, values: [n_periods floats]}
    """
    lines = clean_lines(text)
    items = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if VALUE_RE.match(line):
            i += 1
            continue  # stray numeric line before any label (e.g. page header numbers)
        # treat as label; join any wrapped continuation lines (non-numeric)
        # before the numeric run starts
        label_parts = [line]
        j = i + 1
        while j < n and not VALUE_RE.match(lines[j]):
            label_parts.append(lines[j])
            j += 1
        label = ''.join(label_parts)
        run = []
        while j < n and VALUE_RE.match(lines[j]):
            run.append(lines[j])
            j += 1
        if len(run) == n_periods:
            items.append({"label": label, "footnote": None,
                          "values": [to_number(v) for v in run]})
        elif len(run) == n_periods + 1:
            items.append({"label": label, "footnote": run[0],
                          "values": [to_number(v) for v in run[1:]]})
        elif len(run) == 0:
            pass  # header/section label with no numbers, skip storing as data row
        else:
            items.append({"label": label, "footnote": "IRREGULAR(%d)" % len(run),
                          "values": [to_number(v) for v in run]})
        i = j
    return items

if __name__ == "__main__":
    doc = pymupdf.open("_10-K-2025-As-Filed.pdf")
    apple_text = doc[31].get_text()
    print("=== Apple 10-K Income Statement (n_periods=3) ===")
    for it in parse_statement(apple_text, 3):
        print(it)

    doc2 = pymupdf.open("2025AnnualReportA.pdf")
    icbc_text = doc2[144].get_text()
    print("\n=== ICBC 合并及公司利润表 (n_periods=4) ===")
    for it in parse_statement(icbc_text, 4):
        print(it)
