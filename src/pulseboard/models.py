"""Database models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Monitor(Base):
    __tablename__ = "monitor"
    __table_args__ = (Index("monitor_active_idx", "active"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(String(2_048), nullable=False, unique=True)
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="GET")
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    expected_status_min: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    expected_status_max: Mapped[int] = mapped_column(Integer, nullable=False, default=399)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    checks: Mapped[list[Check]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )


class Check(Base):
    __tablename__ = "monitor_check"
    __table_args__ = (Index("monitor_check_monitor_checked_idx", "monitor_id", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[str] = mapped_column(
        ForeignKey("monitor.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)

    monitor: Mapped[Monitor] = relationship(back_populates="checks")


class Incident(Base):
    __tablename__ = "incident"
    __table_args__ = (Index("incident_monitor_resolved_idx", "monitor_id", "resolved_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[str] = mapped_column(
        ForeignKey("monitor.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cause: Mapped[str] = mapped_column(Text, nullable=False)

    monitor: Mapped[Monitor] = relationship(back_populates="incidents")
