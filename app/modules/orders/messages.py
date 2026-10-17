"""Copy of the orders module, in Brazilian Portuguese. The owner can reword any Text (see app/utils/messages.py)."""

from collections.abc import Sequence
from decimal import Decimal

from app.modules.orders.models import Fulfillment, HalfHalfPricing, PaymentMethod
from app.modules.orders.schemas import Checkout, DeliveryAddress, MenuSection, Quote
from app.utils.messages import ATTENDANT, ask, contact_lines, options, priced
from app.utils.money import format_brl
from app.utils.texts import Text

_PAYMENT = {PaymentMethod.CASH: "Dinheiro", PaymentMethod.CARD: "Cartão", PaymentMethod.PIX: "Pix"}
_HALF_RULE = {
    HalfHalfPricing.HIGHEST: "No meio a meio vale o preço do sabor mais caro.",
    HalfHalfPricing.AVERAGE: "No meio a meio o preço é a média dos dois sabores.",
}

WELCOME = Text(
    "WELCOME", "Olá! 👋 Seja bem-vindo(a) à *{loja}*.\nSou o assistente virtual e vou anotar o seu pedido."
)
START_LABEL = Text("START_LABEL", "Fazer pedido")
CATALOG_LABEL = Text("CATALOG_LABEL", "Ver cardápio")

MENU_UNAVAILABLE = Text("MENU_UNAVAILABLE", "Nosso cardápio está indisponível no momento. 😕")
NO_DRINKS = Text("NO_DRINKS", "No momento não temos bebidas disponíveis.")
CART_EMPTIED = Text("CART_EMPTIED", "Seu pedido ficou vazio.")
ORDER_CANCELLED = Text("ORDER_CANCELLED", "Pedido cancelado.")
ORDER_FAILED = Text("ORDER_FAILED", "Não consegui registrar seu pedido agora. 😕 Tente confirmar de novo em instantes.")
ADDRESS_INVALID = Text("ADDRESS_INVALID", "Faltou o número. Escreva a rua, uma vírgula e o número.")
CEP_INVALID = Text("CEP_INVALID", "O CEP tem 8 números.")
CEP_NOT_FOUND = Text("CEP_NOT_FOUND", "Não encontrei esse CEP. Confira os números.")
CEP_UNAVAILABLE = Text("CEP_UNAVAILABLE", "Não consegui consultar o CEP agora.")
CEP_WITHOUT_STREET = Text("CEP_WITHOUT_STREET", "Esse CEP não traz o nome da rua.")
NUMBER_INVALID = Text("NUMBER_INVALID", "Não entendi o número.")
COMPLEMENT_INVALID = Text("COMPLEMENT_INVALID", "O complemento ficou longo demais.")
AMOUNT_INVALID = Text("AMOUNT_INVALID", "Não entendi o valor.")

CEP = Text("CEP", options("Qual o *CEP* da entrega? Digite os 8 números.", ["Não sei o CEP"]))
ADDRESS_NUMBER = Text("ADDRESS_NUMBER", ask("Qual o *número*? Se não tiver, digite s/n."))
ADDRESS_COMPLEMENT = Text(
    "ADDRESS_COMPLEMENT", options("Tem *complemento*? (apartamento, bloco, casa dos fundos...)", ["Não", "Sim"])
)
ADDRESS_COMPLEMENT_TEXT = Text("ADDRESS_COMPLEMENT_TEXT", ask("Qual o complemento?"))
ADDRESS = Text(
    "ADDRESS",
    ask(
        "Qual o *endereço de entrega*?\n"
        "Escreva a rua, uma vírgula e o número. Depois, bairro e complemento.\n"
        "Exemplo: Rua das Flores, 123 - Centro - Apto 4"
    ),
)
PAYMENT = Text(
    "PAYMENT",
    options(
        "Qual a forma de pagamento?\nO pagamento é feito na entrega ou na retirada.",
        ["Dinheiro", "Cartão", "Pix"],
    ),
)
CHANGE = Text("CHANGE", options("Precisa de troco?", ["Não", "Sim"]))
CHANGE_AMOUNT = Text("CHANGE_AMOUNT", ask("Troco para quanto? Digite só o valor, por exemplo: 100"))


def size_label(size_name: str, half: bool) -> str:
    return f"{size_name} meio a meio" if half else size_name


def pizza_description(size_name: str, half: bool, flavor_names: Sequence[str]) -> str:
    return f"Pizza {size_label(size_name, half)} - {' / '.join(flavor_names)}"


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


def _area(address: DeliveryAddress) -> str:
    return ", ".join(part for part in (address.neighborhood, f"{address.city}/{address.state}") if part)


def address_confirm(address: DeliveryAddress) -> str:
    found = f"Encontrei este endereço:\n*{address.street}*\n{_area(address)}"
    return options(f"{found}\n\nEstá certo?", ["Sim", "Não, digitar outro CEP"])


def address_line(address: DeliveryAddress) -> str:
    """The single line stored on the order and shown to the staff."""
    street = f"{address.street}, {address.number}"
    if address.complement:
        street = f"{street} - {address.complement}"
    return f"{street} - {_area(address)} - CEP {address.cep}"


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
            *contact_lines(jid),
        ]
    )


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
