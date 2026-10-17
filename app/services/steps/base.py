import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from app.models import Conversation, Customer, StoreSettings
from app.schemas.conversation_schemas import Draft
from app.utils import messages
from app.utils.texts import Texts

# How long the chat shows "typing..." before each reply, in milliseconds.
WELCOME_DELAY_MS = 4000
DEFAULT_DELAY_MS = 2000
PAGINATION_DELAY_MS = 1000

# Lists with up to PAGINATE_ABOVE entries go out whole; longer ones are split into pages of PAGE_SIZE.
PAGE_SIZE = 15
PAGINATE_ABOVE = 30

_CHOICE = re.compile(r"\d{1,3}", re.ASCII)


class InvalidInputError(Exception):
    """The message is not an acceptable answer for the current step."""

    def __init__(self, hint: str = messages.INVALID) -> None:
        super().__init__(hint)
        self.hint = hint


class StaleDraftError(Exception):
    """The saved draft no longer matches the catalog, or lacks data the current step relies on."""


@dataclass
class Context[D: Draft]:
    store: StoreSettings
    customer: Customer
    conv: Conversation
    draft: D
    push_name: str | None
    texts: Texts
    # Set once the conversation row is gone (order or booking placed), so the draft is not written back.
    finished: bool = False


@dataclass(frozen=True)
class Move:
    """What a step decided: where the conversation goes and what is said on the way.

    `notice` and `say` may be Text constants: the engine applies the owner's wording to them.
    """

    # None stays on the current step and keeps its page.
    step: str | None = None
    notice: str | None = None
    delay_ms: int = DEFAULT_DELAY_MS
    # Messages sent before the next question.
    say: tuple[str, ...] = ()
    # The order or booking is placed: the conversation closes and nothing else is asked.
    ends: bool = False


@dataclass(frozen=True)
class Page:
    number: int
    start: int
    end: int
    count: int


class StepHandler[D: Draft](ABC):
    """One step of the flow: it asks its own question and reads the answer to it."""

    step: ClassVar[str]
    # The answer is typed freely, so only the exact one-character commands are intercepted.
    free_text: ClassVar[bool] = False
    # Where "voltar" leads when that never varies; without it the step is asked again.
    previous: ClassVar[str | None] = None
    # The question, when it is always the same text.
    question: ClassVar[str] = ""

    @abstractmethod
    async def handle(self, ctx: Context[D], answer: str) -> Move:
        """Applies the answer to the draft. Raises InvalidInputError when it is not an acceptable one."""

    async def render(self, ctx: Context[D]) -> str:
        return ctx.texts(self.question)

    def back(self, ctx: Context[D]) -> str:
        return self.previous or self.step


def choice(answer: str) -> int | None:
    return int(answer) if _CHOICE.fullmatch(answer) else None


def pick[T](choices: Sequence[T], answer: str) -> T:
    """The option the customer typed. Numbers are positions in the full list, not in the current page."""
    number = choice(answer)
    if number is None or not 1 <= number <= len(choices):
        raise InvalidInputError
    return choices[number - 1]


def required[T](value: T | None) -> T:
    if value is None:
        raise StaleDraftError
    return value


def paginate(total: int, requested: int) -> Page:
    if total <= PAGINATE_ABOVE:
        return Page(0, 0, total, 1)
    count = -(-total // PAGE_SIZE)
    number = min(requested, count - 1)
    return Page(number, number * PAGE_SIZE, min((number + 1) * PAGE_SIZE, total), count)


def turn_page(draft: Draft, answer: str, total: int) -> bool:
    """Applies M (next) / A (previous) to a paginated list. True when the page changed."""
    page = paginate(total, draft.page)
    command = answer.casefold()
    if command in {"m", "mais"} and page.number + 1 < page.count:
        draft.page = page.number + 1
    elif command in {"a", "anterior"} and page.number > 0:
        draft.page = page.number - 1
    else:
        return False
    return True
