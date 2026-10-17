"""A minimal module to test the engine on its own: pick a color, give a name, confirm."""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.conversation_schemas import CoreStep, Draft
from app.services.flow import Flow
from app.services.messenger import Messenger
from app.services.steps.base import (
    Context,
    InvalidInputError,
    Move,
    StaleDraftError,
    StepHandler,
    choice,
    pick,
)
from app.services.steps.name import NameStep
from app.utils.messages import options
from app.utils.texts import Text

BUSINESS_TYPE = "fake"
COLORS = ("Azul", "Verde")

WELCOME = Text("WELCOME", "Olá! Bem-vindo(a) à *{loja}*.")
START_LABEL = Text("START_LABEL", "Escolher cor")
CATALOG_LABEL = Text("CATALOG_LABEL", "Ver cores")
COLOR_QUESTION = Text("COLOR_QUESTION", options("Qual cor?", COLORS))
CANCELLED = Text("CANCELLED", "Cancelado.")
CATALOG = "Cores: Azul, Verde"


class FakeStep(StrEnum):
    COLOR = "fake_color"
    NAME = "fake_name"
    CONFIRM = "fake_confirm"


class FakeDraft(Draft):
    color: str | None = None


class ColorStep(StepHandler[FakeDraft]):
    step = FakeStep.COLOR
    previous = CoreStep.MAIN_MENU
    question = COLOR_QUESTION

    async def handle(self, ctx: Context[FakeDraft], answer: str) -> Move:
        if answer == "quebrar":
            # Stands in for a draft that no longer matches the catalog.
            raise StaleDraftError
        ctx.draft.color = pick(COLORS, answer)
        return Move(FakeStep.NAME)


class FakeNameStep(NameStep[FakeDraft]):
    step = FakeStep.NAME
    previous = FakeStep.COLOR
    next_step = FakeStep.CONFIRM


class ConfirmStep(StepHandler[FakeDraft]):
    step = FakeStep.CONFIRM
    previous = FakeStep.NAME

    async def handle(self, ctx: Context[FakeDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                return Move(say=(f"Feito, {ctx.draft.name}!",), ends=True)
            case 2:
                ctx.draft = FakeDraft()
                return Move(CoreStep.MAIN_MENU, notice=CANCELLED)
            case _:
                raise InvalidInputError

    async def render(self, ctx: Context[FakeDraft]) -> str:
        return options(f"Confirma {ctx.draft.color} para {ctx.draft.name}?", ["Sim", "Não"])


class FakeFlow(Flow[FakeDraft]):
    welcome = WELCOME
    start_label = START_LABEL
    catalog_label = CATALOG_LABEL

    def __init__(self, db: AsyncSession, messenger: Messenger) -> None:
        pass

    def draft(self, data: Mapping[str, Any] | None = None) -> FakeDraft:
        return FakeDraft() if data is None else FakeDraft.model_validate(data)

    def steps(self) -> Sequence[StepHandler[FakeDraft]]:
        return (ColorStep(), FakeNameStep(), ConfirmStep())

    async def start(self, ctx: Context[FakeDraft]) -> Move:
        return Move(FakeStep.COLOR)

    async def catalog(self, ctx: Context[FakeDraft]) -> str:
        return CATALOG
