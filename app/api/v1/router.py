from fastapi import APIRouter
from app.api.v1 import analytics, auth, concessions, genres, loyalty, movies, payments, refunds, reservations, rooms, showtimes, users, vouchers

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(genres.router)
api_router.include_router(movies.router)
api_router.include_router(rooms.router)
api_router.include_router(showtimes.router)
api_router.include_router(reservations.router)
api_router.include_router(payments.router)
api_router.include_router(refunds.router)
api_router.include_router(vouchers.router)
api_router.include_router(concessions.router)
api_router.include_router(loyalty.router)
api_router.include_router(analytics.router)
