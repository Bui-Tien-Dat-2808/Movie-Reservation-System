from fastapi import APIRouter

from app.api.v1 import auth, genres, movies, reservations, showtimes, rooms, users

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(genres.router)
api_router.include_router(movies.router)
api_router.include_router(rooms.router)
api_router.include_router(showtimes.router)
api_router.include_router(reservations.router)
