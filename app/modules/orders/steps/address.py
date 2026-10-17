import re

from app.modules.orders import messages
from app.modules.orders.cep_service import CepService, CepUnavailableError
from app.modules.orders.schemas import OrderDraft, OrderStep
from app.services.steps.base import Context, InvalidInputError, Move, StepHandler, choice, required

_NON_DIGIT = re.compile(r"\D", re.ASCII)
_NO_NUMBER = frozenset({"s/n", "sn", "sem numero", "sem número"})
# A typed address must read "street, number": the comma is what tells the two apart.
_STREET_AND_NUMBER = re.compile(r"[^\W\d_].*?,\s*(\d|s/?n\b)", re.IGNORECASE)


def _finish(draft: OrderDraft, complement: str | None) -> Move:
    lookup = required(draft.lookup)
    lookup.complement = complement
    draft.address = messages.address_line(lookup)
    return Move(OrderStep.PAYMENT)


class CepStep(StepHandler[OrderDraft]):
    step = OrderStep.ADDRESS_CEP
    previous = OrderStep.FULFILLMENT
    question = messages.CEP

    def __init__(self, cep: CepService) -> None:
        self.cep = cep

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        if choice(answer) == 1:
            return Move(OrderStep.ADDRESS)
        cep = _NON_DIGIT.sub("", answer)
        if len(cep) != 8:
            raise InvalidInputError(messages.CEP_INVALID)
        try:
            found = await self.cep.find(cep)
        except CepUnavailableError:
            # A third-party outage must not block delivery orders.
            return Move(OrderStep.ADDRESS, notice=messages.CEP_UNAVAILABLE)
        if found is None:
            raise InvalidInputError(messages.CEP_NOT_FOUND)
        if not found.street:
            return Move(OrderStep.ADDRESS, notice=messages.CEP_WITHOUT_STREET)
        ctx.draft.lookup = found
        return Move(OrderStep.ADDRESS_CONFIRM)


class AddressConfirmStep(StepHandler[OrderDraft]):
    step = OrderStep.ADDRESS_CONFIRM
    previous = OrderStep.ADDRESS_CEP

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                return Move(OrderStep.ADDRESS_NUMBER)
            case 2:
                return Move(OrderStep.ADDRESS_CEP)
            case _:
                raise InvalidInputError

    async def render(self, ctx: Context[OrderDraft]) -> str:
        return messages.address_confirm(required(ctx.draft.lookup))


class AddressNumberStep(StepHandler[OrderDraft]):
    step = OrderStep.ADDRESS_NUMBER
    previous = OrderStep.ADDRESS_CEP
    free_text = True
    question = messages.ADDRESS_NUMBER

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        number = " ".join(answer.split())
        has_number = any(char.isdigit() for char in number) or number.casefold() in _NO_NUMBER
        if not 1 <= len(number) <= 10 or not has_number:
            raise InvalidInputError(messages.NUMBER_INVALID)
        required(ctx.draft.lookup).number = number
        return Move(OrderStep.ADDRESS_COMPLEMENT)


class AddressComplementStep(StepHandler[OrderDraft]):
    step = OrderStep.ADDRESS_COMPLEMENT
    previous = OrderStep.ADDRESS_NUMBER
    question = messages.ADDRESS_COMPLEMENT

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                return _finish(ctx.draft, None)
            case 2:
                return Move(OrderStep.ADDRESS_COMPLEMENT_TEXT)
            case _:
                raise InvalidInputError


class AddressComplementTextStep(StepHandler[OrderDraft]):
    step = OrderStep.ADDRESS_COMPLEMENT_TEXT
    previous = OrderStep.ADDRESS_COMPLEMENT
    free_text = True
    question = messages.ADDRESS_COMPLEMENT_TEXT

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        complement = " ".join(answer.split())
        if not 1 <= len(complement) <= 100:
            raise InvalidInputError(messages.COMPLEMENT_INVALID)
        return _finish(ctx.draft, complement)


class TypedAddressStep(StepHandler[OrderDraft]):
    """The whole address in one message: the way out when the postal code is unknown or cannot be looked up."""

    step = OrderStep.ADDRESS
    previous = OrderStep.ADDRESS_CEP
    free_text = True
    question = messages.ADDRESS

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        address = " ".join(answer.split())
        if not 5 <= len(address) <= 300 or not _STREET_AND_NUMBER.search(address):
            raise InvalidInputError(messages.ADDRESS_INVALID)
        ctx.draft.lookup, ctx.draft.address = None, address
        return Move(OrderStep.PAYMENT)
