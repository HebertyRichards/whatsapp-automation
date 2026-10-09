import re
from decimal import Decimal

_NOT_AMOUNT_CHARS = re.compile(r"[^\d.,]")
_AMOUNT = re.compile(r"\d{1,6}(\.\d{1,2})?")


def format_brl(value: Decimal) -> str:
    """Decimal('1234.5') -> 'R$ 1.234,50'."""
    whole, cents = f"{value:,.2f}".split(".")
    return f"R$ {whole.replace(',', '.')},{cents}"


def parse_brl(text: str) -> Decimal | None:
    """Reads an amount the way customers type it: '100', '100,50', 'R$ 1.000,00'."""
    cleaned = _NOT_AMOUNT_CHARS.sub("", text)
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return Decimal(cleaned) if _AMOUNT.fullmatch(cleaned) else None
