from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Movie Reservation System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    CINEMA_TIMEZONE: str = "Asia/Ho_Chi_Minh"
    MIN_MINUTES_BEFORE_CANCEL_OR_EXCHANGE: int = 30

    # Database
    DATABASE_URL: str
    DATABASE_URL_SYNC: str = ""

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    @property
    def effective_redis_url(self) -> str:
        url = self.REDIS_URL
        if "redis:6379" in url:
            import socket
            try:
                socket.gethostbyname("redis")
            except socket.gaierror:
                return url.replace("redis:6379", "localhost:6379")
        return url

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Admin Seed
    ADMIN_EMAIL: str = "admin@moviereservation.com"
    ADMIN_PASSWORD: str = "Admin@123456"
    ADMIN_FULL_NAME: str = "System Administrator"

    # TMDB
    TMDB_API_KEY: str = ""
    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL: str = "https://image.tmdb.org/t/p/w500"
    TMDB_REGION: str = "VN"
    TMDB_LANGUAGE: str = "vi-VN"

    # CORS & Base URLs
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8080"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    BACKEND_BASE_URL: str = "http://localhost:8000"

    # VNPay Configuration
    VNPAY_TMN_CODE: str = ""           # Required: set via .env (e.g. VNPAY_TMN_CODE=XXXXXXXX)
    VNPAY_HASH_SECRET: str = ""        # Required: set via .env (e.g. VNPAY_HASH_SECRET=...)
    VNPAY_URL: str = "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
    VNPAY_RETURN_URL: str = ""

    # SMTP Email Configuration
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_EMAIL: str = "noreply@cineverse.vn"
    EMAILS_FROM_NAME: str = "CineVerse Cinema"
    EMAIL_ENABLED: bool = False

    # Cache TTLs (seconds)
    CACHE_TTL_MOVIES: int = 300        # 5 minutes
    CACHE_TTL_SHOWTIMES: int = 60      # 1 minute
    CACHE_TTL_GENRES: int = 600        # 10 minutes
    CACHE_TTL_THEATERS: int = 600      # 10 minutes

    # Virtual Queue Settings
    QUEUE_ENABLED: bool = True
    QUEUE_MAX_ACTIVE_USERS_PER_SHOWTIME: int = 30
    QUEUE_PASS_TOKEN_EXPIRE_MINUTES: int = 5

    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def effective_database_url(self) -> str:
        url = self.DATABASE_URL
        if "@db:" in url:
            import socket
            try:
                socket.gethostbyname("db")
            except socket.gaierror:
                url = url.replace("@db:", "@localhost:")
        return url


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
