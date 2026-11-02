from datetime import date, datetime, time, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.booking_service import (
    cancel_booking,
    confirm_booking,
    create_booking,
    get_available_slots,
)
from core.models import Booking


@pytest.mark.asyncio
async def test_midnight_wrap_and_out_of_bounds_booking_rejected(db_session: AsyncSession):
    target_date = date.today() + timedelta(days=2)

    # Attempt booking that ends past salon closing (21:00)
    with pytest.raises(ValueError, match="выходит за рамки рабочего графика"):
        await create_booking(
            session=db_session,
            client_telegram_id=999000101,
            client_name="Дарья",
            client_phone="+79991112233",
            master_id=1,
            service_id=1,  # 90 min
            booking_date=target_date,
            start_time=time(20, 0),  # 20:00 + 90m = 21:30 (exceeds 21:00!)
        )

    # Attempt booking at or after closing time (e.g. 21:00 or 22:00)
    with pytest.raises(ValueError, match="выходит за рамки рабочего графика"):
        await create_booking(
            session=db_session,
            client_telegram_id=999000101,
            client_name="Дарья",
            client_phone="+79991112233",
            master_id=1,
            service_id=2,  # 30 min
            booking_date=target_date,
            start_time=time(21, 30),
        )


@pytest.mark.asyncio
async def test_slots_for_past_date_returns_empty(db_session: AsyncSession):
    yesterday = date.today() - timedelta(days=1)
    slots = await get_available_slots(
        session=db_session,
        master_id=1,
        service_id=2,
        target_date=yesterday,
    )
    assert slots == [], "Slots for past dates must be strictly empty"


@pytest.mark.asyncio
async def test_confirm_and_cancel_preserves_relationships_without_missing_greenlet(
    db_session: AsyncSession,
):
    target_date = date.today() + timedelta(days=2)

    booking = await create_booking(
        session=db_session,
        client_telegram_id=999000101,
        client_name="Дарья",
        client_phone="+79991112233",
        master_id=1,
        service_id=2,
        booking_date=target_date,
        start_time=time(12, 0),
    )

    # Confirm
    confirmed = await confirm_booking(
        session=db_session,
        booking_id=booking.id,
        admin_telegram_id=5568814893,
    )
    assert confirmed.status == "confirmed"
    # Access relationships directly — should NOT raise MissingGreenlet!
    assert confirmed.client_user.telegram_id == 999000101
    assert confirmed.master.full_name == "Анна Смирнова"
    assert confirmed.service.duration_minutes == 30

    # Cancel
    cancelled = await cancel_booking(
        session=db_session,
        booking_id=booking.id,
        actor_telegram_id=5568814893,
        is_admin_action=True,
    )
    assert cancelled.status == "cancelled_by_admin"
    assert cancelled.client_user.full_name == "Дарья"


@pytest.mark.asyncio
async def test_admin_block_invalid_time_returns_400_not_500(client: AsyncClient):
    res = await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": "2026-11-05",
            "start_time": "invalid_time",
            "end_time": "14:00",
            "reason": "Тест",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res.status_code == 400
    assert "Некорректный формат" in res.json()["detail"]


