import time
from typing import Literal

from pydantic import BaseModel


class WebhookEvent(BaseModel):
    """Envelope the Evolution API posts for every event. `data` is only parsed for the events we handle."""

    event: str
    instance: str = ""
    data: object = None


class WebhookAck(BaseModel):
    status: Literal["queued", "ignored"]


class MessageKey(BaseModel):
    remoteJid: str
    fromMe: bool = False
    id: str


class ExtendedText(BaseModel):
    text: str | None = None


class MessageContent(BaseModel):
    conversation: str | None = None
    extendedTextMessage: ExtendedText | None = None
    # Chats with disappearing messages may wrap the real content.
    ephemeralMessage: "WrappedMessage | None" = None

    @property
    def text(self) -> str | None:
        if self.conversation:
            return self.conversation
        if self.extendedTextMessage and self.extendedTextMessage.text:
            return self.extendedTextMessage.text
        if self.ephemeralMessage and self.ephemeralMessage.message:
            return self.ephemeralMessage.message.text
        return None


class WrappedMessage(BaseModel):
    message: MessageContent | None = None


class InboundMessage(BaseModel):
    """`data` of a messages.upsert event."""

    key: MessageKey
    pushName: str | None = None
    message: MessageContent | None = None
    messageType: str = "unknown"
    messageTimestamp: object = None

    @property
    def text(self) -> str | None:
        return self.message.text if self.message else None

    def is_older_than(self, seconds: int) -> bool:
        sent_at = self.messageTimestamp
        return isinstance(sent_at, int) and time.time() - sent_at > seconds
