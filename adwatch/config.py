from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = "sqlite:///./work/adwatch.db"
    admin_username: str = "admin"
    admin_password: str = ""
    public_url: str = "http://localhost:18473"
    scan_gap_seconds: int = Field(default=30, ge=0, le=3600)
    poll_seconds: int = Field(default=5, ge=1, le=60)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_tls: str = "starttls"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @model_validator(mode="after")
    def valid_channels(self):
        if self.smtp_host and (not self.smtp_from or not self.smtp_to):
            raise ValueError("SMTP_FROM and SMTP_TO are required when SMTP_HOST is configured.")
        if self.smtp_tls not in {"starttls", "ssl"}:
            raise ValueError("SMTP_TLS must be starttls or ssl.")
        if bool(self.telegram_bot_token) != bool(self.telegram_chat_id):
            raise ValueError("Configure both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return self

    @property
    def channels(self) -> list[str]:
        return (["email"] if self.smtp_host else []) + (
            ["telegram"] if self.telegram_bot_token else []
        )


@lru_cache
def settings() -> Settings:
    return Settings()
