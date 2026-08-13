import enum
from datetime import date
from typing import List, Optional

from sqlalchemy import Boolean, Date, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MovieStatus(str, enum.Enum):
    NOW_SHOWING = "now_showing"
    COMING_SOON = "coming_soon"
    ENDED = "ended"


class MovieGenre(Base):
    """Association table for Movie <-> Genre many-to-many."""
    __tablename__ = "movie_genres"

    movie_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
    )
    genre_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("genres.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    movie: Mapped["Movie"] = relationship("Movie", back_populates="movie_genres")
    genre: Mapped["Genre"] = relationship("Genre", back_populates="movies")  # noqa: F821


class Movie(Base):
    __tablename__ = "movies"

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    release_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rating: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # e.g. PG-13
    director: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    popularity: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0.0)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    status: Mapped[MovieStatus] = mapped_column(
        Enum(MovieStatus), default=MovieStatus.NOW_SHOWING, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    movie_genres: Mapped[List["MovieGenre"]] = relationship(
        "MovieGenre",
        back_populates="movie",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    showtimes: Mapped[List["Showtime"]] = relationship(  # noqa: F821
        "Showtime", back_populates="movie"
    )

    @property
    def genres(self) -> List["Genre"]:  # noqa: F821
        return [mg.genre for mg in self.movie_genres if mg.genre is not None]

    def __repr__(self) -> str:
        return f"<Movie id={self.id} title={self.title}>"
