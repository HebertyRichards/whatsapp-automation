"""Texts the owner can reword without a deploy: a row in the `texts` table replaces the default with the same key."""

import re
from collections.abc import Mapping
from typing import Self

# Placeholders such as {loja}. Only names the caller passes are filled; anything else is left as written.
_FIELD = re.compile(r"\{(\w+)\}")


class Text(str):
    """A default text that carries the key the owner overrides it by."""

    key: str

    def __new__(cls, key: str, default: str) -> Self:
        text = super().__new__(cls, default)
        text.key = key
        return text


class Texts:
    """The owner's rewordings, applied when a text is shown."""

    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        self._overrides = overrides or {}

    def __call__(self, text: str, /, **fields: object) -> str:
        """The owner's wording of `text` when there is one, else the default. Plain strings pass through."""
        template = self._overrides.get(text.key, text) if isinstance(text, Text) else text
        if not fields:
            return str(template)
        return _FIELD.sub(lambda m: str(fields[m[1]]) if m[1] in fields else m[0], template)
