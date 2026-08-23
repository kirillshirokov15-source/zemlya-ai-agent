import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(800), index=True)
    industry: Mapped[str | None] = mapped_column(String(255))
    description_short: Mapped[str | None] = mapped_column(Text)
    sales_argument_short: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(512))
    stage: Mapped[str | None] = mapped_column(String(8), index=True)
    land_status: Mapped[str | None] = mapped_column(String(64), index=True)
    signal_status: Mapped[str | None] = mapped_column(String(64), index=True)
    investment_amount: Mapped[float | None] = mapped_column(Numeric(20, 2))
    first_announced_at: Mapped[date | None] = mapped_column(Date)
    last_significant_event_at: Mapped[date | None] = mapped_column(Date, index=True)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_review_reason: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_score: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
