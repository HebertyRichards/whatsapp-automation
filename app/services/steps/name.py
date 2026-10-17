from typing import ClassVar

from app.schemas.conversation_schemas import Draft
from app.services.steps.base import Context, InvalidInputError, Move, StepHandler
from app.utils import messages


class NameStep[D: Draft](StepHandler[D]):
    """Asks the customer's name. A module subclasses it to set `step`, `previous` and `next_step`."""

    free_text = True
    question = messages.NAME
    next_step: ClassVar[str]

    async def handle(self, ctx: Context[D], answer: str) -> Move:
        name = " ".join(answer.split())
        if not 2 <= len(name) <= 80 or not any(char.isalpha() for char in name):
            raise InvalidInputError(messages.NAME_INVALID)
        ctx.draft.name = name
        return Move(self.next_step)
