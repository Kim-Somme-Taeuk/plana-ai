from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RankingSnapshot(Base):
    __tablename__ = "ranking_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="collecting",
        server_default=text("'collecting'"),
    )
    total_rows_collected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    season = relationship("Season", back_populates="ranking_snapshots")
    ranking_entries = relationship(
        "RankingEntry",
        back_populates="ranking_snapshot",
        cascade="all, delete-orphan",
    )
