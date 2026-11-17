"""
Analytics and financial statistics calculation service.
Pure domain logic: calculating daily/period revenue, occupancy, average check,
and booking status breakdown.
"""
from typing import Any, Dict, Sequence
from core.models import Booking


def calculate_schedule_stats(bookings: Sequence[Booking]) -> Dict[str, Any]:
    """
    Computes revenue and status breakdown for a list of bookings.
    Uses snapshotted booking price when available, falling back to service catalog price.
    """
    revenue = sum(
        (b.price if b.price is not None else (b.service.price if b.service else 0.0))
        for b in bookings
        if b.status in ("confirmed", "completed")
    )
    expected_revenue = sum(
        (b.price if b.price is not None else (b.service.price if b.service else 0.0))
        for b in bookings
        if b.status in ("confirmed", "completed", "pending")
    )
    total_count = len(bookings)
    pending_count = sum(1 for b in bookings if b.status == "pending")
    confirmed_count = sum(1 for b in bookings if b.status == "confirmed")
    completed_count = sum(1 for b in bookings if b.status == "completed")
    cancelled_count = sum(1 for b in bookings if b.status.startswith("cancelled"))
    avg_check = round(revenue / (completed_count + confirmed_count), 0) if (completed_count + confirmed_count) > 0 else 0

    return {
        "revenue": revenue,
        "expected_revenue": expected_revenue,
        "total": total_count,
        "pending": pending_count,
        "confirmed": confirmed_count,
        "completed": completed_count,
        "cancelled": cancelled_count,
        "avg_check": avg_check,
    }
