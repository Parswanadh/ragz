"""Public connection status is separate from in-memory runtime credentials."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class ChatGPTLogin(BaseModel):
    login_id: str | None = None
    state: Literal["idle", "pending", "authorised", "cancelled", "expired", "failed"] = "idle"
    verification_url: str | None = None
    user_code: str | None = None
    expires_at: float | None = None
    interval: int = 5
    error: str | None = None


class ChatGPTStatus(BaseModel):
    available: bool = True
    connected: bool = False
    account_id: str | None = None
    email: str | None = None
    plan_type: str | None = None
    expires_at: float | None = None
    login: ChatGPTLogin = Field(default_factory=ChatGPTLogin)


class ChatGPTPoll(BaseModel):
    login_id: str = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class ChatGPTCredentials:
    access_token: str = field(repr=False)
    account_id: str
    expires_at: float
