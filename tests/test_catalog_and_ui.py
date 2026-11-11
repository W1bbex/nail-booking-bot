from datetime import date, datetime, time, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
async def test_backup_closes_source_on_dest_error(tmp_path, monkeypatch):
    import sqlite3
    from core.backup import backup_sqlite_database
    db = tmp_path / "test.db"
    db.write_bytes(b"SQLite format 3\x00")

    orig_connect = sqlite3.connect
    calls = []
    def mock_connect(path, *args, **kwargs):
        if "studio_" in str(path):
            raise OSError("destination access error")
        conn = orig_connect(path, *args, **kwargs)
        calls.append((path, conn))
        return conn

    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    res = backup_sqlite_database(db_path=db, backup_dir=tmp_path / "backups")
    assert res is None
    # Verify src_conn was closed despite dest_conn error
    for path, conn in calls:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            conn.execute("SELECT 1")


def test_cors_headers_contain_standard_web_headers():
    from api.app import app
    from starlette.middleware.cors import CORSMiddleware
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            headers = middleware.kwargs.get("allow_headers", [])
            assert "Accept" in headers
            assert "Accept-Language" in headers
            break
    else:
        pytest.fail("CORSMiddleware not found")


@pytest.mark.asyncio
async def test_dev_mode_blocked_when_external_x_forwarded_for_present(client: AsyncClient, monkeypatch):
    from core.config import settings
    monkeypatch.setattr(settings, "bot_token", "987654321:ValidLookingBotTokenSecret")
    res = await client.get(
        "/api/me",
        headers={
            "X-Dev-User-Id": "5568814893",
            "X-Forwarded-For": "203.0.113.50",
        },
    )
    assert res.status_code == 401
