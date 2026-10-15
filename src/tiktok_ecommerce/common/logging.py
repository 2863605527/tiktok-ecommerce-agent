"""结构化日志：JSON 输出（便于采集到日志平台）。

企业级要点：
- JSON 日志格式，机器可解析，可被 ELK/Loki 等采集
- 支持 context（request_id 等），贯穿一次请求的所有日志
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """把日志记录转成单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 附加上下文（如 request_id）
        if hasattr(record, "context") and record.context:
            payload["context"] = record.context
        # 异常堆栈
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_format: bool = True) -> None:
    """初始化全局日志。重复调用安全。"""
    root = logging.getLogger()
    if root.handlers:  # 已初始化
        root.setLevel(level)
        return

    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """获取带命名空间的 logger（推荐统一从这里取）。"""
    return logging.getLogger(name)
