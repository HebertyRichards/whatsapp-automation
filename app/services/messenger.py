from abc import ABC, abstractmethod


class Messenger(ABC):
    """The channel messages leave through. The flow depends on this, never on a provider."""

    @abstractmethod
    async def send_text(self, jid: str, text: str, delay_ms: int = 0) -> None:
        """Sends a text message, raising AppException when it could not be delivered.

        With `delay_ms`, the chat shows "typing..." for that long first.
        """
