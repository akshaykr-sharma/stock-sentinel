from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional
from datetime import datetime, timezone
import re

from app.database import get_db
from app.models import Monitor
from app.scheduler import add_monitor_job, remove_monitor_job, get_next_run

router = APIRouter(prefix="/api/monitors", tags=["monitors"])


class MonitorCreate(BaseModel):
    name: str
    url: str
    phone_number: str
    check_interval: int = 60  # minutes

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+\d{10,15}$", cleaned):
            raise ValueError("Phone must be in E.164 format: +919876543210")
        return cleaned

    @field_validator("check_interval")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 5:
            raise ValueError("Minimum interval is 5 minutes")
        if v > 1440:
            raise ValueError("Maximum interval is 1440 minutes (24 hours)")
        return v


class MonitorUpdate(BaseModel):
    check_interval: Optional[int] = None
    is_active: Optional[bool] = None
    got_it: Optional[bool] = None


class MonitorResponse(BaseModel):
    id: int
    name: str
    url: str
    phone_number: str
    check_interval: int
    is_active: bool
    got_it: bool
    status: str
    price: Optional[str]
    last_checked: Optional[datetime]
    next_check: Optional[datetime]
    created_at: datetime
    error_message: Optional[str]

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[MonitorResponse])
def list_monitors(db: Session = Depends(get_db)):
    monitors = db.query(Monitor).order_by(Monitor.created_at.desc()).all()
    # Sync next_check from scheduler (live job state)
    for m in monitors:
        next_run = get_next_run(m.id)
        if next_run:
            m.next_check = next_run
    return monitors


@router.post("/", response_model=MonitorResponse, status_code=201)
def create_monitor(data: MonitorCreate, db: Session = Depends(get_db)):
    monitor = Monitor(
        name=data.name,
        url=str(data.url),
        phone_number=data.phone_number,
        check_interval=data.check_interval,
        is_active=True,
        status="unknown",
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    add_monitor_job(monitor.id, monitor.check_interval)
    return monitor


@router.patch("/{monitor_id}", response_model=MonitorResponse)
def update_monitor(monitor_id: int, data: MonitorUpdate, db: Session = Depends(get_db)):
    monitor = db.get(Monitor, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if data.got_it is not None:
        monitor.got_it = data.got_it
        if data.got_it:
            monitor.is_active = False
            remove_monitor_job(monitor_id)

    if data.is_active is not None and not monitor.got_it:
        monitor.is_active = data.is_active
        if data.is_active:
            add_monitor_job(monitor.id, monitor.check_interval)
        else:
            remove_monitor_job(monitor.id)

    if data.check_interval is not None:
        monitor.check_interval = data.check_interval
        if monitor.is_active and not monitor.got_it:
            add_monitor_job(monitor.id, monitor.check_interval)

    db.commit()
    db.refresh(monitor)
    return monitor


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = db.get(Monitor, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    remove_monitor_job(monitor_id)
    db.delete(monitor)
    db.commit()


@router.post("/{monitor_id}/check-now", response_model=MonitorResponse)
def check_now(monitor_id: int, db: Session = Depends(get_db)):
    """Trigger an immediate check outside the schedule."""
    from app.scheduler import _run_check
    monitor = db.get(Monitor, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    _run_check(monitor_id, force_notify=True)
    db.refresh(monitor)
    return monitor
