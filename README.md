# finance-report-skill

从财报 PDF（美股 10-K/10-Q、A 股年报/季报、港股年报/季报）提取关键财务数据、统一口径并生成表格/文档形式分析结论的 Claude Code / Codex skill。支持英文、简体中文、繁体中文报告。

## 现状

当前版本为 **v0.3 Universal Cross-Market Mode**，已在 8 份真实样本报告上逐项人工核对，覆盖 Apple、美股季报、小米港股公告与年报、比亚迪 A 股年报及工商银行报告。

输入任意 A 股、港股或美股财报时，可使用自动模式识别市场、语言和报告类型；跨报告比较时，`compare.py` 会统一常见字段、原始单位和币种。缺失汇率、低识别置信度及会计口径差异会显式提示，不会静默混算。分析仍然坚持数字和方向优先，不做估值或主观的“好/坏”判断。

## 快速开始

```bash
pip install -r requirements.txt
```

```python
from scripts.universal import extract_universal

result = extract_universal("path/to/report.pdf", report_type="auto")
print(result["detection"])  # 市场、语言、置信度和各类型得分
print(result["schema"])
```

跨市场比较：

```python
from scripts.compare import compare_reports, render_markdown

result = compare_reports(
    ["a_share_report.pdf", "hk_report.pdf", "us_report.pdf"],
    fx_to_cny={"USD": 7.2, "HKD": 0.92},
)
print(render_markdown(result))
```

命令行形式：

```bash
PYTHONPATH=scripts python3 scripts/compare.py a_share_report.pdf hk_report.pdf us_report.pdf --fx '{"USD":7.2,"HKD":0.92}'
```

`report_type` 仍支持显式指定 `us_10k` / `us_10q` / `cn_a_share_annual` / `cn_a_share_general` / `hk_quarterly` / `hk_annual`；推荐普通使用场景采用 `auto`。

## 示例输出

见 [examples/](./examples) 目录。

## 贡献

这是一个刚起步的项目，欢迎 PR。新增报告类型/公司前请先读 SKILL.md 里的"已知的坑"，
里面记录的都是实测踩过的问题（PDF中文提取工具选择、多页报表定位、字段映射子串冲突等）。

## License

MIT，见 [LICENSE](./LICENSE)。
