import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inn: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    legal_name: Mapped[str] = mapped_column(String(512), index=True)
    status: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(Text)
    revenue: Mapped[float | None] = mapped_column(Numeric(18, 2))
    profit: Mapped[float | None] = mapped_column(Numeric(18, 2))
    group_name: Mapped[str | None] = mapped_column(String(512))
    is_private: Mapped[bool | None] = mapped_column(Boolean)
    is_bankrupt: Mapped[bool] = mapped_column(Boolean, default=False)
    is_liquidating: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
