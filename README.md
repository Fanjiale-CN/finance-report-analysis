# finance-report-skill

从财报PDF（美股10-K/10-Q、A股年报/季报、港股季报）提取关键财务数据并生成表格/文档形式分析结论的
Claude Code / Codex skill。支持英文、简体中文、繁体中文报告。

## 现状

早期版本（v0.1），已在5份真实样本报告上逐项人工核对过提取准确率：
- Apple 10-K（FY2025）、Apple 10-Q（FY26 Q3）
- 小米集团季报（2026Q1，港股）
- 中国工商银行年报（FY2025）、一季报（2026Q1，A股）

分析深度目前刻意做得比较浅（同比增速+方向性描述），详见 [SKILL.md](./SKILL.md) 里的
"现状与边界"和"已知的坑"两节——踩过的问题都记录在那，方便贡献者不重复踩。

## 快速开始

```bash
pip install -r requirements.txt
```

```python
from scripts.extract import run_extraction
from scripts.analyze import build_schema, render_markdown_table, render_narrative

result = run_extraction("path/to/report.pdf", report_type="us_10k")
schema = build_schema(result, "us_10k")
print(render_markdown_table(schema, "us_10k", "公司名/报告期"))
print(render_narrative(schema, "us_10k", "公司名/报告期"))
```

`report_type` 目前支持 `us_10k` / `us_10q` / `cn_a_share_annual` / `hk_quarterly`，
详见 [SKILL.md](./SKILL.md)。

## 示例输出

见 [examples/](./examples) 目录。

## 贡献

这是一个刚起步的项目，欢迎 PR。新增报告类型/公司前请先读 SKILL.md 里的"已知的坑"，
里面记录的都是实测踩过的问题（PDF中文提取工具选择、多页报表定位、字段映射子串冲突等）。

## License

MIT，见 [LICENSE](./LICENSE)。
