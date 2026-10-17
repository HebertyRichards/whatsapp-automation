"""Customer-facing copy every business shares, in Brazilian Portuguese. Each module keeps its own in its messages.py.

A Text can be reworded by the owner: a row in the `texts` table with the constant's name as key replaces it.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.utils.money import format_brl
from app.utils.texts import Text, Texts

BACK = "V - Voltar"
ATTENDANT = "0 - Falar com atendente"

_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


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


def ask(question: str) -> str:
    """An open question, followed by the navigation lines."""
    return f"{question}\n\n{BACK}\n{ATTENDANT}"


INVALID = Text("INVALID", "Não entendi. 😕 Responda com uma das opções abaixo.")
ATTENDANT_TIP = Text("ATTENDANT_TIP", "Se preferir, digite *0* para falar com um atendente.")
TEXT_ONLY = Text("TEXT_ONLY", "Por aqui eu só consigo ler mensagens de texto. 🙂")
RESTARTED = Text("RESTARTED", "Precisei reiniciar o atendimento. Vamos de novo?")
HANDOFF = Text(
    "HANDOFF",
    "Certo! Um atendente vai continuar a conversa por aqui. 🙋\nPara voltar ao atendimento automático, digite *menu*.",
)
HANDOFF_FAILED = Text("HANDOFF_FAILED", "Não consegui chamar um atendente agora. Tente de novo em instantes.")
MAIN_MENU_TITLE = Text("MAIN_MENU_TITLE", "Como posso ajudar?")
ATTENDANT_OPTION = Text("ATTENDANT_OPTION", "Falar com atendente")
NAME = Text("NAME", ask("Qual é o seu *nome*?"))
NAME_INVALID = Text("NAME_INVALID", "Não consegui entender o nome.")
CLOSED = Text("CLOSED", "Olá! A *{loja}* está fechada no momento. 😴")
REOPENS = Text("REOPENS", "Abrimos {dia} às {hora}.")


def closed(texts: Texts, store_name: str, opening: datetime | None, now: datetime) -> str:
    text = texts(CLOSED, loja=store_name)
    if opening is None:
        return text
    days_ahead = (opening.date() - now.date()).days
    day = "hoje" if days_ahead == 0 else "amanhã" if days_ahead == 1 else _WEEKDAYS[opening.weekday()]
    clock = f"{opening.hour}h" if opening.minute == 0 else f"{opening.hour}h{opening.minute:02d}"
    return f"{text}\n{texts(REOPENS, dia=day, hora=clock)}"


def priced(name: str, price: Decimal) -> str:
    return f"{name} - {format_brl(price)}"


def contact_lines(jid: str) -> list[str]:
    """A tap-to-chat link for the staff, when the JID is a phone number."""
    number, _, server = jid.partition("@")
    return [f"WhatsApp: wa.me/{number}"] if server == "s.whatsapp.net" else []


def staff_handoff(name: str | None, jid: str) -> str:
    return "\n".join(["🙋 *Cliente pedindo atendimento*", f"Nome: {name or 'não informado'}", *contact_lines(jid)])
