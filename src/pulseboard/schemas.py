"""Validated API input and output models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class MonitorInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: HttpUrl
    method: Literal["GET", "HEAD"] = "GET"
    interval_seconds: int = Field(default=60, ge=10, le=86_400)
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    expected_status_min: int = Field(default=200, ge=100, le=599)
    expected_status_max: int = Field(default=399, ge=100, le=599)

    @model_validator(mode="after")
    def status_range_is_ordered(self) -> "MonitorInput":
        if self.expected_status_min > self.expected_status_max:
            raise ValueError("expected_status_min must not exceed expected_status_max")
        return self


class MonitorCreate(MonitorInput):
    active: bool = True


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: HttpUrl | None = None
    method: Literal["GET", "HEAD"] | None = None
    interval_seconds: int | None = Field(default=None, ge=10, le=86_400)
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=60.0)
    expected_status_min: int | None = Field(default=None, ge=100, le=599)
    expected_status_max: int | None = Field(default=None, ge=100, le=599)
    active: bool | None = None


class CheckView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: str
    checked_at: datetime
    status: Literal["up", "down"]
    status_code: int | None
    duration_ms: float | None
    error: str | None


class MonitorView(BaseModel):
    id: str
    name: str
    url: str
    method: Literal["GET", "HEAD"]
    interval_seconds: int
    timeout_seconds: float
    expected_status_min: int
    expected_status_max: int
    active: bool
    created_at: datetime
    updated_at: datetime
    current_status: Literal["up", "down", "pending", "paused"]
    uptime_24h: float | None
    last_check: CheckView | None
    has_open_incident: bool


class IncidentView(BaseModel):
    id: int
    monitor_id: str
    monitor_name: str
    started_at: datetime
    resolved_at: datetime | None
    cause: str


class StatusSummary(BaseModel):
    generated_at: datetime
    overall_status: Literal["operational", "degraded", "unknown"]
    monitors_up: int
    monitors_down: int
    monitors_pending: int
    monitors_paused: int
    monitors: list[MonitorView]
