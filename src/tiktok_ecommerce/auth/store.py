"""用户账户存储：SQLite 单文件（标准库 sqlite3）。

企业级要点：
- 密码只存 scrypt 哈希串，绝不落明文
- username / email 唯一约束（大小写不敏感存小写）
- 所有写操作显式提交 + 异常回滚；重复账号/邮箱返回结构化错误
- 生产可平移 PostgreSQL + SQLAlchemy：只替换本模块实现，接口不变
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tiktok_ecommerce.common.exceptions import ConflictError, UnauthorizedError, ValidationError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.common.security import (
    hash_password,
    validate_email,
    validate_password,
    validate_username,
    verify_password,
)

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


@dataclass(frozen=True)
class User:
    """已认证用户（对外安全视图：不含密码哈希）。"""

    id: int
    username: str
    email: str
    created_at: str

    def to_dict(self) -> dict:
        return {"id": self.id, "username": self.username,
                "email": self.email, "created_at": self.created_at}


class UserStore:
    """用户表读写（线程安全：每次操作独立连接）。"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)
        logger.info("用户库就绪: %s", self.db_path)

    # ---- 注册 ----

    def create_user(self, username: str, email: str, password: str) -> User:
        """创建用户：先本地校验（格式/强度），再查重，最后入库。"""
        username = username.strip()
        email = email.strip().lower()
        if err := validate_username(username):
            raise ValidationError(err)
        if err := validate_email(email):
            raise ValidationError(err)
        if err := validate_password(password):
            raise ValidationError(err)

        pw_hash = hash_password(password)
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, pw_hash),
                )
                user_id = cur.lastrowid
                created = conn.execute(
                    "SELECT created_at FROM users WHERE id = ?", (user_id,)
                ).fetchone()["created_at"]
        except sqlite3.IntegrityError as e:
            # UNIQUE 约束冲突 → 区分用户名/邮箱
            msg = str(e).lower()
            if "users.username" in msg:
                raise ConflictError("该用户名已被注册") from e
            if "users.email" in msg:
                raise ConflictError("该邮箱已被注册") from e
            raise ConflictError("注册失败，请稍后重试") from e
        logger.info("新用户注册: %s <%s>", username, email)
        return User(id=user_id, username=username, email=email, created_at=created)

    # ---- 登录 ----

    def verify_login(self, identifier: str, password: str) -> User:
        """登录校验：identifier 支持用户名或邮箱；密码错误统一 401（不泄露存在性）。"""
        identifier = identifier.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?",
                (identifier, identifier),
            ).fetchone()
        if row is None or not verify_password(password, str(row["password_hash"])):
            raise UnauthorizedError("用户名或密码错误")
        return User(id=int(row["id"]), username=str(row["username"]),
                    email=str(row["email"]), created_at=str(row["created_at"]))

    # ---- 查询 ----

    def get_by_username(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, email, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return User(id=int(row["id"]), username=str(row["username"]),
                    email=str(row["email"]), created_at=str(row["created_at"]))
