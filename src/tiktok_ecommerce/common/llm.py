"""LLM 访问层：统一创建模型与向量化函数。

企业级要点：
- 工厂函数 + 配置注入，便于测试时替换 Mock
- 兼容任何 OpenAI 协议服务（OpenAI/DeepSeek/豆包/通义/硅基流动）
- 启动前校验 API Key：HTTP 认证头只接受 ASCII，中文占位符会导致编码崩溃，提前拦截
"""
from collections.abc import Callable

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from tiktok_ecommerce.config import Settings
from tiktok_ecommerce.common.exceptions import ConfigError

# 模板占位符特征（.env 没改时能识别出来）
_PLACEHOLDER_MARKERS = ("your-api-key", "sk-your", "在这里", "xxxx", "changeme", "填入")


def _validate_api_key(key: str, which: str) -> None:
    """校验 API Key：非空、非占位符、纯 ASCII。"""
    if not key:
        raise ConfigError(f"未配置 {which} API Key，请复制 .env.example 为 .env 并填写")
    low = key.lower()
    if any(marker in low or marker in key for marker in _PLACEHOLDER_MARKERS):
        raise ConfigError(
            f"{which} API Key 仍是模板占位符（{key[:8]}...），请在 .env 填入真实 Key"
        )
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        raise ConfigError(
            f"{which} API Key 含中文或非英文字符；HTTP 认证头只接受英文 Key，"
            "请检查 .env 是否把说明文字填进了 Key"
        )


def create_llm(settings: Settings) -> ChatOpenAI:
    """创建对话 LLM 实例。"""
    _validate_api_key(settings.llm.api_key, "对话模型 LLM")
    return ChatOpenAI(
        model=settings.llm.model,
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )


def create_embedding_fn(settings: Settings) -> Callable[[str], list[float]]:
    """创建向量化函数: text -> list[float]。

    向量模型可与对话模型不同服务商（见 LLMSettings.emb_* 回退逻辑）。
    """
    _validate_api_key(settings.llm.emb_api_key, "向量模型 EMBEDDING")
    emb = OpenAIEmbeddings(
        model=settings.llm.embedding_model,
        api_key=settings.llm.emb_api_key,
        base_url=settings.llm.emb_base_url,
    )
    return emb.embed_query
