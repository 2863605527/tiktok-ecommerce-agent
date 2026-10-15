"""应用配置：基于 pydantic-settings 的类型安全配置管理。

企业级要点：
- 配置来源优先级：环境变量 > .env 文件 > 代码默认值
- 所有配置有类型约束，启动时即校验，杜绝"字符串拼错"
- 单例模式：全应用共享一份配置，避免各处重复读取
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（config.py 所在包的上级上级）
ROOT_DIR = Path(__file__).resolve().parents[2]


class LLMSettings(BaseSettings):
    """大模型配置。

    对话模型与向量化模型可来自不同服务商（国内常见组合）：
    - 对话：DeepSeek（deepseek-chat）
    - 向量：硅基流动（BAAI/bge-m3，1024 维，有免费额度）
    embedding_* 留空时自动回退到对话模型的配置（即同一家服务商）。
    """

    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", extra="ignore")

    # ---- 对话模型 ----
    api_key: str = Field(..., description="对话模型 API Key（必填）")
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = 0.3
    max_tokens: int = 2000

    # ---- 向量化模型（可单独配置服务商；留空回退对话模型）----
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None

    @property
    def emb_api_key(self) -> str:
        """向量模型 API Key（未单独配置则回退对话模型 Key）。"""
        return self.embedding_api_key or self.api_key

    @property
    def emb_base_url(self) -> str:
        """向量模型服务地址（未单独配置则回退对话模型地址）。"""
        return self.embedding_base_url or self.base_url


class MilvusSettings(BaseSettings):
    """向量库配置。"""

    model_config = SettingsConfigDict(env_prefix="MILVUS_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 19530
    collection: str = "tiktok_product"
    embedding_dim: int = 1024  # BAAI/bge-m3=1024；若用 OpenAI text-embedding-3-small 改为 1536
    top_k: int = 5
    score_threshold: float = 0.0


class RAGSettings(BaseSettings):
    """检索层配置：自建 Milvus / 托管 RAGFlow / 内存库 三选一。"""

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    # 检索后端：milvus（自建，默认）| ragflow（托管）| memory（内存，无Docker/测试用）
    backend: str = "milvus"
    # RAGFlow 连接（backend=ragflow 时使用）
    base_url: str = "http://localhost"
    api_key: str = ""
    dataset: str = "tiktok_bedding_kb"
    similarity_threshold: float = 0.2
    vector_weight: float = 0.3  # RAGFlow 混合检索中的向量权重（其余为关键词权重）


class CrawlerSettings(BaseSettings):
    """采集配置。"""

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    tiktok_base_url: str = "https://www.tiktok.com"
    supplier_base_url: str = "https://www.1688.com"
    # 找家纺网（默认货源平台；原 91家纺网已替换）
    jiafang_base_url: str = "https://www.zhaojiafang.com"
    # 找家纺搜索 API（前后端分离，数据 JSON 返回）
    jiafang_api_base_url: str = "https://api-pl-mobile.zhaojiafang.com"
    # 找家纺商品详情站
    jiafang_detail_base_url: str = "https://detail.zhaojiafang.com"
    # 找家纺"以图搜款"接口鉴权 token（F12 抓取，站内公开；过期时重新抓取替换）
    # 安全：不内置在源码（会随仓库公开），必须放 .env：ZHAOJIAFANG_IMAGE_SEARCH_TOKEN=...
    # 参考: /api/search/search_by_image?SystemName=pc&storeid=1&token=<token>
    jiafang_image_search_token: str = ""
    # FastMoss 查询区域（TikTok Shop 区域代码，JP=日本站）
    fastmoss_region: str = "JP"
    request_interval: float = 3.0
    timeout: int = 10
    max_retries: int = 3
    max_comments: int = 200
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    # 数据源开关：sample=本地样本(默认,离线可跑) / api=第三方数据平台(生产) / direct=直连RPA(默认不可用)
    product_source: str = "sample"
    # 货源：sample=家纺货源样本(默认,91家纺风格) / jiafang=家纺垂直站直连 / 1688=综合批发平台直连(可选) / api=开放平台
    supplier_source: str = "sample"
    sample_dir: Path = ROOT_DIR / "data" / "samples"
    # 第三方数据平台 API（FastMoss/Kalodata/EchoTik 等，生产方案，在 .env 配置）
    third_party_product_api_base: str = ""
    third_party_product_api_key: str = ""
    third_party_supplier_api_base: str = ""
    third_party_supplier_api_key: str = ""
    # SocialCrawl（免费 100 credits 验证用）：x-api-key 鉴权，1 credit/次
    socialcrawl_base_url: str = "https://www.socialcrawl.dev"
    socialcrawl_api_key: str = ""
    # TikHub（日常批量付费源，$0.001/次起）：Bearer 鉴权
    tikhub_base_url: str = "https://api.tikhub.io"
    tikhub_api_key: str = ""
    # 代理（日本站建议日本住宅代理，形如 http://user:pass@host:port；留空不用）
    proxy_url: str = ""


class PipelineSettings(BaseSettings):
    """流水线配置。"""

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    default_category: str = "bedding"   # 默认品类：床上用品
    chunk_size: int = 300
    chunk_overlap: int = 30
    sourcing_top_n: int = 10
    match_threshold: float = 0.6
    image_width: int = 800
    image_height: int = 800
    image_quality: int = 85
    enable_manual_review: bool = True


class AuthSettings(BaseSettings):
    """用户认证配置（登录注册 + JWT 鉴权）。

    企业级要点：
    - JWT 用 HMAC-SHA256 签名，secret 必须保密（生产用随机强口令）
    - 密码用 scrypt 加盐哈希存储（标准库，无需 bcrypt 依赖）
    - SQLite 单文件存储（本地单机够用；生产可换 PostgreSQL + SQLAlchemy）
    """

    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    # JWT 签名密钥：生产必须改为随机强口令（openssl rand -hex 32）
    secret: str = "dev-secret-change-me-in-production"
    # access_token 有效期（小时）
    token_ttl_hours: int = 12
    # 用户库 SQLite 路径（相对项目根）
    db_path: str = "data/app.db"
    # 利润测算默认汇率（1 CNY ≈ ? JPY，估算值，可按实际行情改 .env）
    fx_cny_jpy: float = 21.0


class Settings(BaseSettings):
    """应用总配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "tiktok-ecommerce-agent"
    version: str = "0.1.0"
    log_level: str = "INFO"
    data_dir: Path = ROOT_DIR / "data"
    output_dir: Path = ROOT_DIR / "output"
    log_dir: Path = ROOT_DIR / "logs"

    llm: LLMSettings = Field(default_factory=LLMSettings)
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"非法日志级别: {v}")
        return v

    def ensure_dirs(self) -> None:
        """确保数据/输出/日志目录存在。"""
        for d in (self.data_dir, self.output_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)
        for sub in ("raw", "processed", "vectors"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        for sub in ("reports", "listings"):
            (self.output_dir / sub).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()
