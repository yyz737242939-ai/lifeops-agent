from typing import Literal

from pydantic import BaseModel


Energy = Literal["low", "medium", "high"]
Mood = Literal["bad", "neutral", "good"]
CostLevel = Literal["free", "low", "medium"]
Location = Literal["home", "nearby", "outside"]
ActivityGoal = Literal["recover", "focus", "socialize", "health", "fun"]


class Activity(BaseModel):
    """One deterministic local activity recommendation candidate."""

    id: int
    name: str
    duration_minutes: int
    cost_level: CostLevel
    energy_required: Energy
    locations: list[Location]
    goals: list[ActivityGoal]
    mood_fit: list[Mood]
    reason: str


ACTIVITIES = [
    Activity(
        id=1,
        name="20-minute walk",
        duration_minutes=20,
        cost_level="free",
        energy_required="low",
        locations=["nearby", "outside"],
        goals=["recover", "health", "focus"],
        mood_fit=["bad", "neutral", "good"],
        reason="Light movement can reset energy without making the day heavier.",
    ),
    Activity(
        id=2,
        name="Desk reset",
        duration_minutes=15,
        cost_level="free",
        energy_required="low",
        locations=["home"],
        goals=["focus", "recover"],
        mood_fit=["bad", "neutral"],
        reason="A small environment reset lowers friction before focused work.",
    ),
    Activity(
        id=3,
        name="Simple stretching",
        duration_minutes=10,
        cost_level="free",
        energy_required="low",
        locations=["home"],
        goals=["recover", "health"],
        mood_fit=["bad", "neutral", "good"],
        reason="Short mobility work is useful when energy is limited.",
    ),
    Activity(
        id=4,
        name="Deep work sprint",
        duration_minutes=45,
        cost_level="free",
        energy_required="medium",
        locations=["home"],
        goals=["focus"],
        mood_fit=["neutral", "good"],
        reason="A bounded sprint is easier to start than an open-ended work block.",
    ),
    Activity(
        id=5,
        name="Call a friend",
        duration_minutes=25,
        cost_level="free",
        energy_required="medium",
        locations=["home", "nearby"],
        goals=["socialize", "recover", "fun"],
        mood_fit=["bad", "neutral", "good"],
        reason="A short social check-in can improve mood without needing a big plan.",
    ),
    Activity(
        id=6,
        name="Low-cost cafe planning block",
        duration_minutes=60,
        cost_level="low",
        energy_required="medium",
        locations=["nearby", "outside"],
        goals=["focus", "fun"],
        mood_fit=["neutral", "good"],
        reason="A change of setting can help planning feel less stale.",
    ),
    Activity(
        id=7,
        name="Gym session",
        duration_minutes=60,
        cost_level="medium",
        energy_required="high",
        locations=["outside"],
        goals=["health", "fun"],
        mood_fit=["neutral", "good"],
        reason="Higher-energy exercise works best when the day has enough capacity.",
    ),
    Activity(
        id=8,
        name="No-spend home movie",
        duration_minutes=90,
        cost_level="free",
        energy_required="low",
        locations=["home"],
        goals=["recover", "fun"],
        mood_fit=["bad", "neutral", "good"],
        reason="Good for recovery when budget and energy are both constrained.",
    ),
]

COST_RANK = {"free": 0, "low": 1, "medium": 2}
ENERGY_RANK = {"low": 0, "medium": 1, "high": 2}


def _matches_activity(
    activity: Activity,
    *,
    max_cost: int,
    max_energy: int,
    available_minutes: int | None,
    location: Location | None,
    goal: ActivityGoal | None,
    mood: Mood | None,
) -> bool:
    """Apply hard constraints before preference scoring."""
    if (
        available_minutes is not None
        and activity.duration_minutes > available_minutes
    ):
        return False
    if COST_RANK[activity.cost_level] > max_cost:
        return False
    if ENERGY_RANK[activity.energy_required] > max_energy:
        return False
    if location is not None and location not in activity.locations:
        return False
    if goal is not None and goal not in activity.goals:
        return False
    if mood is not None and mood not in activity.mood_fit:
        return False
    return True


def _score_activity(
    activity: Activity,
    *,
    energy: Energy | None,
    mood: Mood | None,
    budget_level: CostLevel | None,
    goal: ActivityGoal | None,
) -> int:
    """Rank matching activities without turning preferences into hard filters."""
    score = 0
    if goal is not None and goal in activity.goals:
        score += 4
    if mood is not None and mood in activity.mood_fit:
        score += 2
    if energy is not None and activity.energy_required == energy:
        score += 1
    if budget_level is not None and activity.cost_level == budget_level:
        score += 1
    return score


def _activity_sort_key(item: tuple[int, Activity]) -> tuple[int, int, int]:
    score, activity = item
    return (-score, activity.duration_minutes, COST_RANK[activity.cost_level])


def recommend_activities(
    energy: Energy | None = None,
    mood: Mood | None = None,
    available_minutes: int | None = None,
    budget_level: CostLevel | None = None,
    location: Location | None = None,
    goal: ActivityGoal | None = None,
    limit: int = 3,
) -> list[Activity]:
    """Filter and rank activities using explicit constraints and preferences."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    max_cost = COST_RANK.get(budget_level, 2)
    max_energy = ENERGY_RANK.get(energy, 2)

    scored: list[tuple[int, Activity]] = []
    for activity in ACTIVITIES:
        if not _matches_activity(
            activity,
            max_cost=max_cost,
            max_energy=max_energy,
            available_minutes=available_minutes,
            location=location,
            goal=goal,
            mood=mood,
        ):
            continue
        scored.append(
            (
                _score_activity(
                    activity,
                    energy=energy,
                    mood=mood,
                    budget_level=budget_level,
                    goal=goal,
                ),
                activity,
            )
        )

    scored.sort(key=_activity_sort_key)
    return [activity for _, activity in scored[:limit]]
