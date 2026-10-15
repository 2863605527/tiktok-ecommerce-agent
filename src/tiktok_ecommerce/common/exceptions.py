"""统一异常体系。

企业级要点：
- 所有业务异常继承 AppError，上层（API/CLI）只需捕获 AppError 即可统一处理
- 错误码稳定，便于日志告警和前端提示
- 异常信息记录到日志，不把内部堆栈直接暴露给用户
"""
from enum import Enum


class ErrorCode(str, Enum):
    """稳定错误码。"""

    CONFIG_ERROR = "CONFIG_ERROR"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    CRAWLER_ERROR = "CRAWLER_ERROR"
    RAG_ERROR = "RAG_ERROR"
    AGENT_ERROR = "AGENT_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class AppError(Exception):
    """应用异常基类。"""

    code: ErrorCode = ErrorCode.UNKNOWN
    http_status: int = 500

    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "error": {"code": self.code.value, "message": self.message, "detail": self.detail},
        }


class ConfigError(AppError):
    """配置错误（缺 Key、非法值等）。"""

    code = ErrorCode.CONFIG_ERROR
    http_status = 500


class ExternalAPIError(AppError):
    """外部 API 调用失败（LLM、向量库等）。"""

    code = ErrorCode.EXTERNAL_API_ERROR
    http_status = 502


class CrawlerError(AppError):
    """爬虫采集失败。"""

    code = ErrorCode.CRAWLER_ERROR
    http_status = 502


class RAGError(AppError):
    """RAG 检索/入库失败。"""

    code = ErrorCode.RAG_ERROR
    http_status = 500


class AgentError(AppError):
    """Agent 执行失败。"""

    code = ErrorCode.AGENT_ERROR
    http_status = 500


class ValidationError(AppError):
    """输入校验失败。"""

    code = ErrorCode.VALIDATION_ERROR
    http_status = 400


class NotFoundError(AppError):
    """资源不存在。"""

    code = ErrorCode.NOT_FOUND
    http_status = 404


class UnauthorizedError(AppError):
    """未登录 / token 无效 / 凭据错误（401）。"""

    code = ErrorCode.UNAUTHORIZED
    http_status = 401


class ConflictError(AppError):
    """资源冲突（用户名/邮箱已被占用，409）。"""

    code = ErrorCode.CONFLICT
    http_status = 409
