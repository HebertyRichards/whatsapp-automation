"""Pure helpers: owner texts, opening hours."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.models import OpeningHours
from app.utils.schedule import is_open, next_opening
from app.utils.texts import Text, Texts

GREETING = Text("GREETING", "Olá, {nome}!")


def test_texts_use_the_override_by_key_and_fill_known_fields() -> None:
    assert Texts()(GREETING, nome="Ana") == "Olá, Ana!"
    assert Texts({"GREETING": "Oi {nome}, {outro}"})(GREETING, nome="Ana") == "Oi Ana, {outro}"
    assert Texts({"GREETING": "Oi"})("plain text") == "plain text"
    assert type(Texts()(GREETING)) is str


_TZ = ZoneInfo("America/Sao_Paulo")
# Tuesday to Sunday, 18:00 to 04:00 the next day.
_SHIFTS = [OpeningHours(weekday=day, opens_at=time(18), closes_at=time(4)) for day in range(2, 8)]


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    # October 2026: the 5th is a Monday.
    return datetime(2026, 10, day, hour, minute, tzinfo=_TZ)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_at(5, 1), True),  # Monday 01:00 belongs to Sunday's shift
        (_at(5, 3, 59), True),
        (_at(5, 4), False),
        (_at(5, 18), False),  # no Monday shift
        (_at(6, 1), False),
        (_at(6, 17, 59), False),
        (_at(6, 18), True),
        (_at(7, 3, 59), True),
        (_at(7, 4), False),
        (_at(11, 23), True),
    ],
)
def test_is_open(moment: datetime, expected: bool) -> None:
    assert is_open(_SHIFTS, moment) is expected


def test_next_opening() -> None:
    assert next_opening(_SHIFTS, _at(5, 10)) == _at(6, 18)
    assert next_opening(_SHIFTS, _at(6, 10)) == _at(6, 18)
    assert next_opening(_SHIFTS, _at(7, 5)) == _at(7, 18)
    assert next_opening([], _at(7, 5)) is None
