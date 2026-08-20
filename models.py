from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, LargeBinary, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id:           Mapped[int]   = mapped_column(Integer, primary_key=True)
    google_id:    Mapped[str]   = mapped_column(String(128), unique=True, index=True)
    email:        Mapped[str]   = mapped_column(String(256), unique=True)
    display_name: Mapped[str]   = mapped_column(String(256), default="")
    avatar_url:   Mapped[str]   = mapped_column(String(512), default="")

    # Fernet-encrypted JSON: token, refresh_token, scopes, etc.
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete")


class Conversation(Base):
    __tablename__ = "conversations"

    id:         Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[int] = mapped_column(ForeignKey("users.id"))
    title:      Mapped[str] = mapped_column(String(200), default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user:     Mapped["User"]          = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation",
                                                      cascade="all, delete",
                                                      order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id:              Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role:            Mapped[str] = mapped_column(String(16))   # "user" | "assistant"
    content:         Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
