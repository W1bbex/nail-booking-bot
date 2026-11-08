from datetime import date, datetime, time, timezone
from typing import List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    text,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="client")  # client, admin, master
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    bookings: Mapped[List["Booking"]] = relationship("Booking", back_populates="client_user")


class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120))
    specialization: Mapped[str] = mapped_column(String(200), default="")
    experience_years: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, default=None)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, default=None)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)

    bookings: Mapped[List["Booking"]] = relationship("Booking", back_populates="master")
    blocked_intervals: Mapped[List["BlockedInterval"]] = relationship("BlockedInterval", back_populates="master")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(80), default="Маникюр")
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)

    bookings: Mapped[List["Booking"]] = relationship("Booking", back_populates="service")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)

    booking_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time, index=True)
    end_time: Mapped[time] = mapped_column(Time, index=True)

    price: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending, confirmed, cancelled_by_client, cancelled_by_admin, completed, awaiting_client_choice

    is_any_master: Mapped[bool] = mapped_column(Boolean, default=False)
    declined_master_ids: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    assignment_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
    client_reassign_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)

    client_name: Mapped[str] = mapped_column(String(160), default="")
    client_phone: Mapped[str] = mapped_column(String(40), default="")
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    client_user: Mapped["User"] = relationship("User", back_populates="bookings")
    master: Mapped["Master"] = relationship("Master", back_populates="bookings")
    service: Mapped["Service"] = relationship("Service", back_populates="bookings")

    __table_args__ = (
        Index(
            "idx_unique_active_master_slot",
            "master_id",
            "booking_date",
            "start_time",
            unique=True,
            sqlite_where=text("status IN ('pending', 'confirmed', 'awaiting_client_choice')"),
            postgresql_where=text("status IN ('pending', 'confirmed', 'awaiting_client_choice')"),
        ),
    )


class BlockedInterval(Base):
    __tablename__ = "blocked_intervals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    reason: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)

    master: Mapped["Master"] = relationship("Master", back_populates="blocked_intervals")


class BookingMessage(Base):
    __tablename__ = "booking_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), default="admin_card")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