@pytest.mark.asyncio
async def test_client_booking_receipt_and_admin_cancellation_notifications(
    client: AsyncClient,
    db_session: AsyncSession,
):
    from unittest.mock import AsyncMock, MagicMock
    import api.routes_client as routes_client
    from ui.keyboards import client_my_bookings_keyboard
    from ui.dashboards import contact_dashboard

    # Mock telegram bot
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    routes_client.telegram_bot_instance = mock_bot

    target_date = (date.today() + timedelta(days=4)).strftime("%Y-%m-%d")

    # 1. Create booking via API
    res = await client.post(
        "/api/bookings",
        json={
            "master_id": 1,
            "service_id": 2,
            "date": target_date,
            "start_time": "14:00",
            "client_name": "Елена",
            "client_phone": "+79993332211",
        },
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res.status_code == 200
    booking_id = res.json()["booking_id"]

    # Verify bot sent message to admin AND to the client (999000101)
    call_chat_ids = [call.kwargs.get("chat_id") for call in mock_bot.send_message.call_args_list]
    assert 999000101 in call_chat_ids, "Client must receive confirmation message in Telegram"

    # 2. Verify client keyboard renders cancel button for active booking
    booking_obj = await db_session.get(Booking, booking_id)
    kb = client_my_bookings_keyboard([booking_obj])
    buttons = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"client_cancel:{booking_id}" in buttons, "Active booking must have cancel button in client keyboard"

    # 3. Client cancels via API
    mock_bot.send_message.reset_mock()
    res_cancel = await client.post(
        f"/api/bookings/{booking_id}/cancel",
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_cancel.status_code == 200

    # Verify admins got notified of client cancellation
    cancel_calls = [call.kwargs.get("chat_id") for call in mock_bot.send_message.call_args_list]
    assert any(admin_id in cancel_calls for admin_id in routes_client.settings.admin_telegram_ids), "Admins must be alerted of client cancellation"

    # 4. Verify contact dashboard does not leak hardcoded author handles
    contacts = contact_dashboard()
    assert "@nail_atelier_admin" not in contacts
    assert "3 минуты от метро" not in contacts



@pytest.mark.asyncio
async def test_complete_booking_flow(client: AsyncClient, db_session: AsyncSession):
    target_date = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
    res = await client.post(
        "/api/bookings",
        json={
            "master_id": 1,
            "service_id": 2,
            "date": target_date,
            "start_time": "15:00",
            "client_name": "Анастасия",
            "client_phone": "+79998881122",
        },
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res.status_code == 200
    booking_id = res.json()["booking_id"]

    # Admin confirms
    await client.post(f"/api/admin/bookings/{booking_id}/confirm", headers={"X-Dev-User-Id": "5568814893"})

    # Admin completes visit
    res_complete = await client.post(
        f"/api/admin/bookings/{booking_id}/complete",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_complete.status_code == 200
    assert res_complete.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_unblock_interval_flow(client: AsyncClient):
    target_date = (date.today() + timedelta(days=6)).strftime("%Y-%m-%d")
    # 1. Block interval
    res_blk = await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": target_date,
            "start_time": "13:00",
            "end_time": "14:00",
            "reason": "Обед",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_blk.status_code == 200
    block_id = res_blk.json()["id"]

    # 2. Unblock interval
    res_unblk = await client.delete(
        f"/api/admin/block/{block_id}",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_unblk.status_code == 200
    assert res_unblk.json()["success"] is True


@pytest.mark.asyncio
async def test_any_master_booking_flow(client: AsyncClient):
    target_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    # Slots with master_id=0
    res_slots = await client.get(f"/api/slots?master_id=0&service_id=2&date={target_date}")
    assert res_slots.status_code == 200
    slots = res_slots.json()
    assert len(slots) > 0

    # Book with master_id=0
    res_book = await client.post(
        "/api/bookings",
        json={
            "master_id": 0,
            "service_id": 2,
            "date": target_date,
            "start_time": slots[0]["start_time"],
            "client_name": "Клиент Любой",
            "client_phone": "+79991230000",
        },
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_book.status_code == 200
    data = res_book.json()
    assert data["success"] is True
    assert data["master"] is not None
    assert data["master"]["full_name"]


def test_admin_router_handlers_registered():
    from handlers.admin import admin_router
    # Verify router has registered message and callback query handlers
    assert len(admin_router.message.handlers) >= 7
    assert len(admin_router.callback_query.handlers) >= 15


@pytest.mark.asyncio
async def test_admin_profile_not_overwritten_by_manual_booking(db_session: AsyncSession):
    from core.models import User
    from sqlalchemy import select

    admin_id = 5568814893
    # 1. Setup admin user in DB
    res = await db_session.execute(select(User).where(User.telegram_id == admin_id))
    admin_user = res.scalar_one_or_none()
    if not admin_user:
        admin_user = User(
            telegram_id=admin_id,
            full_name="Владелец Студии",
            phone="+79990001122",
            role="admin",
        )
        db_session.add(admin_user)
        await db_session.commit()
    else:
        admin_user.full_name = "Владелец Студии"
        admin_user.phone = "+79990001122"
        admin_user.role = "admin"
        await db_session.commit()

    # 2. Call create_booking with admin ID but client's name/phone
    target_date = date.today() + timedelta(days=5)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=admin_id,
        client_name="Елена Клиентка",
        client_phone="+79998887766",
        master_id=1,
        service_id=2,
        booking_date=target_date,
        start_time=time(14, 0),
        comment="Ручная запись",
    )
    assert booking.id is not None

    # 3. Assert admin's name and phone were NOT overwritten!
    await db_session.refresh(admin_user)
    assert admin_user.full_name == "Владелец Студии"
    assert admin_user.phone == "+79990001122"
    assert admin_user.role == "admin"


@pytest.mark.asyncio
async def test_client_create_booking_api_returns_master_without_missing_greenlet(client: AsyncClient):
    target_date = (date.today() + timedelta(days=8)).strftime("%Y-%m-%d")
    res_book = await client.post(
        "/api/bookings",
        json={
            "master_id": 1,
            "service_id": 2,
            "date": target_date,
            "start_time": "15:00",
            "client_name": "Тестовый Клиент",
            "client_phone": "+79995554433",
            "comment": "Пожелания без ошибок",
        },
        headers={"X-Dev-User-Id": "999000202"},
    )
    assert res_book.status_code == 200
    data = res_book.json()
    assert data["success"] is True
    assert data["booking_id"] is not None
    assert data["master"] is not None
    assert data["master"]["id"] == 1
    assert data["master"]["full_name"] != ""


@pytest.mark.asyncio
async def test_master_role_not_overwritten_by_get_current_user(db_session: AsyncSession):
    from core.models import User
    from core.security import get_current_user

    # Create master user
    master_tg_id = 777000333
    master_user = User(
        telegram_id=master_tg_id,
        full_name="Мастер Анна",
        role="master",
    )
    db_session.add(master_user)
    await db_session.commit()

    # Emulate request with X-Dev-User-Id
    user = await get_current_user(x_dev_user_id=str(master_tg_id), db=db_session)
    assert user.role == "master"
    assert user.telegram_id == master_tg_id


def test_single_instance_lock_pid_check():
    import os
    from core.lock import SingleInstanceLock

    # Current process PID must be detected as running
    current_pid = os.getpid()
    assert SingleInstanceLock._is_pid_running(current_pid) is True
    # Negative or 0 PID must be false
    assert SingleInstanceLock._is_pid_running(0) is False
    assert SingleInstanceLock._is_pid_running(-1) is False


@pytest.mark.asyncio
async def test_admin_services_catalog_price_and_toggle(client: AsyncClient):
    # 1. List all services
    res_list = await client.get("/api/admin/services", headers={"X-Dev-User-Id": "5568814893"})
    assert res_list.status_code == 200
    services = res_list.json()
    assert len(services) > 0
    target_id = services[0]["id"]
    orig_price = services[0]["price"]
    orig_active = services[0]["is_active"]

    # 2. Update price
    res_price = await client.post(
        f"/api/admin/services/{target_id}/price",
        json={"price": 3500.0},
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_price.status_code == 200
    assert res_price.json()["price"] == 3500.0

    # 3. Toggle active
    res_toggle = await client.post(
        f"/api/admin/services/{target_id}/toggle",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_active"] != orig_active


@pytest.mark.asyncio
async def test_admin_manual_booking_endpoint(client: AsyncClient):
    target_date = (date.today() + timedelta(days=9)).strftime("%Y-%m-%d")
    res_mb = await client.post(
        "/api/admin/manual-booking",
        json={
            "master_id": 1,
            "service_id": 1,
            "date": target_date,
            "start_time": "12:00",
            "client_name": "Виктория VIP",
            "client_phone": "+79998881122",
            "comment": "Через Mini App CRM",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_mb.status_code == 200
    data = res_mb.json()
    assert data["success"] is True
    assert data["status"] == "confirmed"

    # Check schedule returns stats and client_telegram_id
    res_sch = await client.get(
        f"/api/admin/schedule?date={target_date}",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_sch.status_code == 200
    sch_data = res_sch.json()
    assert "stats" in sch_data
    assert sch_data["stats"]["confirmed"] >= 1
    assert any(b["client_name"] == "Виктория VIP" for b in sch_data["bookings"])


@pytest.mark.asyncio
async def test_admin_masters_crud_and_toggle(client: AsyncClient):
    # 1. Create master
    res_create = await client.post(
        "/api/admin/masters",
        json={
            "full_name": "Мария Свечникова",
            "specialization": "Мастер аэрографии и японского маникюра",
            "experience_years": 6,
            "is_active": True,
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_create.status_code == 200
    master_data = res_create.json()
    assert master_data["success"] is True
    master_id = master_data["id"]
    assert master_data["full_name"] == "Мария Свечникова"
    assert master_data["experience_years"] == 6

    # 2. List masters
    res_list = await client.get(
        "/api/admin/masters",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_list.status_code == 200
    masters = res_list.json()
    found = next((m for m in masters if m["id"] == master_id), None)
    assert found is not None
    assert found["specialization"] == "Мастер аэрографии и японского маникюра"

    # 3. Update master
    res_update = await client.put(
        f"/api/admin/masters/{master_id}",
        json={
            "full_name": "Мария Свечникова (Топ)",
            "experience_years": 7,
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["full_name"] == "Мария Свечникова (Топ)"
    assert res_update.json()["experience_years"] == 7

    # 4. Toggle master active
    res_toggle = await client.post(
        f"/api/admin/masters/{master_id}/toggle",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_services_crud(client: AsyncClient):
    # 1. Create new service
    res_create = await client.post(
        "/api/admin/services",
        json={
            "category": "VIP-Уход",
            "name": "Японский эко-глянцевание ногтей",
            "description": "Лечебная полировка натуральной минеральной пастой Masura",
            "duration_minutes": 50,
            "price": 2800.0,
            "is_active": True,
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_create.status_code == 200
    svc_data = res_create.json()
    svc_id = svc_data["id"]
    assert svc_data["category"] == "VIP-Уход"
    assert svc_data["name"] == "Японский эко-глянцевание ногтей"
    assert svc_data["price"] == 2800.0

    # 2. Update service (edit description and price)
    res_update = await client.put(
        f"/api/admin/services/{svc_id}",
        json={
            "description": "Обновленное описание процедуры с питательной сывороткой",
            "price": 3100.0,
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["price"] == 3100.0
    assert "питательной сывороткой" in res_update.json()["description"]


@pytest.mark.asyncio
async def test_admin_salon_settings_update(client: AsyncClient):
    # 1. Update salon settings
    res_update = await client.put(
        "/api/admin/salon",
        json={
            "address": "г. Москва, ул. Большая Дмитровка, д. 12, стр. 1, этаж 3",
            "working_hours": "Ежедневно с 09:00 до 22:00",
            "phone": "+7 (999) 000-11-22",
            "description": "Флагманская студия ногтевого сервиса премиум-класса",
            "contact_telegram": "@atelier_support",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_update.status_code == 200
    data = res_update.json()
    assert data["success"] is True
    assert data["salon"]["address"] == "г. Москва, ул. Большая Дмитровка, д. 12, стр. 1, этаж 3"
    assert data["salon"]["working_hours"] == "Ежедневно с 09:00 до 22:00"

    # 2. Check public client endpoint reflects changes
    res_client = await client.get("/api/salon")
    assert res_client.status_code == 200
    client_salon = res_client.json()["salon"]
    assert client_salon["address"] == "г. Москва, ул. Большая Дмитровка, д. 12, стр. 1, этаж 3"
    assert client_salon["phone"] == "+7 (999) 000-11-22"


def test_keyboard_urls_have_explicit_tabs():
    from ui.keyboards import client_main_keyboard, admin_main_keyboard

    client_kb = client_main_keyboard(is_admin=True)
    hero_btn = client_kb.inline_keyboard[0][0]
    assert hero_btn.text == "Открыть кабинет"
    assert hero_btn.web_app is not None
    assert "/miniapp/" in hero_btn.web_app.url

    # Ensure duplicate "Панель администратора (Mini App)" button is removed from main menu
    admin_miniapp_btns = [b for row in client_kb.inline_keyboard for b in row if "Mini App" in (b.text or "")]
    assert len(admin_miniapp_btns) == 0

    admin_kb = admin_main_keyboard()
    admin_ma_btn = admin_kb.inline_keyboard[0][0]
    assert admin_ma_btn.web_app is not None
    assert "?tab=admin" in admin_ma_btn.web_app.url


@pytest.mark.asyncio
async def test_idempotent_confirm_and_live_bot_card_sync(client: AsyncClient, db_session: AsyncSession):
    from unittest.mock import AsyncMock, MagicMock
    import api.routes_client as routes_client

    mock_bot = MagicMock()
    sent_msg = MagicMock()
    sent_msg.message_id = 777888
    mock_bot.send_message = AsyncMock(return_value=sent_msg)
    mock_bot.edit_message_text = AsyncMock()
    routes_client.telegram_bot_instance = mock_bot

    target_date = (date.today() + timedelta(days=10)).strftime("%Y-%m-%d")

    # 1. Create booking via API (records message_id=777888 in booking_messages)
    res_book = await client.post(
        "/api/bookings",
        json={
            "master_id": 1,
            "service_id": 2,
            "date": target_date,
            "start_time": "11:00",
            "client_name": "София",
            "client_phone": "+79991110099",
        },
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_book.status_code == 200
    booking_id = res_book.json()["booking_id"]

    # 2. Confirm via Mini App Admin API -> must edit tracked Telegram message!
    res_conf1 = await client.post(
        f"/api/admin/bookings/{booking_id}/confirm",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_conf1.status_code == 200
    assert res_conf1.json()["status"] == "confirmed"
    assert mock_bot.edit_message_text.called, "Confirming in Mini App must sync Telegram bot card"
    edit_kwargs = mock_bot.edit_message_text.call_args.kwargs
    assert edit_kwargs["message_id"] == 777888
    assert "подтверждена" in edit_kwargs["text"]

    # 3. Confirm a second time (idempotency check — no ValueError!)
    res_conf2 = await client.post(
        f"/api/admin/bookings/{booking_id}/confirm",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_conf2.status_code == 200
    assert res_conf2.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_block_interval_rejects_past_and_duplicates(client: AsyncClient):
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    future_date = (date.today() + timedelta(days=11)).strftime("%Y-%m-%d")

    # 1. Past date must be rejected
    res_past = await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": yesterday,
            "start_time": "13:00",
            "end_time": "14:00",
            "reason": "Обед",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_past.status_code == 400
    assert "прошедш" in res_past.json()["detail"].lower()

    # 2. First block on future_date succeeds
    res_ok = await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": future_date,
            "start_time": "13:00",
            "end_time": "14:00",
            "reason": "Обед",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_ok.status_code == 200

    # 3. Duplicate / overlapping block for same master & date must be rejected!
    res_dup = await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": future_date,
            "start_time": "13:00",
            "end_time": "14:00",
            "reason": "Обед дубль",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_dup.status_code == 400
    assert "уже установлен перерыв" in res_dup.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_master_and_service_archives_cleanly(client: AsyncClient):
    # 1. Create a temporary master and delete them
    res_m = await client.post(
        "/api/admin/masters",
        json={
            "full_name": "Временный Мастер",
            "specialization": "Тест",
            "experience_years": 2,
            "telegram_username": "@megausername1",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_m.status_code == 200
    m_id = res_m.json()["id"]
    assert res_m.json()["telegram_username"] == "megausername1"

    res_del_m = await client.delete(
        f"/api/admin/masters/{m_id}",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_del_m.status_code == 200

    # Verify deleted master is no longer in /api/admin/masters or /api/masters
    admin_masters = (await client.get("/api/admin/masters", headers={"X-Dev-User-Id": "5568814893"})).json()
    assert all(m["id"] != m_id for m in admin_masters)

    # 2. Create a temporary service and delete it
    res_s = await client.post(
        "/api/admin/services",
        json={
            "category": "Тест",
            "name": "Временная услуга",
            "duration_minutes": 30,
            "price": 900.0,
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_s.status_code == 200
    s_id = res_s.json()["id"]

    res_del_s = await client.delete(
        f"/api/admin/services/{s_id}",
        headers={"X-Dev-User-Id": "5568814893"},
    )
    assert res_del_s.status_code == 200
    admin_services = (await client.get("/api/admin/services", headers={"X-Dev-User-Id": "5568814893"})).json()
    assert all(s["id"] != s_id for s in admin_services)


@pytest.mark.asyncio
async def test_slots_include_unavailable_and_load_balancing(client: AsyncClient):
    target_date = (date.today() + timedelta(days=12)).strftime("%Y-%m-%d")

    # Block 13:00-14:00 for master 1
    await client.post(
        "/api/admin/block",
        json={
            "master_id": 1,
            "date": target_date,
            "start_time": "13:00",
            "end_time": "14:00",
            "reason": "Перерыв",
        },
        headers={"X-Dev-User-Id": "5568814893"},
    )

    # Request slots with include_unavailable=true for master 1
    res_slots = await client.get(
        f"/api/slots?master_id=1&service_id=2&date={target_date}&include_unavailable=true"
    )
    assert res_slots.status_code == 200
    slots = res_slots.json()
    slot_1300 = next((s for s in slots if s["start_time"] == "13:00"), None)
    assert slot_1300 is not None
    assert slot_1300["available"] is False
    assert slot_1300["reason"] == "break"

    # Book "Любой мастер" (master_id=0) at 13:00 -> must NOT assign Master 1 (who is on break)!
    res_any = await client.post(
        "/api/bookings",
        json={
            "master_id": 0,
            "service_id": 2,
            "date": target_date,
            "start_time": "13:00",
            "client_name": "Проверка Баланса",
            "client_phone": "+79990009988",
        },
        headers={"X-Dev-User-Id": "999000101"},
    )
    assert res_any.status_code == 200
    assigned_master = res_any.json()["master"]
    assert assigned_master["id"] != 1, "Master on break must never be assigned by 'Any master'!"


def test_contact_dashboard_omits_empty_landmark_and_no_duplicate_phone():
    from core.config import settings
    from ui.dashboards import contact_dashboard

    orig_salon = dict(settings.salon)
    try:
        settings.salon["landmark"] = ""
        settings.salon["contact_telegram"] = ""
        settings.salon["admin_contact"] = ""
        settings.salon["phone"] = "+7 (999) 999-99-99"

        text = contact_dashboard()
        assert "Ориентир:" not in text
        assert "Telegram / WhatsApp:" not in text
        assert text.count("+7 (999) 999-99-99") == 1
    finally:
        settings.salon.clear()
        settings.salon.update(orig_salon)


@pytest.mark.asyncio
async def test_master_binding_and_order_claim(db_session: AsyncSession):
    from core.booking_service import (
        bind_master_by_telegram,
        claim_booking_by_master,
        create_booking,
    )
    from core.models import Master

    # 1. Ensure master exists with username megausername1
    res = await db_session.execute(select(Master).where(Master.id == 1))
    m1 = res.scalar_one()
    m1.telegram_username = "@megausername1"
    m1.telegram_id = None
    await db_session.commit()

    # 2. Bind master via telegram
    bound = await bind_master_by_telegram(db_session, telegram_id=777001, username="megausername1")
    assert bound is not None
    assert bound.id == 1
    assert bound.telegram_id == 777001

    # 3. Create a booking with is_any_master=True
    target_date = date.today() + timedelta(days=14)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=999888,
        client_name="Тест Клейм",
        client_phone="+79991112233",
        master_id=0,
        service_id=1,
        booking_date=target_date,
        start_time=time(15, 0),
    )
    assert booking.is_any_master is True

    # 4. Master 1 claims order
    ok, msg, claimed = await claim_booking_by_master(db_session, booking.id, master_telegram_id=777001)
    assert ok is True
    assert claimed.status == "confirmed"
    assert claimed.master_id == 1

    # 5. Second attempt to claim rejected
    ok2, msg2, claimed2 = await claim_booking_by_master(db_session, booking.id, master_telegram_id=999999)
    assert ok2 is False
    assert "уже принят" in msg2 or "не зарегистрированы" in msg2


@pytest.mark.asyncio
async def test_master_decline_and_client_reassign_flow(db_session: AsyncSession):
    from core.booking_service import (
        client_accept_any_master,
        create_booking,
        decline_booking_by_master,
    )
    from core.models import Master

    # Setup master 1 with telegram_id 777001
    res = await db_session.execute(select(Master).where(Master.id == 1))
    m1 = res.scalar_one()
    m1.telegram_id = 777001
    await db_session.commit()

    target_date = date.today() + timedelta(days=5)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=888777,
        client_name="Клиент Персональный",
        client_phone="+79998887766",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(16, 0),
    )
    assert booking.is_any_master is False

    # Master 1 declines personal booking -> awaiting_client_choice
    ok, flow_status, b_updated = await decline_booking_by_master(db_session, booking.id, master_telegram_id=777001)
    assert ok is True
    assert flow_status == "declined_specific"
    assert b_updated.status == "awaiting_client_choice"
    assert b_updated.client_reassign_deadline is not None
    assert "1" in (b_updated.declined_master_ids or "")

    # Client accepts any other master
    ok_c, msg_c, reassigned = await client_accept_any_master(db_session, booking.id, client_telegram_id=888777)
    assert ok_c is True
    assert reassigned.status == "pending"
    assert reassigned.is_any_master is True
    assert reassigned.client_reassign_deadline is None


@pytest.mark.asyncio
async def test_watchdog_auto_assigns_expired_pending_booking(db_session: AsyncSession):
    from core.booking_service import create_booking, process_expired_bookings

    target_date = date.today() + timedelta(days=6)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=666555,
        client_name="Клиент Таймаут",
        client_phone="+79995554433",
        master_id=0,
        service_id=1,
        booking_date=target_date,
        start_time=time(12, 0),
    )
    # Set expired assignment deadline
    booking.assignment_deadline = datetime.now() - timedelta(minutes=5)
    await db_session.commit()

    processed = await process_expired_bookings(db_session, bot=None)
    assert processed >= 1

    await db_session.refresh(booking)
    assert booking.status == "confirmed"
    assert booking.assignment_deadline is None


@pytest.mark.asyncio
async def test_negative_synthetic_tg_id_does_not_generate_invalid_button_url():
    from ui.keyboards import admin_booking_keyboard, admin_notification_keyboard
    from ui.dashboards import admin_booking_card
    from core.models import Booking, User

    # 1. Keyboard checks
    kb_admin = admin_booking_keyboard(1, "pending", client_telegram_id=-123456)
    for row in kb_admin.inline_keyboard:
        for btn in row:
            if btn.url:
                assert not btn.url.startswith("tg://user?id=-")

    kb_notify = admin_notification_keyboard(1, client_telegram_id=-123456)
    for row in kb_notify.inline_keyboard:
        for btn in row:
            if btn.url:
                assert not btn.url.startswith("tg://user?id=-")

    # 2. Dashboard check
    fake_user = User(id=999, telegram_id=-123456, full_name="Тест Без ТГ", phone="+79991112233")
    fake_booking = Booking(
        id=999,
        client_user=fake_user,
        booking_date=date.today(),
        start_time=time(12, 0),
        end_time=time(13, 0),
        status="pending",
    )
    card_text = admin_booking_card(fake_booking)
    assert "tg://user?id=-" not in card_text
    assert "Не привязан" in card_text


@pytest.mark.asyncio
async def test_cannot_claim_booking_assigned_to_specific_master(db_session: AsyncSession):
    from core.booking_service import claim_booking_by_master, create_booking
    from core.models import Master

    # Ensure master 2 exists
    res = await db_session.execute(select(Master).where(Master.id == 2))
    m2 = res.scalar_one_or_none()
    if not m2:
        m2 = Master(id=2, full_name="Мастер Два", is_active=True, telegram_id=888002)
        db_session.add(m2)
    else:
        m2.telegram_id = 888002
        m2.is_active = True
        m2.archived_at = None
    await db_session.commit()

    target_date = date.today() + timedelta(days=7)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=111222,
        client_name="Клиент К Мастеру 1",
        client_phone="+79993332211",
        master_id=1,  # specifically chosen master 1
        service_id=1,
        booking_date=target_date,
        start_time=time(14, 0),
    )
    assert booking.is_any_master is False
    assert booking.master_id == 1

    # Master 2 attempts to claim Master 1's personal booking
    ok, msg, b_res = await claim_booking_by_master(db_session, booking.id, master_telegram_id=888002)
    assert ok is False
    assert "конкретному мастеру" in msg
    assert b_res.master_id == 1


@pytest.mark.asyncio
async def test_cannot_decline_or_cancel_completed_booking(db_session: AsyncSession):
    from core.booking_service import cancel_booking, complete_booking, create_booking, decline_booking_by_master

    target_date = date.today() + timedelta(days=8)
    booking = await create_booking(
        session=db_session,
        client_telegram_id=444333,
        client_name="Клиент Завершённый",
        client_phone="+79997776655",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(11, 0),
    )
    booking = await complete_booking(db_session, booking.id, admin_telegram_id=5568814893)
    assert booking.status == "completed"

    # Setup master 1 telegram ID
    from core.models import Master
    res_m = await db_session.execute(select(Master).where(Master.id == 1))
    m1 = res_m.scalar_one()
    m1.telegram_id = 777001
    await db_session.commit()

    # Decline must be rejected
    ok, msg, _ = await decline_booking_by_master(db_session, booking.id, master_telegram_id=777001)
    assert ok is False
    assert "completed" in msg

    # Cancellation must be rejected
    with pytest.raises(ValueError, match="Нельзя отменить уже завершённый визит"):
        await cancel_booking(db_session, booking.id, actor_telegram_id=5568814893, is_admin_action=True)


@pytest.mark.asyncio
async def test_admin_reassign_rejects_busy_or_break_master(db_session: AsyncSession):
    from core.booking_service import admin_reassign_booking, block_time_interval, create_booking
    from core.models import Master

    target_date = date.today() + timedelta(days=9)
    # Master 1 booking
    b1 = await create_booking(
        session=db_session,
        client_telegram_id=555111,
        client_name="Запись 1",
        client_phone="+79991110001",
        master_id=1,
        service_id=1,
        booking_date=target_date,
        start_time=time(12, 0),
    )

    # Master 2 break at 12:00-13:00
    await block_time_interval(
        session=db_session,
        master_id=2,
        block_date=target_date,
        start_time=time(12, 0),
        end_time=time(13, 0),
        reason="Обед",
        admin_telegram_id=5568814893,
    )

    # Admin attempts to reassign b1 to master 2 who has a break
    with pytest.raises(ValueError, match="имеет перерыв"):
        await admin_reassign_booking(
            session=db_session,
            booking_id=b1.id,
            new_master_id=2,
            admin_telegram_id=5568814893,
        )




