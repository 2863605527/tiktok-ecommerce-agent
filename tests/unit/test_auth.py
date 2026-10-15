"""认证安全原语测试：密码哈希 / JWT / 输入校验 / 用户存储 / 鉴权依赖。"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tiktok_ecommerce.api.app import create_app
from tiktok_ecommerce.common.exceptions import AppError
from tiktok_ecommerce.common.security import (
    create_token,
    decode_token,
    hash_password,
    validate_email,
    validate_password,
    validate_username,
    verify_password,
)

_SECRET = "test-secret-0123456789abcdef"


def test_password_hash_roundtrip():
    h = hash_password("Abc12345")
    assert h.startswith("scrypt$")
    assert "Abc12345" not in h  # 不落明文
    assert verify_password("Abc12345", h)
    assert not verify_password("Abc1234X", h)
    assert not verify_password("Abc12345", "junk")


def test_password_hash_is_salted():
    assert hash_password("Abc12345") != hash_password("Abc12345")


def test_jwt_roundtrip():
    token = create_token("tester", _SECRET, ttl_hours=1)
    payload = decode_token(token, _SECRET)
    assert payload.sub == "tester"
    assert payload.exp > payload.iat


def test_jwt_rejects_tampered():
    token = create_token("tester", _SECRET)
    tampered = token[:-4] + ("abcd" if token[-4:] != "abcd" else "wxyz")
    with pytest.raises(ValueError):
        decode_token(tampered, _SECRET)


def test_jwt_rejects_wrong_secret():
    token = create_token("tester", _SECRET)
    with pytest.raises(ValueError):
        decode_token(token, "another-secret")


def test_jwt_rejects_expired():
    token = create_token("tester", _SECRET, ttl_hours=0)  # exp == iat（立即过期）
    time.sleep(1.1)
    with pytest.raises(ValueError, match="过期"):
        decode_token(token, _SECRET)


@pytest.mark.parametrize("username,ok", [
    ("tester", True), ("t_e_s_ter_1", True), ("ab", False), ("", False),
    ("中文用户名", False), ("a" * 21, False), ("has space", False),
    ("t-e-s", False),  # 连字符不允许
])
def test_validate_username(username: str, ok: bool):
    assert (validate_username(username) is None) == ok


@pytest.mark.parametrize("email,ok", [
    ("a@b.com", True), ("user.name+tag@sub.example.co.jp", True),
    ("plain", False), ("a@b", False), ("", False), ("a b@c.com", False),
])
def test_validate_email(email: str, ok: bool):
    assert (validate_email(email) is None) == ok


@pytest.mark.parametrize("password,ok", [
    ("Abc12345", True), ("abc12345", True), ("ABCDEFGH", False),
    ("abcdefgh", False), ("Abc12", False), ("", False),
])
def test_validate_password(password: str, ok: bool):
    assert (validate_password(password) is None) == ok


# ---------- 用户存储 ----------

def _make_store(tmp_path):
    from tiktok_ecommerce.auth.store import UserStore
    return UserStore(tmp_path / "test_app.db")


def test_create_user_duplicate_username(tmp_path):
    store = _make_store(tmp_path)
    store.create_user("alice", "a@x.com", "Alice123")
    with pytest.raises(AppError) as ei:
        store.create_user("alice", "b@x.com", "Bob123456")
    assert ei.value.http_status == 409
    assert "用户名" in ei.value.message


def test_create_user_duplicate_email_case_insensitive(tmp_path):
    store = _make_store(tmp_path)
    store.create_user("alice", "A@X.com", "Alice123")
    with pytest.raises(AppError) as ei:
        store.create_user("bob", "a@x.com", "Bob123456")
    assert ei.value.http_status == 409
    assert "邮箱" in ei.value.message


def test_verify_login_by_username_and_email(tmp_path):
    store = _make_store(tmp_path)
    store.create_user("alice", "alice@x.com", "Alice123")
    assert store.verify_login("alice", "Alice123").username == "alice"
    assert store.verify_login("ALICE@X.COM", "Alice123").username == "alice"
    with pytest.raises(AppError) as ei:
        store.verify_login("alice", "Wrong123")
    assert ei.value.http_status == 401
    with pytest.raises(AppError):
        store.verify_login("nobody", "Alice123")


# ---------- 认证 API ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "api_app.db"))
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    from tiktok_ecommerce.config import get_settings
    get_settings.cache_clear()
    from tiktok_ecommerce.api.v1.auth import get_user_store
    get_user_store.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()
    get_user_store.cache_clear()


def test_register_and_me(client):
    r = client.post("/api/v1/auth/register", json={
        "username": "seller01", "email": "seller01@x.com", "password": "Passw0rd"})
    assert r.status_code == 201
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["user"]["username"] == "seller01"
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "seller01@x.com"


def test_register_validation_errors(client):
    r = client.post("/api/v1/auth/register", json={
        "username": "x", "email": "bad", "password": "weak"})
    assert r.status_code == 400
    assert "用户名" in r.json()["error"]["message"]


def test_login_success_and_failure(client):
    client.post("/api/v1/auth/register", json={
        "username": "seller02", "email": "s2@x.com", "password": "Passw0rd"})
    ok = client.post("/api/v1/auth/login", json={
        "identifier": "seller02", "password": "Passw0rd"})
    assert ok.status_code == 200
    bad = client.post("/api/v1/auth/login", json={
        "identifier": "seller02", "password": "Wrong123"})
    assert bad.status_code == 401


def test_business_api_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.post("/api/v1/chat", json={"message": "你好"})
    assert r.status_code == 401


def test_chat_works_with_token(client):
    client.post("/api/v1/auth/register", json={
        "username": "seller03", "email": "s3@x.com", "password": "Passw0rd"})
    login = client.post("/api/v1/auth/login", json={
        "identifier": "seller03", "password": "Passw0rd"}).json()
    token = login["access_token"]
    r = client.post("/api/v1/chat", json={"message": "你是干啥的"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["intent"] == "self_intro"
