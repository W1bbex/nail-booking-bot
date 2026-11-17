from contextlib import asynccontextmanager
from datetime import timedelta, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.booking_service import create_booking
from core.models import Booking, BookingMessage, Master
from core.slot_service import get_moscow_now
from handlers import master as handler
from notifiers.booking_notifier import sync_booking_messages


@pytest.mark.asyncio
async def test_last_master_decline_cancels_booking_and_notifies_client(db_session, monkeypatch):
    masters = list((await db_session.execute(select(Master))).scalars())
    masters[0].telegram_id = 201
    masters[1].is_active = False
    await db_session.commit()
    booking = await create_booking(db_session, 999000101, "Synthetic Client", "+70000000000",
                                   0, 2, get_moscow_now().date() + timedelta(days=2), time(12))

    @asynccontextmanager
    async def session():
        yield db_session

    monkeypatch.setattr(handler, "get_session", session)
    bot = SimpleNamespace(send_message=AsyncMock(), edit_message_text=AsyncMock())
    call = SimpleNamespace(data=f"master_decline:{booking.id}", from_user=SimpleNamespace(id=201),
                           bot=bot, answer=AsyncMock(), message=SimpleNamespace(edit_text=AsyncMock()))
    await handler.cb_master_decline(call)
    assert booking.status == "cancelled_by_admin"
    client_calls = [c for c in bot.send_message.await_args_list if c.args and c.args[0] == 999000101]
    assert len(client_calls) == 1
    assert "отмен" in client_calls[0].args[1].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled_by_client", "cancelled_by_admin", "completed", "awaiting_client_choice"])
async def test_personal_and_broadcast_master_cards_follow_terminal_status(db_session, status):
    booking = Booking(client_user_id=1, master_id=1, service_id=1,
                      booking_date=get_moscow_now().date() + timedelta(days=2),
                      start_time=time(12), end_time=time(13), price=0, status=status,
                      client_name="Synthetic Client", client_phone="synthetic-contact")
    db_session.add(booking)
    await db_session.commit()
    db_session.add_all([BookingMessage(booking_id=booking.id, chat_id=201, message_id=10, kind="master_card"),
                        BookingMessage(booking_id=booking.id, chat_id=202, message_id=11, kind="master_claim")])
    await db_session.commit()
    bot = SimpleNamespace(edit_message_text=AsyncMock())
    await sync_booking_messages(db_session, bot, booking.id)
    calls = {c.kwargs["chat_id"]: c.kwargs for c in bot.edit_message_text.await_args_list}
    assert set(calls) == {201, 202}
    assert all(c["reply_markup"] is None for c in calls.values())


@pytest.mark.asyncio
async def test_reassigned_personal_card_loses_actions_for_old_master(db_session):
    masters = list((await db_session.execute(select(Master).order_by(Master.id))).scalars())
    masters[0].telegram_id, masters[1].telegram_id = 201, 202
    booking = Booking(client_user_id=1, master_id=2, service_id=1,
                      booking_date=get_moscow_now().date() + timedelta(days=2),
                      start_time=time(12), end_time=time(13), price=0, status="confirmed",
                      client_name="Synthetic Client", client_phone="synthetic-contact")
    db_session.add(booking)
    await db_session.commit()
    db_session.add_all([BookingMessage(booking_id=booking.id, chat_id=201, message_id=10, kind="master_card"),
                        BookingMessage(booking_id=booking.id, chat_id=202, message_id=11, kind="master_card")])
    await db_session.commit()
    bot = SimpleNamespace(edit_message_text=AsyncMock())
    await sync_booking_messages(db_session, bot, booking.id)
    calls = {c.kwargs["chat_id"]: c.kwargs for c in bot.edit_message_text.await_args_list}
    assert set(calls) == {201, 202}
    assert calls[201]["reply_markup"] is None
    assert calls[202]["reply_markup"] is not None
