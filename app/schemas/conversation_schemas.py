from enum import StrEnum

from pydantic import BaseModel


class CoreStep(StrEnum):
    """Steps every business has. Each module names its own in its schemas."""

    MAIN_MENU = "main_menu"
    HANDOFF = "handoff"


class Draft(BaseModel):
    """What the conversation collected so far, stored as JSON on it. Each module extends it with its own fields.

    Every field needs a default: a fresh draft is built with no arguments.
    """

    page: int = 0
    name: str | None = None
