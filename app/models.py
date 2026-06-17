from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime, timezone
from app.database import Base


class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    phone_number = Column(String(20), nullable=False)  # E.164 format: +919876543210
    check_interval = Column(Integer, default=60)  # minutes
    is_active = Column(Boolean, default=True)
    got_it = Column(Boolean, default=False)  # user marked as received
    status = Column(String(20), default="unknown")  # in_stock | out_of_stock | unknown | error
    price = Column(String(50), nullable=True)
    last_checked = Column(DateTime, nullable=True)
    next_check = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    platform = Column(String(20), default="amul")  # amul | blinkit
    error_message = Column(Text, nullable=True)
