from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List

from app.db.base import Base


class Genre(Base):
    __tablename__ = "genres"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)

    # Relationships
    movies: Mapped[List["MovieGenre"]] = relationship(  # noqa: F821
        "MovieGenre", back_populates="genre"
    )

    def __repr__(self) -> str:
        return f"<Genre id={self.id} name={self.name}>"
