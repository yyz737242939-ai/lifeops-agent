from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.json_file import load_model_list, save_model_list
from app.utils.time import now_iso


BudgetPeriod = Literal["daily", "weekly", "monthly"]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EXPENSES_FILE = DATA_DIR / "expenses.json"
BUDGETS_FILE = DATA_DIR / "budgets.json"


class Expense(BaseModel):
    """Persisted spending record with normalized amount and date."""

    id: int
    amount: float
    category: str
    description: str
    spent_date: str = Field(default_factory=lambda: date.today().isoformat())
    created_at: str = Field(default_factory=now_iso)

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
    """Category budget scoped to a daily, weekly, or monthly period."""

    category: str
    amount: float
    period: BudgetPeriod = "weekly"
    updated_at: str = Field(default_factory=now_iso)

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


def _load_expenses() -> list[Expense]:
    return load_model_list(EXPENSES_FILE, Expense)


def _save_expenses(expenses: list[Expense]) -> None:
    save_model_list(EXPENSES_FILE, expenses)


def _load_budgets() -> list[Budget]:
    return load_model_list(BUDGETS_FILE, Budget)


def _save_budgets(budgets: list[Budget]) -> None:
    save_model_list(BUDGETS_FILE, budgets)


def add_expense(
    amount: float,
    category: str,
    description: str,
    spent_date: str | None = None,
) -> Expense:
    """Persist a normalized expense with the next local identifier."""
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
    """Filter expenses and return newest records first."""
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
    """Aggregate filtered spending while retaining a short recent sample."""
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
    """Create or replace the budget for one normalized category and period."""
    budgets = _load_budgets()
    normalized_category = category.strip().lower()

    for index, budget in enumerate(budgets):
        if budget.category.lower() != normalized_category or budget.period != period:
            continue

        updated_budget = Budget(
            category=budget.category,
            amount=amount,
            period=period,
            updated_at=now_iso(),
        )
        budgets[index] = updated_budget
        _save_budgets(budgets)
        return updated_budget

    budget = Budget(category=category, amount=amount, period=period)
    budgets.append(budget)
    _save_budgets(budgets)
    return budget


def get_budget(category: str, period: BudgetPeriod = "weekly") -> Budget | None:
    """Look up one category budget case-insensitively."""
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
    """Return inclusive ISO date boundaries for a budget period."""
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
