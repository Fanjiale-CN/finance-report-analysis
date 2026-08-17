"""统一财报数据契约。

该模块只定义数据结构和完整性规则，不负责 PDF/HTML 解析。解析器、标准化器和比较器
通过这些结构交换数据，避免在缺字段时抛出裸 KeyError 或静默填零。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Severity = Literal["info", "warning", "error"]
StatementKind = Literal["income_statement", "balance_sheet", "cash_flow", "key_ratios"]


@dataclass
class ParseIssue:
    code: str
    message: str
    severity: Severity = "warning"
    statement: str | None = None
    page: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinancialLineItem:
    canonical: str | None
    label: str
    values: list[float | None]
    periods: list[str] = field(default_factory=list)
    unit: str | None = None
    currency: str | None = None
    source_page: int | None = None
    confidence: float = 1.0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinancialStatement:
    kind: StatementKind
    title: str | None = None
    periods: list[str] = field(default_factory=list)
    unit: str | None = None
    currency: str | None = None
    accounting_standard: str | None = None
    consolidation: str | None = "consolidated"
    items: list[FinancialLineItem] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)
    complete: bool = False
    issues: list[ParseIssue] = field(default_factory=list)

    def completeness(self, minimum_items: int = 3) -> dict[str, Any]:
        usable = sum(1 for item in self.items if any(v is not None for v in item.values))
        errors = [issue for issue in self.issues if issue.severity == "error"]
        complete = usable >= minimum_items and not errors
        return {
            "complete": complete,
            "usable_items": usable,
            "minimum_items": minimum_items,
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass
class FinancialReport:
    source: str
    company: str | None
    market: str | None
    report_type: str | None
    language: str | None
    fiscal_period: str | None
    currency: str | None
    unit: str | None
    accounting_standard: str | None
    consolidation: str | None
    detection_confidence: str
    statements: dict[str, FinancialStatement] = field(default_factory=dict)
    issues: list[ParseIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def completeness(self) -> dict[str, Any]:
        statement_results = {
            name: statement.completeness()
            for name, statement in self.statements.items()
        }
        required = ("income_statement", "balance_sheet", "cash_flow")
        missing = [name for name in required if name not in self.statements]
        incomplete = [
            name for name, result in statement_results.items()
            if not result["complete"]
        ]
        errors = [issue for issue in self.issues if issue.severity == "error"]
        return {
            "complete": not missing and not incomplete and not errors,
            "missing_statements": missing,
            "incomplete_statements": incomplete,
            "statements": statement_results,
            "issues": [asdict(issue) for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def issue(code: str, message: str, severity: Severity = "warning", **kwargs: Any) -> ParseIssue:
    return ParseIssue(code=code, message=message, severity=severity, **kwargs)


def safe_failure(source: str, message: str, code: str = "parse_failed") -> dict[str, Any]:
    """返回可序列化的失败对象，供 CLI/API 使用，而不是抛裸异常。"""
    return {
        "status": "error",
        "source": source,
        "error": {"code": code, "message": message},
        "schema": {},
        "statements": {},
        "issues": [asdict(issue(code, message, "error"))],
    }
