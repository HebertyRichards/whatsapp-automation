"""Customer-facing copy, in Brazilian Portuguese. The flow itself lives in conversation_service."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.models import Fulfillment, HalfHalfPricing, PaymentMethod
from app.schemas.conversation_schemas import Checkout
from app.schemas.menu_schemas import MenuSection
from app.schemas.order_schemas import Quote
from app.utils.money import format_brl

BACK = "V - Voltar"
ATTENDANT = "0 - Falar com atendente"

_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
_PAYMENT = {PaymentMethod.CASH: "Dinheiro", PaymentMethod.CARD: "Cartão", PaymentMethod.PIX: "Pix"}
_HALF_RULE = {
    HalfHalfPricing.HIGHEST: "No meio a meio vale o preço do sabor mais caro.",
    HalfHalfPricing.AVERAGE: "No meio a meio o preço é a média dos dois sabores.",
}


def options(title: str, labels: Sequence[str], *, first: int = 1, nav: Sequence[str] = (BACK, ATTENDANT)) -> str:
    """A numbered list. `first` keeps the numbering continuous across pages."""
    lines = [title, "", *(f"{number} - {label}" for number, label in enumerate(labels, first))]
    if nav:
        lines += ["", *nav]
    return "\n".join(lines)


def page_nav(page: int, pages: int) -> tuple[str, ...]:
    """Navigation lines for a list that may span several pages (`page` is zero-based)."""
    lines: list[str] = []
    if pages > 1:
        lines.append(f"Página {page + 1} de {pages}")
        if page + 1 < pages:
            lines.append("M - Mais opções")
        if page > 0:
            lines.append("A - Página anterior")
    return (*lines, BACK, ATTENDANT)


def _ask(question: str) -> str:
    return f"{question}\n\n{BACK}\n{ATTENDANT}"


INVALID = "Não entendi. 😕 Responda com uma das opções abaixo."
ATTENDANT_TIP = "Se preferir, digite *0* para falar com um atendente."
TEXT_ONLY = "Por aqui eu só consigo ler mensagens de texto. 🙂"
MENU_UNAVAILABLE = "Nosso cardápio está indisponível no momento. 😕"
NO_DRINKS = "No momento não temos bebidas disponíveis."
CART_EMPTIED = "Seu pedido ficou vazio."
ORDER_CANCELLED = "Pedido cancelado."
ORDER_FAILED = "Não consegui registrar seu pedido agora. 😕 Tente confirmar de novo em instantes."
RESTARTED = "Precisei reiniciar o atendimento. Vamos de novo?"
HANDOFF = (
    "Certo! Um atendente vai continuar a conversa por aqui. 🙋\n"
    "Para voltar ao atendimento automático, digite *menu*."
)
HANDOFF_FAILED = "Não consegui chamar um atendente agora. Tente de novo em instantes."
NAME_INVALID = "Não consegui entender o nome."
ADDRESS_INVALID = "O endereço parece incompleto."
AMOUNT_INVALID = "Não entendi o valor."

MAIN_MENU = options("Como posso ajudar?", ["Fazer pedido", "Ver cardápio", "Falar com atendente"], nav=())
NAME = _ask("Qual é o seu *nome*?")
ADDRESS = _ask("Qual o *endereço de entrega*?\nInforme rua, número, bairro e complemento.")
PAYMENT = options(
    "Qual a forma de pagamento?\nO pagamento é feito na entrega ou na retirada.",
    ["Dinheiro", "Cartão", "Pix"],
)
CHANGE = options("Precisa de troco?", ["Não", "Sim"])
CHANGE_AMOUNT = _ask("Troco para quanto? Digite só o valor, por exemplo: 100")


def welcome(store_name: str) -> str:
    return f"Olá! 👋 Seja bem-vindo(a) à *{store_name}*.\nSou o assistente virtual e vou anotar o seu pedido."


def closed(store_name: str, opening: datetime | None, now: datetime) -> str:
    text = f"Olá! A *{store_name}* está fechada no momento. 😴"
    if opening is None:
        return text
    days_ahead = (opening.date() - now.date()).days
    day = "hoje" if days_ahead == 0 else "amanhã" if days_ahead == 1 else _WEEKDAYS[opening.weekday()]
    clock = f"{opening.hour}h" if opening.minute == 0 else f"{opening.hour}h{opening.minute:02d}"
    return f"{text}\nAbrimos {day} às {clock}."


def size_label(size_name: str, half: bool) -> str:
    return f"{size_name} meio a meio" if half else size_name


def pizza_description(size_name: str, half: bool, flavor_names: Sequence[str]) -> str:
    return f"Pizza {size_label(size_name, half)} - {' / '.join(flavor_names)}"


def priced(name: str, price: Decimal) -> str:
    return f"{name} - {format_brl(price)}"


def categories(names: Sequence[str]) -> str:
    return options("Qual tipo de pizza você quer?", names)


def sizes(labels: Sequence[str]) -> str:
    return options("Qual o tamanho?", labels)


def flavors(
    labels: Sequence[str],
    *,
    first: int,
    nav: Sequence[str],
    half: bool,
    choosing_second: bool,
    pricing: HalfHalfPricing,
) -> str:
    if not half:
        title = "Qual o sabor?"
    else:
        title = "Agora escolha o *2º sabor*:" if choosing_second else "Escolha o *1º sabor*:"
        title = f"{title}\n{_HALF_RULE[pricing]}"
    return options(title, labels, first=first, nav=nav)


def drinks(labels: Sequence[str], *, first: int, nav: Sequence[str]) -> str:
    return options("Qual bebida você quer?", labels, first=first, nav=nav)


def fulfillment(delivery_fee: Decimal) -> str:
    return options(
        "Como você quer receber o pedido?",
        ["Retirar no balcão", f"Entrega (taxa de {format_brl(delivery_fee)})"],
    )


def change_too_low(total: Decimal) -> str:
    return f"O valor precisa ser maior que o total do pedido ({format_brl(total)})."


def _item_lines(quote: Quote) -> list[str]:
    return [f"{line.quantity}x {line.description} - {format_brl(line.total)}" for line in quote.lines]


def _total_lines(quote: Quote) -> list[str]:
    lines = [f"Subtotal: {format_brl(quote.subtotal)}"]
    if quote.delivery_fee:
        lines.append(f"Taxa de entrega: {format_brl(quote.delivery_fee)}")
    return [*lines, f"*Total: {format_brl(quote.total)}*"]


def _checkout_lines(checkout: Checkout) -> list[str]:
    delivery = checkout.fulfillment is Fulfillment.DELIVERY
    payment = _PAYMENT[checkout.payment]
    if checkout.change_for is not None:
        payment = f"{payment} (troco para {format_brl(checkout.change_for)})"
    return [
        f"Nome: {checkout.name}",
        f"Entrega: {checkout.address}" if delivery else "Retirada no balcão",
        f"Pagamento: {payment}",
    ]


def _contact_lines(jid: str) -> list[str]:
    number, _, server = jid.partition("@")
    return [f"WhatsApp: wa.me/{number}"] if server == "s.whatsapp.net" else []


def cart(quote: Quote) -> str:
    summary = "\n".join(["🛒 *Seu pedido*", "", *_item_lines(quote), "", f"Subtotal: {format_brl(quote.subtotal)}"])
    return options(
        summary,
        ["Adicionar outra pizza", "Adicionar bebida", "Finalizar pedido", "Remover um item"],
        nav=(ATTENDANT,),
    )


def cart_remove(quote: Quote) -> str:
    return options("Qual item você quer remover?", _item_lines(quote))


def order_summary(quote: Quote, checkout: Checkout) -> str:
    summary = "\n".join(
        ["📋 *Confira seu pedido*", "", *_item_lines(quote), "", *_total_lines(quote), "", *_checkout_lines(checkout)]
    )
    return options(summary, ["Confirmar pedido", "Cancelar pedido"])


def order_confirmed(order_id: int, quote: Quote, checkout: Checkout) -> str:
    if checkout.fulfillment is Fulfillment.DELIVERY:
        closing = "Vamos preparar e entregar no endereço informado."
    else:
        closing = "Vamos preparar para você retirar no balcão."
    return (
        f"✅ *Pedido #{order_id} confirmado!*\n"
        f"Total: {format_brl(quote.total)}\n"
        f"{closing}\n\n"
        "Obrigado pela preferência! 🍕"
    )


def staff_order(order_id: int, quote: Quote, checkout: Checkout, jid: str) -> str:
    return "\n".join(
        [
            f"🍕 *Novo pedido #{order_id}*",
            "",
            *_item_lines(quote),
            "",
            *_total_lines(quote),
            "",
            *_checkout_lines(checkout),
            *_contact_lines(jid),
        ]
    )


def staff_handoff(name: str | None, jid: str) -> str:
    return "\n".join(["🙋 *Cliente pedindo atendimento*", f"Nome: {name or 'não informado'}", *_contact_lines(jid)])


def full_menu(sections: Sequence[MenuSection], drink_prices: Sequence[tuple[str, Decimal]]) -> str:
    lines = ["📖 *Cardápio*"]
    for section in sections:
        lines += ["", f"🍕 *{section.name}*"]
        for flavor in section.flavors:
            prices = " | ".join(f"{size} {format_brl(price)}" for size, price in flavor.prices)
            lines.append(f"• {flavor.name} - {prices}")
            if flavor.description:
                lines.append(f"  _{flavor.description}_")
    if drink_prices:
        lines += ["", "🥤 *Bebidas*", *(f"• {priced(name, price)}" for name, price in drink_prices)]
    return "\n".join(lines)
