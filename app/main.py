from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging
from app.db.session import engine
from app.db.init_db import init_db

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    configure_logging()
    logger.info("Starting Movie Reservation System", version=settings.APP_VERSION)

    # Initialize database (create tables + seed admin)
    await init_db()

    yield

    # Cleanup on shutdown
    await engine.dispose()
    logger.info("Application shutdown complete")


def create_application() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="""
## Movie Reservation System API

A comprehensive backend system for movie seat reservations.

### Features
- 🔐 **JWT Authentication** with access & refresh tokens
- 👥 **RBAC** — Admin and User roles
- 🎬 **Movie Management** with TMDB integration
- 🎭 **Showtime & Theater Management**
- 🎟️ **Seat Reservation** with overbooking prevention
- 📊 **Admin Reporting** — revenue & capacity
- ⚡ **Redis Caching** for high-read endpoints

### Authentication
Use `/api/v1/auth/login` to obtain tokens, then include in header:
```
Authorization: Bearer <access_token>
```
        """,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # Global exception handlers
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "error_code": exc.error_code,
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception", exc_info=exc, path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
        )

    # Health check
    @app.get("/health", tags=["Health"], summary="Health Check")
    async def health_check():
        return {
            "status": "healthy",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    return app


app = create_application()
