from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str | None = None
    redis_url: str | None = None
    openai_api_key: str | None = None
    tavily_api_key: str | None = None
    dadata_api_key: str | None = None
    telegram_bot_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
