"""认证接口：注册 / 登录 / 当前用户 + 鉴权依赖。

企业级要点：
- 注册表单三重校验（后端为准）：用户名格式、邮箱格式、密码强度，重复账号 409
- 登录支持用户名或邮箱，密码错误统一 401（不泄露账号是否存在）
- 业务接口通过 Depends(get_current_user) 保护（chat / selection）
- 密码全程不落明文、不返回给前端
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from tiktok_ecommerce.auth.store import User, UserStore
from tiktok_ecommerce.common.exceptions import UnauthorizedError
from tiktok_ecommerce.common.security import create_token, decode_token
from tiktok_ecommerce.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_user_store() -> UserStore:
    """用户库单例（.env 变更需重启；生产可换外部存储）。"""
    settings = get_settings()
    return UserStore(settings.auth.db_path)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> User:
    """业务接口鉴权依赖：校验 Bearer token（签名 + 过期），返回当前用户。"""
    if cred is None or not cred.credentials:
        raise UnauthorizedError("请先登录")
    try:
        payload = decode_token(cred.credentials, settings.auth.secret)
    except ValueError as e:
        raise UnauthorizedError(str(e)) from e
    user = store.get_by_username(payload.sub)
    if user is None:
        raise UnauthorizedError("账号不存在或已被删除")
    return user


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=30, description="用户名")
    email: str = Field(..., max_length=64, description="邮箱")
    password: str = Field(..., min_length=1, max_length=128, description="密码（≥8位，含字母和数字）")


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=64, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ---- 登录暴力破解防护（进程内滑动失败计数：5 次失败锁定 15 分钟）----
_LOGIN_ATTEMPTS: dict[tuple[str, str], list[float]] = {}  # (identifier, ip) -> [count, locked_until]
_LOGIN_LOCK = threading.Lock()
_MAX_LOGIN_FAILS = 5
_LOCK_SECONDS = 15 * 60


def _login_key(identifier: str, client_ip: str) -> tuple[str, str]:
    return identifier.strip().lower(), client_ip or "unknown"


def _check_login_throttle(identifier: str, client_ip: str) -> None:
    with _LOGIN_LOCK:
        key = _login_key(identifier, client_ip)
        rec = _LOGIN_ATTEMPTS.get(key)
        if rec and rec[1] > time.time():
            wait_min = int((rec[1] - time.time()) / 60) + 1
            raise HTTPException(status_code=429,
                                detail=f"登录失败次数过多，请 {wait_min} 分钟后重试")


def _record_login_failure(identifier: str, client_ip: str) -> None:
    with _LOGIN_LOCK:
        key = _login_key(identifier, client_ip)
        cnt, until = _LOGIN_ATTEMPTS.get(key, [0.0, 0.0])
        cnt += 1
        if cnt >= _MAX_LOGIN_FAILS:
            until = time.time() + _LOCK_SECONDS
        _LOGIN_ATTEMPTS[key] = [cnt, until]
        if len(_LOGIN_ATTEMPTS) > 10000:  # 防内存膨胀（窗口滑动即可，无需持久化）
            _LOGIN_ATTEMPTS.clear()


def _record_login_success(identifier: str, client_ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(_login_key(identifier, client_ip), None)


# ---- 注册频率限制（进程内滑动计数：同 IP 每小时最多 5 个新账号）----
_REGISTER_ATTEMPTS: dict[str, list[float]] = {}
_REGISTER_LOCK = threading.Lock()
_MAX_REGISTERS_PER_HOUR = 5
_REGISTER_WINDOW = 3600


def _check_register_throttle(client_ip: str) -> None:
    with _REGISTER_LOCK:
        now = time.time()
        stamps = _REGISTER_ATTEMPTS.setdefault(client_ip or "unknown", [])
        # 只保留窗口内的记录
        stamps[:] = [t for t in stamps if now - t < _REGISTER_WINDOW]
        if len(stamps) >= _MAX_REGISTERS_PER_HOUR:
            raise HTTPException(status_code=429,
                                detail="注册过于频繁，请 1 小时后再试")
        stamps.append(now)
        if len(_REGISTER_ATTEMPTS) > 10000:  # 防内存膨胀
            _REGISTER_ATTEMPTS.clear()


def reset_register_throttle() -> None:
    """清空注册限流计数（测试隔离用；生产不调用）。"""
    with _REGISTER_LOCK:
        _REGISTER_ATTEMPTS.clear()


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(req: RegisterRequest, settings: Settings = Depends(get_settings),
             store: UserStore = Depends(get_user_store),
             request: Request = None) -> AuthResponse:
    """注册：本地校验 → 入库 → 直接签发 token（注册即登录）。"""
    client_ip = request.client.host if request and request.client else ""
    _check_register_throttle(client_ip)
    user = store.create_user(req.username, req.email, req.password)
    token = create_token(user.username, settings.auth.secret,
                         ttl_hours=settings.auth.token_ttl_hours)
    return AuthResponse(access_token=token, user=user.to_dict())


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, settings: Settings = Depends(get_settings),
          store: UserStore = Depends(get_user_store),
          request: Request = None) -> AuthResponse:
    """登录：用户名或邮箱 + 密码 → JWT（带失败次数限流，防暴力破解）。"""
    client_ip = request.client.host if request and request.client else ""
    _check_login_throttle(req.identifier, client_ip)
    try:
        user = store.verify_login(req.identifier, req.password)
    except UnauthorizedError:
        _record_login_failure(req.identifier, client_ip)
        raise
    _record_login_success(req.identifier, client_ip)
    token = create_token(user.username, settings.auth.secret,
                         ttl_hours=settings.auth.token_ttl_hours)
    return AuthResponse(access_token=token, user=user.to_dict())


@router.get("/me", response_model=dict)
def me(user: User = Depends(get_current_user)) -> dict:
    """当前登录用户（前端刷新后恢复会话用）。"""
    return user.to_dict()
