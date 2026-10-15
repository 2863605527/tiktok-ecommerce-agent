"""用户认证安全原语：scrypt 密码哈希 + 标准库 HS256 JWT。

企业级要点（零第三方依赖，全部标准库）：
- 密码：scrypt 加盐 KDF（16 字节随机盐 + 64 字节派生密钥），存储格式
  `scrypt$n$r$p$salt_b64$hash_b64`，参数化可平滑升级
- Token：RFC 7519 JWT（HS256，HMAC-SHA256 签名），带 iat/exp，
  篡改或过期即刻校验失败；payload 仅含 sub/iat/exp，不放敏感信息

生产建议：AUTH_SECRET 用 `openssl rand -hex 32` 生成并妥善保管；
多实例部署时所有实例共享同一 secret，否则 token 互相不认。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

# scrypt 参数（Python 标准库 hashlib.scrypt；n 必须是 2 的幂）
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_DK_BYTES = 64

_JWT_ALG = "HS256"
_JWT_TYP = "JWT"

# ---- 输入校验（注册表单"不能胡乱输入"）----

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_username(username: str) -> str | None:
    """校验用户名：3-20 位字母/数字/下划线。返回错误信息，合法返回 None。"""
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        return "用户名需为 3-20 位字母、数字或下划线"
    return None


def validate_email(email: str) -> str | None:
    """校验邮箱格式。"""
    email = (email or "").strip()
    if len(email) > 64 or not _EMAIL_RE.match(email):
        return "邮箱格式不正确"
    return None


def validate_password(password: str) -> str | None:
    """校验密码强度：≥8 位，至少含一个字母和一个数字。"""
    password = password or ""
    if len(password) < 8:
        return "密码至少 8 位"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        return "密码需同时包含字母和数字"
    return None


# ---- 密码哈希（scrypt）----


def hash_password(password: str) -> str:
    """scrypt 加盐哈希密码，返回自描述存储串（不落明文）。"""
    salt = hashlib.sha256(
        f"{time.time_ns()}-{id(password)}".encode()
    ).digest()[: _SALT_BYTES]
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DK_BYTES,
    )
    return (f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}")


def verify_password(password: str, stored: str) -> bool:
    """校验密码与存储串是否匹配（解析参数，兼容未来参数升级）。"""
    try:
        _alg, n, r, p, salt_b64, dk_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expect = base64.b64decode(dk_b64)
    except (ValueError, TypeError):
        return False
    try:
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expect),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expect)


# ---- JWT（HS256，RFC 7519）----


@dataclass(frozen=True)
class TokenPayload:
    """JWT 载荷（仅业务需要的最小字段）。"""

    sub: str
    iat: int
    exp: int


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_token(subject: str, secret: str, ttl_hours: int = 12) -> str:
    """签发 HS256 JWT access token（sub=用户名，带签发/过期时间）。"""
    now = int(time.time())
    header = _b64url(json.dumps({"alg": _JWT_ALG, "typ": _JWT_TYP},
                                separators=(",", ":")).encode())
    payload = _b64url(json.dumps(
        {"sub": subject, "iat": now, "exp": now + ttl_hours * 3600},
        separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}"
    sig = _b64url(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{sig}"


def decode_token(token: str, secret: str) -> TokenPayload:
    """校验 JWT：签名 + 过期。任何失败抛 ValueError（调用方转 401）。"""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError as e:
        raise ValueError("token 格式错误") from e
    signing_input = f"{header_b64}.{payload_b64}"
    expect = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig_b64)
    except (ValueError, TypeError) as e:
        raise ValueError("token 签名格式错误") from e
    if not hmac.compare_digest(got, expect):
        raise ValueError("token 签名无效（可能被篡改）")
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        raise ValueError("token 载荷损坏") from e
    sub = str(payload.get("sub") or "")
    iat = int(payload.get("iat") or 0)
    exp = int(payload.get("exp") or 0)
    if not sub:
        raise ValueError("token 缺少主体")
    if exp <= int(time.time()):
        raise ValueError("token 已过期，请重新登录")
    return TokenPayload(sub=sub, iat=iat, exp=exp)
