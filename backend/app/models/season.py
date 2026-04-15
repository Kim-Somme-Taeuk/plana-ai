from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    server: Mapped[str] = mapped_column(String(20), nullable=False)
    boss_name: Mapped[str] = mapped_column(String(100), nullable=False)
    armor_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    terrain: Mapped[str] = mapped_column(String(50), nullable=False)
    season_label: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ranking_snapshots = relationship(
        "RankingSnapshot",
        back_populates="season",
        cascade="all, delete-orphan",
    )
