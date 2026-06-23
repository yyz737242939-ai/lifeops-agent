from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.json_file import load_model_list, save_model_list
from app.utils.time import now_iso, today_iso


Mood = Literal["bad", "neutral", "good"]
Energy = Literal["low", "medium", "high"]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DAILY_LOGS_FILE = DATA_DIR / "daily_logs.json"


class DailyLog(BaseModel):
    log_date: str
    sleep_hours: float | None = None
    mood: Mood | None = None
    energy: Energy | None = None
    note: str | None = None
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("log_date")
    @classmethod
    def log_date_must_be_iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise ValueError("log_date must use YYYY-MM-DD format") from e
        return value

    @field_validator("sleep_hours")
    @classmethod
    def sleep_hours_must_be_reasonable(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0 or value > 24:
            raise ValueError("sleep_hours must be between 0 and 24")
        return value


def _load_logs() -> list[DailyLog]:
    return load_model_list(DAILY_LOGS_FILE, DailyLog)


def _save_logs(logs: list[DailyLog]) -> None:
    save_model_list(DAILY_LOGS_FILE, logs)


def upsert_daily_log(
    log_date: str | None = None,
    sleep_hours: float | None = None,
    mood: Mood | None = None,
    energy: Energy | None = None,
    note: str | None = None,
) -> DailyLog:
    target_date = log_date or today_iso()
    logs = _load_logs()

    for index, log in enumerate(logs):
        if log.log_date != target_date:
            continue

        update_data = log.model_dump()
        if sleep_hours is not None:
            update_data["sleep_hours"] = sleep_hours
        if mood is not None:
            update_data["mood"] = mood
        if energy is not None:
            update_data["energy"] = energy
        if note is not None:
            update_data["note"] = note
        update_data["updated_at"] = now_iso()

        updated_log = DailyLog.model_validate(update_data)
        logs[index] = updated_log
        _save_logs(logs)
        return updated_log

    log = DailyLog(
        log_date=target_date,
        sleep_hours=sleep_hours,
        mood=mood,
        energy=energy,
        note=note,
    )
    logs.append(log)
    logs.sort(key=lambda item: item.log_date)
    _save_logs(logs)
    return log


def get_daily_log(log_date: str | None = None) -> DailyLog | None:
    target_date = log_date or today_iso()
    return next((log for log in _load_logs() if log.log_date == target_date), None)


def list_daily_logs(days: int = 7, end_date: str | None = None) -> list[DailyLog]:
    if days < 1:
        raise ValueError("days must be at least 1")

    target_end = date.fromisoformat(end_date or today_iso())
    target_start = target_end - timedelta(days=days - 1)

    return [
        log
        for log in _load_logs()
        if target_start <= date.fromisoformat(log.log_date) <= target_end
    ]
