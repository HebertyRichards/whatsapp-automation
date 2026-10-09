from collections.abc import Sequence
from datetime import datetime, timedelta

from app.models import OpeningHours


def is_open(hours: Sequence[OpeningHours], now: datetime) -> bool:
    """`now` must be in the store's timezone.

    A shift whose closing time is at or before its opening time runs past midnight,
    so the early hours of a day belong to the previous day's shift.
    """
    by_weekday = {shift.weekday: shift for shift in hours}
    current = now.time()

    today = by_weekday.get(now.isoweekday())
    if today is not None:
        if today.opens_at < today.closes_at:
            if today.opens_at <= current < today.closes_at:
                return True
        elif current >= today.opens_at:
            return True

    yesterday = by_weekday.get((now - timedelta(days=1)).isoweekday())
    return yesterday is not None and yesterday.closes_at <= yesterday.opens_at and current < yesterday.closes_at


def next_opening(hours: Sequence[OpeningHours], now: datetime) -> datetime | None:
    """Start of the next shift after `now`, or None when no shift is configured."""
    by_weekday = {shift.weekday: shift for shift in hours}
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        shift = by_weekday.get(day.isoweekday())
        if shift is None:
            continue
        opening = datetime.combine(day, shift.opens_at, tzinfo=now.tzinfo)
        if opening > now:
            return opening
    return None
