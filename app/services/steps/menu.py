from typing import Any

from app.schemas.conversation_schemas import CoreStep, Draft
from app.services.flow import Flow
from app.services.steps.base import Context, InvalidInputError, Move, StepHandler, choice
from app.utils import messages


class MainMenuStep(StepHandler[Draft]):
    """The first question of every session. The module fills options 1 and 2."""

    step = CoreStep.MAIN_MENU

    def __init__(self, flow: Flow[Any]) -> None:
        self.flow = flow

    async def handle(self, ctx: Context[Draft], answer: str) -> Move:
        match choice(answer):
            case 1:
                return await self.flow.start(ctx)
            case 2:
                return Move(say=(await self.flow.catalog(ctx),))
            case 3:
                return Move(CoreStep.HANDOFF)
            case _:
                raise InvalidInputError

    async def render(self, ctx: Context[Draft]) -> str:
        labels = [self.flow.start_label, self.flow.catalog_label, messages.ATTENDANT_OPTION]
        return messages.options(ctx.texts(messages.MAIN_MENU_TITLE), [ctx.texts(label) for label in labels], nav=())
