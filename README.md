# 🎬 Movie Reservation System

A production-grade backend API for movie seat reservations built with **FastAPI**, **PostgreSQL**, **Redis**, and **Docker**.

[![CI](https://github.com/your-username/movie-reservation-system/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/movie-reservation-system/actions)
[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green?logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-red?logo=redis)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)](https://docs.docker.com/compose/)

---
http://localhost:8000/api/v1/openapi.json
## ✨ Features

| Feature | Details |
|---------|---------|
| 🔐 **Auth** | JWT Access + Refresh Token, RBAC (Admin / User) |
| 🎬 **Movies** | Full CRUD + TMDB API sync (poster, genres, metadata) |
| 🏟️ **Theaters** | Auto seat generation (rows × cols), VIP seat types |
| 🕐 **Showtimes** | Scheduling with conflict detection |
| 🎟️ **Reservations** | SELECT FOR UPDATE overbooking prevention |
| 📊 **Reporting** | Revenue & capacity analytics (Admin) |
| ⚡ **Caching** | Redis cache on read-heavy endpoints |
| 📝 **Docs** | Interactive Swagger UI + ReDoc |
| 🧪 **Tests** | Pytest unit + integration (≥60% coverage) |
| 🐳 **Docker** | One-command startup |
| 🔄 **CI/CD** | GitHub Actions lint + test pipeline |

---

## 🚀 Quick Start (1 Command)

```bash
# Clone the repo
git clone https://github.com/your-username/movie-reservation-system.git
cd movie-reservation-system

# Copy env file
cp .env.example .env
# Edit .env and set TMDB_API_KEY (or it uses demo key)

# Start everything
docker-compose up --build
```

The API will be available at **http://localhost:8000**

| Service | URL |
|---------|-----|
| 📖 Swagger UI | http://localhost:8000/docs |
| 📘 ReDoc | http://localhost:8000/redoc |
| 💾 Adminer (DB GUI) | http://localhost:8080 |
| ❤️ Health Check | http://localhost:8000/health |

---

## 🔑 Default Admin Credentials

```
Email:    admin@moviereservation.com
Password: Admin@123456
```

---

## 📁 Project Structure

```
movie-reservation-system/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings (pydantic-settings)
│   ├── dependencies.py      # Shared FastAPI dependencies
│   ├── core/
│   │   ├── security.py      # JWT + password utils
│   │   ├── exceptions.py    # Custom exceptions
│   │   └── logging.py       # Structured logging
│   ├── db/
│   │   ├── base.py          # SQLAlchemy Base
│   │   ├── session.py       # Async session factory
│   │   └── init_db.py       # Table creation + admin seed
│   ├── models/              # SQLAlchemy ORM models (8 models)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── api/v1/             # API routers (7 routers, 32 endpoints)
│   ├── services/            # Business logic layer
│   └── utils/               # Pagination + helpers
├── tests/
│   ├── unit/               # Unit tests (security, schemas)
│   └── integration/        # Integration tests (API flows)
├── alembic/                 # Database migrations
├── .github/workflows/       # GitHub Actions CI
├── Dockerfile               # Multi-stage Docker build
├── docker-compose.yml       # Full dev environment
└── docker-compose.test.yml  # Test environment
```

---

## 🗃️ Data Model

```
Users ──────────────────────────────────────────────────────────────┐
  │ (one-to-many)                                                    │
Reservations ─── ReservationSeats ─── ShowtimeSeats ─── Seats       │
  │                                         │               │        │
  │                                     Showtimes       Theaters    │
  │                                         │                        │
  └─────────────────────────────────── Movies ── MovieGenres ── Genres
```

---

## 🔌 API Endpoints

### Authentication
```
POST /api/v1/auth/register     Register new user
POST /api/v1/auth/login        Login (get access + refresh token)
POST /api/v1/auth/refresh      Refresh access token
POST /api/v1/auth/logout       Logout (blacklist refresh token)
```

### Users
```
GET    /api/v1/users/me           My profile
PUT    /api/v1/users/me           Update profile
GET    /api/v1/users/             List all users [Admin]
PATCH  /api/v1/users/{id}/promote Promote to admin [Admin]
DELETE /api/v1/users/{id}         Deactivate user [Admin]
```

### Movies
```
GET    /api/v1/movies/                    List movies (filter/search/paginate)
GET    /api/v1/movies/{id}                Movie detail
POST   /api/v1/movies/                    Create movie [Admin]
PUT    /api/v1/movies/{id}                Update movie [Admin]
DELETE /api/v1/movies/{id}                Soft-delete [Admin]
POST   /api/v1/movies/tmdb/sync/{tmdb_id} Sync from TMDB [Admin]
GET    /api/v1/movies/tmdb/search         Search TMDB [Admin]
GET    /api/v1/movies/tmdb/popular        Popular on TMDB [Admin]
```

### Theaters & Showtimes
```
GET    /api/v1/theaters/          List theaters
GET    /api/v1/theaters/{id}      Theater + seat layout
POST   /api/v1/theaters/          Create theater (auto-generates seats) [Admin]
PUT    /api/v1/theaters/{id}      Update theater [Admin]

GET    /api/v1/showtimes/         List showtimes (filter by date/movie/theater)
GET    /api/v1/showtimes/{id}     Showtime detail
GET    /api/v1/showtimes/{id}/seats  Seat availability map [Auth]
POST   /api/v1/showtimes/         Create showtime [Admin]
PUT    /api/v1/showtimes/{id}     Update showtime [Admin]
DELETE /api/v1/showtimes/{id}     Cancel showtime [Admin]
```

### Reservations
```
GET    /api/v1/reservations/               My reservations
POST   /api/v1/reservations/               Create reservation
GET    /api/v1/reservations/{id}           Reservation detail
DELETE /api/v1/reservations/{id}           Cancel reservation

GET    /api/v1/reservations/admin/all              All reservations [Admin]
GET    /api/v1/reservations/admin/report/revenue   Revenue report [Admin]
GET    /api/v1/reservations/admin/report/capacity  Capacity report [Admin]
```

---

## 🛠️ Local Development (Without Docker)

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Set up env variables
cp .env.example .env
# Edit DATABASE_URL and REDIS_URL to point to local services

# Run database migrations
alembic upgrade head

# Start the app
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 🧪 Running Tests

```bash
# Install test dependencies
pip install -r requirements-dev.txt
pip install aiosqlite

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing

# Using Docker
docker-compose -f docker-compose.test.yml run --rm test
```

---

## 🗄️ Database Migrations (Alembic)

```bash
# Create a new migration
alembic revision --autogenerate -m "description of change"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Show migration history
alembic history
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL async URL |
| `DATABASE_URL_SYNC` | — | PostgreSQL sync URL (Alembic) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `SECRET_KEY` | — | JWT signing key (≥32 chars) |
| `TMDB_API_KEY` | — | The Movie Database API key |
| `ADMIN_EMAIL` | `admin@moviereservation.com` | Seed admin email |
| `ADMIN_PASSWORD` | `Admin@123456` | Seed admin password |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `DEBUG` | `false` | Enable SQL query logging |

---

## 🏗️ Architecture

```
Client
  │
  ▼
FastAPI Application (Uvicorn)
  │
  ├── JWT Auth Middleware (RBAC)
  │
  ├── API Routers (/api/v1/*)
  │     └── Service Layer (Business Logic)
  │           ├── PostgreSQL (SQLAlchemy async)
  │           │     └── SELECT FOR UPDATE (overbooking prevention)
  │           └── Redis (Caching + Refresh Token Store)
  │
  └── TMDB External API (movie metadata)
```

---

## 🔒 Security Design

- **Passwords**: bcrypt hashed with salt
- **Access Tokens**: HS256 JWT, 30-minute TTL
- **Refresh Tokens**: HS256 JWT, stored in Redis, blacklisted on logout
- **RBAC**: `admin` vs `user` role enforced at router level
- **Overbooking**: `SELECT FOR UPDATE` database lock during seat reservation
- **Input Validation**: Pydantic v2 strict validation on all endpoints

---

## 📊 Tech Stack Summary

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11 |
| Framework | FastAPI 0.111 |
| ORM | SQLAlchemy 2.x (async) |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Cache | Redis 7 |
| Auth | python-jose (JWT) + passlib (bcrypt) |
| HTTP Client | httpx (async) |
| Validation | Pydantic v2 |
| Testing | Pytest + pytest-asyncio + httpx |
| Linting | Ruff |
| Container | Docker + Docker Compose |
| CI/CD | GitHub Actions |

---

## 📬 Testing with Postman

Import the collection from the Swagger JSON:
1. Open Swagger UI at `http://localhost:8000/docs`
2. Click the `/api/v1/openapi.json` link
3. In Postman: **Import → Link** → paste the URL
4. Create an environment with `base_url = http://localhost:8000`
5. Login via `POST /api/v1/auth/login` and save `access_token`

---

## 📄 License

MIT License — feel free to use this project as a reference or starting point.
