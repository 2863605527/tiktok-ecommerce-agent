"""选品结果历史库：SQLite 单文件（标准库 sqlite3），按用户隔离。

企业级要点：
- 与用户表同库（data/app.db），WAL 模式，每次操作独立连接（线程安全）
- result_json 存完整流水线结果（products/report/offers/listing），可完整回放
- 列表按时间倒序、支持按用户/状态过滤；DELETE 只允许删除本人记录
- 生产可平移 PostgreSQL + SQLAlchemy：只替换本模块实现，接口不变
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tiktok_ecommerce.common.exceptions import NotFoundError, UnauthorizedError
from tiktok_ecommerce.common.logging import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_selections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    product       TEXT    NOT NULL,
    region        TEXT    NOT NULL DEFAULT 'JP',
    category      TEXT    NOT NULL DEFAULT 'bedding',
    language      TEXT    NOT NULL DEFAULT 'ja',
    status        TEXT    NOT NULL DEFAULT 'ok',          -- ok | error
    result_json   TEXT    NOT NULL DEFAULT '{}',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_saved_selections_user
    ON saved_selections (user_id, id DESC);
"""


@dataclass(frozen=True)
class SavedSelection:
    """历史选品记录（对外视图）。"""

    id: int
    user_id: int
    product: str
    region: str
    category: str
    language: str
    status: str
    result: dict
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product": self.product,
            "region": self.region,
            "category": self.category,
            "language": self.language,
            "status": self.status,
            "created_at": self.created_at,
            "result": self.result,
        }


class SelectionStore:
    """选品结果表读写。"""

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
            # executescript：一次执行多段 DDL（CREATE TABLE + CREATE INDEX）
            conn.executescript(_SCHEMA)

    def save(self, user_id: int, product: str, region: str, category: str,
             language: str, result: dict, status: str = "ok") -> SavedSelection:
        """保存一次选品结果（含错误结果，便于前端复盘失败原因）。"""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO saved_selections
                   (user_id, product, region, category, language, status, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, product, region, category, language,
                 status, json.dumps(result, ensure_ascii=False)),
            )
            rid = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM saved_selections WHERE id = ?", (rid,)
            ).fetchone()
        logger.info("选品结果已保存: id=%s user=%s product=%s status=%s",
                    rid, user_id, product[:30], status)
        return self._row_to_model(row)

    def list_for_user(self, user_id: int, limit: int = 50) -> list[SavedSelection]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM saved_selections
                   WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get(self, record_id: int, user_id: int) -> SavedSelection:
        """按 ID 取记录；不存在或非本人 → 结构化错误（不泄露他人数据）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM saved_selections WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("该选品记录不存在")
        if int(row["user_id"]) != user_id:
            raise UnauthorizedError("无权访问该记录")
        return self._row_to_model(row)

    def delete(self, record_id: int, user_id: int) -> None:
        """删除记录（仅本人）。"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM saved_selections WHERE id = ? AND user_id = ?",
                (record_id, user_id),
            )
        if cur.rowcount == 0:
            # 区分不存在与无权：先查存在性
            with self._connect() as conn2:
                row = conn2.execute(
                    "SELECT user_id FROM saved_selections WHERE id = ?",
                    (record_id,),
                ).fetchone()
            if row is None:
                raise NotFoundError("该选品记录不存在")
            raise UnauthorizedError("无权删除该记录")
        logger.info("选品记录已删除: id=%s user=%s", record_id, user_id)

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> SavedSelection:
        return SavedSelection(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            product=str(row["product"]),
            region=str(row["region"]),
            category=str(row["category"]),
            language=str(row["language"]),
            status=str(row["status"]),
            result=json.loads(str(row["result_json"]) or "{}"),
            created_at=str(row["created_at"]),
        )
