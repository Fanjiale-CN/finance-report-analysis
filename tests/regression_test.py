"""回归测试：覆盖所有支持的 report_type × 可用样本，
验证核心字段提取值与已知正确基准一致。

用法:
    python3 tests/regression_test.py                 # 用 tests/samples/ 下的样本
    FRA_SAMPLES=/path/to/pdfs python3 tests/regression_test.py  # 自定义样本目录

注意: 样本 PDF 版权不属于本项目，tests/samples/ 默认不放报告原件，
      使用者把报告放进目录（或指向 FRA_SAMPLES）后自行运行。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

from extract import run_extraction
from analyze import build_schema

SAMPLES = os.environ.get('FRA_SAMPLES', os.path.join(HERE, 'samples'))


def find(*names):
    for n in names:
        p = os.path.join(SAMPLES, n)
        if os.path.exists(p):
            return p
    return None


CASES = [
    # 港股季报（利润表，繁中）— 小米集团 2026Q1 业绩公告
    # 样本文件: xiaomi_1q2026_notice.pdf（小米 2026Q1 公告，官网下载）
    ("小米2026Q1公告 hk_quarterly", find('xiaomi_1q2026_notice.pdf'), 'hk_quarterly',
     [('revenue', 99141618.0), ('net_income', 4734636.0)]),
    # 港股年报（英文，三大报表）— 小米集团 2025 年报
    # 样本文件: xiaomi_ar_2025.pdf（HKEXnews 2026-04-28 年报）
    ("小米2025年报 hk_annual", find('xiaomi_ar_2025.pdf'), 'hk_annual',
     [('revenue', 457286687.0), ('net_income', 41566439.0),
      ('total_assets', 508095967.0), ('cash_from_operations', 34142377.0)]),
    # A股非银行通用 — 比亚迪 2025 年报
    # 样本文件: byd_ar_2025.pdf（巨潮资讯网 2026-03-27 年报）
    ("比亚迪2025年报 cn_a_share_general", find('byd_ar_2025.pdf'), 'cn_a_share_general',
     [('revenue', 803964958.0), ('net_income', 33760758.0),
      ('total_assets', 883729883.0), ('cash_from_operations', 59135544.0)]),
]

TOL = 0.001
failures, passes, skipped = [], 0, 0

for label, pdf, rtype, expects in CASES:
    if pdf is None:
        skipped += 1
        print(f"[SKIP] {label}: samples/ 下未放样本报告")
        continue
    try:
        out = run_extraction(pdf, rtype)
    except Exception as e:
        failures.append(f"{label}: run_extraction 异常: {e}")
        continue
    schema = build_schema(out, rtype)
    if not schema:
        failures.append(f"{label}: schema 为空")
        continue
    ok = True
    for field, exp in expects:
        d = schema.get(field)
        if not d:
            failures.append(f"{label}: {field} 缺失")
            ok = False
            continue
        v = d['values'][0]
        if v is None or abs(v - exp) / abs(exp) > TOL:
            failures.append(f"{label}: {field}={v} != {exp}")
            ok = False
    if ok:
        passes += 1
        print(f"[PASS] {label}")
    else:
        print(f"[FAIL] {label}")

# 未知类型护栏
any_pdf = next((c[1] for c in CASES if c[1]), None)
if any_pdf:
    try:
        run_extraction(any_pdf, 'garbage_type')
        failures.append("未知类型护栏: 未报错")
    except ValueError:
        passes += 1
        print("[PASS] 未知类型护栏 ValueError")

print(f"\n{passes} passed, {skipped} skipped, {len(failures)} failed")
if failures:
    print('\n'.join(failures))
    sys.exit(1)
