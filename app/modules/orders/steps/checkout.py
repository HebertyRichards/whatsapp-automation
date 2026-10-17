import logging

from app.errors import AppException
from app.modules.orders import messages
from app.modules.orders.models import Fulfillment, PaymentMethod
from app.modules.orders.order_service import OrderService
from app.modules.orders.schemas import OrderDraft, OrderStep
from app.schemas.conversation_schemas import CoreStep
from app.services.steps.base import Context, InvalidInputError, Move, StepHandler, choice, required
from app.services.steps.name import NameStep
from app.utils.money import parse_brl

logger = logging.getLogger(__name__)


class OrderNameStep(NameStep[OrderDraft]):
    step = OrderStep.NAME
    previous = OrderStep.CART
    next_step = OrderStep.FULFILLMENT


class FulfillmentStep(StepHandler[OrderDraft]):
    step = OrderStep.FULFILLMENT
    previous = OrderStep.NAME

    def __init__(self, orders: OrderService) -> None:
        self.orders = orders

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                ctx.draft.fulfillment, ctx.draft.lookup, ctx.draft.address = Fulfillment.PICKUP, None, None
                return Move(OrderStep.PAYMENT)
            case 2:
                ctx.draft.fulfillment = Fulfillment.DELIVERY
                return Move(OrderStep.ADDRESS_CEP)
            case _:
                raise InvalidInputError

    async def render(self, ctx: Context[OrderDraft]) -> str:
        return messages.fulfillment((await self.orders.settings()).delivery_fee)


class PaymentStep(StepHandler[OrderDraft]):
    step = OrderStep.PAYMENT
    question = messages.PAYMENT

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                ctx.draft.payment = PaymentMethod.CASH
                return Move(OrderStep.CHANGE)
            case 2:
                ctx.draft.payment = PaymentMethod.CARD
            case 3:
                ctx.draft.payment = PaymentMethod.PIX
            case _:
                raise InvalidInputError
        ctx.draft.change_for = None
        return Move(OrderStep.CONFIRM)

    def back(self, ctx: Context[OrderDraft]) -> str:
        if ctx.draft.fulfillment is not Fulfillment.DELIVERY:
            return OrderStep.FULFILLMENT
        return OrderStep.ADDRESS_COMPLEMENT if ctx.draft.lookup else OrderStep.ADDRESS


class ChangeStep(StepHandler[OrderDraft]):
    step = OrderStep.CHANGE
    previous = OrderStep.PAYMENT
    question = messages.CHANGE

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                ctx.draft.change_for = None
                return Move(OrderStep.CONFIRM)
            case 2:
                return Move(OrderStep.CHANGE_AMOUNT)
            case _:
                raise InvalidInputError


class ChangeAmountStep(StepHandler[OrderDraft]):
    step = OrderStep.CHANGE_AMOUNT
    previous = OrderStep.CHANGE
    free_text = True
    question = messages.CHANGE_AMOUNT

    def __init__(self, orders: OrderService) -> None:
        self.orders = orders

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        amount = parse_brl(answer)
        if amount is None:
            raise InvalidInputError(messages.AMOUNT_INVALID)
        total = (await self.orders.quote(ctx.draft)).total
        if amount <= total:
            raise InvalidInputError(messages.change_too_low(total))
        ctx.draft.change_for = amount
        return Move(OrderStep.CONFIRM)


class ConfirmStep(StepHandler[OrderDraft]):
    step = OrderStep.CONFIRM
    previous = OrderStep.PAYMENT

    def __init__(self, orders: OrderService) -> None:
        self.orders = orders

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                return await self._place(ctx)
            case 2:
                ctx.draft = OrderDraft()
                return Move(CoreStep.MAIN_MENU, notice=messages.ORDER_CANCELLED)
            case _:
                raise InvalidInputError

    async def render(self, ctx: Context[OrderDraft]) -> str:
        quote = await self.orders.quote(ctx.draft)
        return messages.order_summary(quote, required(ctx.draft.checkout()))

    async def _place(self, ctx: Context[OrderDraft]) -> Move:
        checkout = required(ctx.draft.checkout())
        quote = await self.orders.quote(ctx.draft)
        try:
            order = await self.orders.place(ctx.customer, ctx.store, quote, checkout)
        except AppException:
            logger.exception("Order rolled back: the staff could not be notified")
            return Move(notice=messages.ORDER_FAILED)

        ctx.customer.name = checkout.name
        return Move(say=(messages.order_confirmed(order.id, quote, checkout),), ends=True)
