import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


BudgetPeriod = Literal["daily", "weekly", "monthly"]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EXPENSES_FILE = DATA_DIR / "expenses.json"
BUDGETS_FILE = DATA_DIR / "budgets.json"


class Expense(BaseModel):
    id: int
    amount: float
    category: str
    description: str
    spent_date: str = Field(default_factory=lambda: date.today().isoformat())
    created_at: str = Field(default_factory=lambda: _now_iso())

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("amount must be positive")
        return round(value, 2)

    @field_validator("category", "description")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("category and description cannot be empty")
        return clean_value

    @field_validator("spent_date")
    @classmethod
    def spent_date_must_be_iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise ValueError("spent_date must use YYYY-MM-DD format") from e
        return value


class Budget(BaseModel):
    category: str
    amount: float
    period: BudgetPeriod = "weekly"
    updated_at: str = Field(default_factory=lambda: _now_iso())

    @field_validator("category")
    @classmethod
    def category_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("category cannot be empty")
        return clean_value

    @field_validator("amount")
    @classmethod
    def budget_amount_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("amount must be positive")
        return round(value, 2)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_json_file(path: Path, default_value: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default_value, encoding="utf-8")


def _load_expenses() -> list[Expense]:
    _ensure_json_file(EXPENSES_FILE, "[]")

    try:
        raw_expenses = json.loads(EXPENSES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {EXPENSES_FILE}") from e

    if not isinstance(raw_expenses, list):
        raise ValueError(f"{EXPENSES_FILE} must contain a JSON list")

    return [Expense.model_validate(raw_expense) for raw_expense in raw_expenses]


def _save_expenses(expenses: list[Expense]) -> None:
    _ensure_json_file(EXPENSES_FILE, "[]")
    EXPENSES_FILE.write_text(
        json.dumps(
            [expense.model_dump(mode="json") for expense in expenses],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_budgets() -> list[Budget]:
    _ensure_json_file(BUDGETS_FILE, "[]")

    try:
        raw_budgets = json.loads(BUDGETS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {BUDGETS_FILE}") from e

    if not isinstance(raw_budgets, list):
        raise ValueError(f"{BUDGETS_FILE} must contain a JSON list")

    return [Budget.model_validate(raw_budget) for raw_budget in raw_budgets]


def _save_budgets(budgets: list[Budget]) -> None:
    _ensure_json_file(BUDGETS_FILE, "[]")
    BUDGETS_FILE.write_text(
        json.dumps(
            [budget.model_dump(mode="json") for budget in budgets],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def add_expense(
    amount: float,
    category: str,
    description: str,
    spent_date: str | None = None,
) -> Expense:
    expenses = _load_expenses()
    next_id = max((expense.id for expense in expenses), default=0) + 1
    expense = Expense(
        id=next_id,
        amount=amount,
        category=category,
        description=description,
        spent_date=spent_date or date.today().isoformat(),
    )

    expenses.append(expense)
    _save_expenses(expenses)
    return expense


def list_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[Expense]:
    expenses = _load_expenses()
    if start_date is not None:
        start = date.fromisoformat(start_date)
        expenses = [
            expense
            for expense in expenses
            if date.fromisoformat(expense.spent_date) >= start
        ]
    if end_date is not None:
        end = date.fromisoformat(end_date)
        expenses = [
            expense
            for expense in expenses
            if date.fromisoformat(expense.spent_date) <= end
        ]
    if category is not None:
        normalized_category = category.strip().lower()
        expenses = [
            expense
            for expense in expenses
            if expense.category.lower() == normalized_category
        ]

    expenses.sort(key=lambda item: (item.spent_date, item.id), reverse=True)
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        expenses = expenses[:limit]
    return expenses


def summarize_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
) -> dict[str, object]:
    expenses = list_expenses(
        start_date=start_date,
        end_date=end_date,
        category=category,
        limit=None,
    )
    category_totals: dict[str, float] = {}
    for expense in expenses:
        category_totals[expense.category] = round(
            category_totals.get(expense.category, 0) + expense.amount,
            2,
        )

    return {
        "count": len(expenses),
        "total_amount": round(sum(expense.amount for expense in expenses), 2),
        "category_totals": category_totals,
        "recent_expenses": [
            expense.model_dump(mode="json") for expense in expenses[:5]
        ],
    }


def set_budget(category: str, amount: float, period: BudgetPeriod = "weekly") -> Budget:
    budgets = _load_budgets()
    normalized_category = category.strip().lower()

    for index, budget in enumerate(budgets):
        if budget.category.lower() != normalized_category or budget.period != period:
            continue

        updated_budget = Budget(
            category=budget.category,
            amount=amount,
            period=period,
            updated_at=_now_iso(),
        )
        budgets[index] = updated_budget
        _save_budgets(budgets)
        return updated_budget

    budget = Budget(category=category, amount=amount, period=period)
    budgets.append(budget)
    _save_budgets(budgets)
    return budget


def get_budget(category: str, period: BudgetPeriod = "weekly") -> Budget | None:
    normalized_category = category.strip().lower()
    return next(
        (
            budget
            for budget in _load_budgets()
            if budget.category.lower() == normalized_category and budget.period == period
        ),
        None,
    )


def period_range(period: BudgetPeriod, anchor_date: str | None = None) -> tuple[str, str]:
    anchor = date.fromisoformat(anchor_date or date.today().isoformat())
    if period == "daily":
        start = anchor
        end = anchor
    elif period == "weekly":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
    else:
        start = anchor.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(days=1)

    return start.isoformat(), end.isoformat()
