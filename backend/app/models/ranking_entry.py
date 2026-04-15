from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RankingEntry(Base):
    __tablename__ = "ranking_entries"

    __table_args__ = (
        UniqueConstraint(
            "ranking_snapshot_id",
            "rank",
            name="uq_ranking_entries_snapshot_rank",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ranking_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("ranking_snapshots.id"),
        nullable=False,
        index=True,
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_valid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    validation_issue: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ranking_snapshot = relationship(
        "RankingSnapshot",
        back_populates="ranking_entries",
    )
