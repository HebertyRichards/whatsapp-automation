from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.conversation_schemas import Draft
from app.services.messenger import Messenger
from app.services.steps.base import Context, Move, StepHandler
from app.utils.texts import Text


class Flow[D: Draft](ABC):
    """A business module as the conversation engine sees it. Built per database session, like its steps.

    The engine owns the session, the main menu, the global commands and the hand-off; the module owns
    everything between "1" on the main menu and the order or booking being placed.
    """

    # Sent when a session opens; {loja} is the store name.
    welcome: ClassVar[Text]
    # Main menu options 1 and 2. Option 3 is always the attendant.
    start_label: ClassVar[Text]
    catalog_label: ClassVar[Text]

    @abstractmethod
    def draft(self, data: Mapping[str, Any] | None = None) -> D:
        """A fresh draft, or the saved one. Raises ValueError when `data` no longer fits."""

    @abstractmethod
    def steps(self) -> Sequence[StepHandler[D]]:
        """Every step the module asks. Their `step` ids must not collide with CoreStep."""

    @abstractmethod
    async def start(self, ctx: Context[D]) -> Move:
        """Main menu option 1."""

    @abstractmethod
    async def catalog(self, ctx: Context[D]) -> str:
        """Main menu option 2: what is on offer, in one message."""


# How the composition root builds a module for one database session.
type FlowFactory = Callable[[AsyncSession, Messenger], Flow[Any]]
