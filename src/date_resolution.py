"""Pure date arithmetic for resolving natural language date descriptions."""

import contextlib
import re
from datetime import date, timedelta


def resolve_relative_date(description: str, today: date) -> date | None:
    """Resolve a natural language date description to a date object.

    Pure date arithmetic — no LiveKit or data dependencies.
    Returns None if the description cannot be resolved.
    """
    desc = description.lower().strip()
    day_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    # If description contains an ISO date, use it as the reference point
    # e.g. "the Friday before 2026-04-03" -> compute Friday relative to April 3rd
    reference_date = today
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", description)
    if iso_match:
        with contextlib.suppress(ValueError):
            reference_date = date.fromisoformat(iso_match.group(1))

    # "before" means go one additional week back past the nearest occurrence
    extra_weeks = 1 if "before" in desc else 0

    if desc in ("today",):
        return today
    elif desc in ("yesterday",):
        return today - timedelta(days=1)
    else:
        for day_name, weekday in day_map.items():
            if day_name in desc:
                days_back = (reference_date.weekday() - weekday) % 7
                if days_back == 0 and extra_weeks == 0:
                    days_back = 7  # "last X" when today is X means previous week
                days_back += extra_weeks * 7
                return reference_date - timedelta(days=days_back)

    return None
