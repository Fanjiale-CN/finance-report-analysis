"""Universal mode regression tests.

样本 PDF 不随仓库发布；运行前可设置 FRA_SAMPLES 指向本地样本目录。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from universal import detect_report_type, extract_universal
from compare import compare_reports

samples = Path(os.environ.get("FRA_SAMPLES", HERE / "samples"))
cases = [
    ("byd_ar_2025.pdf", "cn_a_share_general"),
    ("xiaomi_ar_2025.pdf", "hk_annual"),
    ("xiaomi_1q2026_notice.pdf", "hk_quarterly"),
]
passes = 0
skips = 0
failures = []
for filename, expected in cases:
    path = samples / filename
    if not path.exists():
        print(f"[SKIP] {filename}: sample not found")
        skips += 1
        continue
    detected = detect_report_type(path)
    if detected["report_type"] != expected or detected["confidence"] not in ("high", "manual"):
        failures.append(f"{filename}: detected={detected}")
        continue
    result = extract_universal(path)
    if not result["schema"]:
        failures.append(f"{filename}: empty schema")
        continue
    print(f"[PASS] {filename}: {expected}")
    passes += 1

available = [str(samples / name) for name, _ in cases if (samples / name).exists()]
if len(available) >= 2:
    compared = compare_reports(available)
    if not compared["fields"]:
        failures.append("compare: no normalized fields")
    else:
        print(f"[PASS] compare: {len(compared['fields'])} normalized fields")
        passes += 1
else:
    print("[SKIP] compare: fewer than two samples")
    skips += 1

print(f"{passes} passed, {skips} skipped, {len(failures)} failed")
if failures:
    print("\n".join(failures))
    raise SystemExit(1)
