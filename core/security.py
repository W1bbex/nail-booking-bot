import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from core.logger import setup_logger
from core.models import Master, User

logger = setup_logger("security")

MAX_AUTH_AGE_SECONDS = 86400  # 24 hours


def _is_proxied_external(x_forwarded_for: Optional[str], x_real_ip: Optional[str]) -> bool:
    for raw in (x_forwarded_for, x_real_ip):
        if isinstance(raw, str) and raw.strip():
            ip = raw.split(",")[0].strip().lower()
            if ip not in ("127.0.0.1", "::1", "localhost", "testclient"):
                return True
    return False



def validate_telegram_init_data(init_data: str, bot_token: str) -> Dict[str, Any]:
    if not init_data:
        raise ValueError("Отсутствуют данные авторизации Telegram (initData)")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    pairs.pop("signature", None)
    if not received_hash:
        raise ValueError("Отсутствует контрольный хеш hash в initData")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Подпись Telegram initData не прошла проверку подлинности")

    try:
        auth_date = int(pairs.get("auth_date", "0") or 0)
    except (ValueError, TypeError):
        auth_date = 0

    if not auth_date or (time.time() - auth_date > MAX_AUTH_AGE_SECONDS) or (auth_date > time.time() + 60):
        raise ValueError("Срок действия сессии Telegram истёк или некорректен (auth_date)")

    if "user" in pairs:
        try:
            pairs["user"] = json.loads(pairs["user"])
        except Exception:
            pass

    return pairs


async def get_current_user(
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_dev_user_id: Optional[str] = Header(None, alias="X-Dev-User-Id"),
    x_forwarded_for: Optional[str] = Header(None, alias="X-Forwarded-For"),
    x_real_ip: Optional[str] = Header(None, alias="X-Real-IP"),
    db: AsyncSession = Depends(get_db),
) -> User:
    telegram_id: Optional[int] = None
    full_name: str = "Гость студии"

    # 1. Dev Mode fallback for local browser preview (never allowed via external reverse proxy)
    init_data_str = x_telegram_init_data if isinstance(x_telegram_init_data, str) else None
    is_external_proxy = _is_proxied_external(x_forwarded_for, x_real_ip)
    if settings.dev_mode and not is_external_proxy and (not init_data_str or init_data_str.startswith("dev")):
        if x_dev_user_id and x_dev_user_id.isdigit():
            telegram_id = int(x_dev_user_id)
            full_name = f"Тестовый пользователь #{telegram_id}"
        else:
            # Default to first admin in dev mode if requested, or standard client
            telegram_id = settings.admin_telegram_ids[0] if settings.admin_telegram_ids else 999000111
            full_name = "Тестовый мастер (Dev)"
    else:
        # 2. Production cryptographic verification
        if (not settings.bot_token or "AAFakeToken" in settings.bot_token
                or settings.bot_token.startswith("123456789:")):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Бот ещё не подключён к Telegram",
            )
        if not init_data_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Доступ разрешён только из Telegram Mini App (отсутствует X-Telegram-Init-Data)",
            )

        try:
            parsed = validate_telegram_init_data(init_data_str, settings.bot_token)
            tg_user = parsed.get("user") or {}
            telegram_id = int(tg_user.get("id", 0))
            first = tg_user.get("first_name", "")
            last = tg_user.get("last_name", "")
            full_name = f"{first} {last}".strip() or "Telegram пользователь"
        except Exception as e:
            logger.warning(f"Auth failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Ошибка проверки Telegram авторизации: {e}",
            )

    if not telegram_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не удалось определить Telegram ID")

    # Fetch or auto-register user in DB
    user = (await db.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        is_admin = settings.is_admin(telegram_id)
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            role="admin" if is_admin else "client",
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            await db.rollback()
            user = (await db.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one()
    else:
        # Update admin role dynamically based on settings.admin_telegram_ids without clobbering master role
        if settings.is_admin(telegram_id):
            if user.role != "admin":
                user.role = "admin"
                await db.commit()
                await db.refresh(user)
        elif user.role == "admin":
            # Demoted from admin: restore master role if bound to an active Master, otherwise client
            bound_master = (await db.execute(
                select(Master).where(Master.telegram_id == telegram_id, Master.archived_at.is_(None))
            )).scalar_one_or_none()
            user.role = "master" if bound_master else "client"
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ваш профиль деактивирован")

    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Only configured administrator identities can use the administrator API."""
    if not settings.is_admin(user.telegram_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав: раздел доступен только администраторам",
        )
    return user

def deterministic_virtual_telegram_id(phone: str) -> int:
    """Generates a deterministic negative virtual telegram ID from client phone."""
    import hashlib
    clean = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not clean:
        clean = "0000000000"
    digest = int(hashlib.sha256(clean.encode("utf-8")).hexdigest()[:8], 16)
    return -(digest % 1000000000 + 1)
