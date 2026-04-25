import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.db import CurrSession
from models.admin import AdminRole, AdminUser, AuditLog
from schemas.admin import AdminUserLoginSchema, AdminUserReadSchema, AuthTokenResponseSchema
from settings.config import get_settings


settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("utf-8"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 310_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${_b64url_encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    computed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations_raw),
    )
    return hmac.compare_digest(_b64url_encode(computed), digest)


def serialize_admin_user(user: AdminUser) -> AdminUserReadSchema:
    return AdminUserReadSchema(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role.value if isinstance(user.role, AdminRole) else user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def create_access_token(user: AdminUser) -> str:
    expires_at = int(time.time()) + settings.ADMIN_ACCESS_TOKEN_TTL_MINUTES * 60
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value if isinstance(user.role, AdminRole) else user.role,
        "exp": expires_at,
    }
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        settings.ADMIN_AUTH_SECRET.encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_segment}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict:
    try:
        payload_segment, signature_segment = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    expected_signature = hmac.new(
        settings.ADMIN_AUTH_SECRET.encode("utf-8"),
        payload_segment.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(_b64url_encode(expected_signature), signature_segment):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    if payload.get("exp", 0) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def add_audit_log(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    message: str,
    actor_user_id: int | None = None,
    entity_id: str | None = None,
    level: str = "info",
    details: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            level=level,
            message=message,
            details=details or {},
        )
    )


async def ensure_bootstrap_super_admin(session: AsyncSession) -> None:
    existing_admin = await session.scalar(select(func.count(AdminUser.id)))
    if existing_admin:
        return

    admin_user = AdminUser(
        username=settings.ADMIN_BOOTSTRAP_USERNAME,
        full_name=settings.ADMIN_BOOTSTRAP_FULL_NAME,
        password_hash=hash_password(settings.ADMIN_BOOTSTRAP_PASSWORD),
        role=AdminRole.super_admin,
        is_active=True,
    )
    session.add(admin_user)
    add_audit_log(
        session,
        action="bootstrap_admin_created",
        entity_type="admin_user",
        entity_id=settings.ADMIN_BOOTSTRAP_USERNAME,
        message="Bootstrap super-admin account created",
        level="warning",
    )
    await session.commit()


async def authenticate_admin(
    session: AsyncSession,
    credentials: AdminUserLoginSchema,
) -> AuthTokenResponseSchema:
    user = await session.scalar(
        select(AdminUser).where(func.lower(AdminUser.username) == credentials.username.lower())
    )
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is deactivated",
        )

    user.last_login_at = datetime.now(timezone.utc)
    add_audit_log(
        session,
        actor_user_id=user.id,
        action="login",
        entity_type="auth",
        entity_id=str(user.id),
        message=f"Admin user {user.username} signed in",
    )
    await session.commit()
    await session.refresh(user)

    return AuthTokenResponseSchema(
        access_token=create_access_token(user),
        user=serialize_admin_user(user),
    )


async def get_current_admin(
    session: CurrSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AdminUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user = await session.get(AdminUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: AdminRole):
    async def dependency(current_user: AdminUser = Depends(get_current_admin)) -> AdminUser:
        current_role = current_user.role.value if isinstance(current_user.role, AdminRole) else current_user.role
        allowed_roles = {
            role.value if isinstance(role, AdminRole) else str(role)
            for role in roles
        }
        if current_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency


async def verify_internal_task_request(request: Request) -> None:
    received_secret = request.headers.get("X-Internal-Task-Secret")
    if received_secret != settings.INTERNAL_TASK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal task access denied",
        )
