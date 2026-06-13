from pydantic import Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )
        DATABASE_URL: str = Field(..., description="PostgreSQL connection string (e.g. postgresql+asyncpg://...)")
        REDIS_URL: str = Field(..., description="Redis connection string (e.g. redis://...)")
        WHOLESALE_API_TOKEN: str = Field(..., description="API token for the wholesale supplier API")
        WHOLESALE_API_BASE_URL: str = Field(..., description="Base URL of wholesale B2B distributor API")
        INTERNAL_API_SECRET_TOKEN: str = Field(..., description="Secret token for verifying internal API requests")
        TELEGRAM_BOT_TOKEN: str = Field(..., description="Token for the Telegram Bot")
        TELEGRAM_ADMIN_CHAT_ID: int = Field(..., description="Telegram ID for the admin/admin group")
        USD_TO_UZS_RATE: float = Field(12800.0, description="Fallback USD to UZS exchange rate")
        EUR_TO_UZS_RATE: float = Field(14000.0, description="Fallback EUR to UZS exchange rate")
        PROFIT_MARGIN_PERCENT: float = Field(5.0, description="Profit margin surcharge percentage")

except ImportError:
    from pydantic import BaseSettings
    
    class Settings(BaseSettings):
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"
            
        DATABASE_URL: str = Field(..., description="PostgreSQL connection string (e.g. postgresql+asyncpg://...)")
        REDIS_URL: str = Field(..., description="Redis connection string (e.g. redis://...)")
        WHOLESALE_API_TOKEN: str = Field(..., description="API token for the wholesale supplier API")
        WHOLESALE_API_BASE_URL: str = Field(..., description="Base URL of wholesale B2B distributor API")
        INTERNAL_API_SECRET_TOKEN: str = Field(..., description="Secret token for verifying internal API requests")
        TELEGRAM_BOT_TOKEN: str = Field(..., description="Token for the Telegram Bot")
        TELEGRAM_ADMIN_CHAT_ID: int = Field(..., description="Telegram ID for the admin/admin group")
        USD_TO_UZS_RATE: float = Field(12800.0, description="Fallback USD to UZS exchange rate")
        EUR_TO_UZS_RATE: float = Field(14000.0, description="Fallback EUR to UZS exchange rate")
        PROFIT_MARGIN_PERCENT: float = Field(5.0, description="Profit margin surcharge percentage")

# Expose settings instance
settings = Settings(_env_file=".env") if ".env" in globals() or "SettingsConfigDict" in globals() else None
if settings is None:
    # Fallback instantiation
    settings = Settings()
