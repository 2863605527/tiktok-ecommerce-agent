"""聊天服务：把用户消息路由到电商工具能力，范围外话题礼貌拒答。

设计原则（工程决策）：
- **意图分类用规则引擎**（关键词+正则，中文/日文双语），不用 LLM：
  可控、可单测、零成本 —— 分类不准会浪费一次 LLM 调用且行为不可复现
- **内容生成才用 LLM**（已有 analyzer/listing Agent），不重复造轮子
- **范围外话题**（非电商）→ 固定礼貌话术，不做无意义检索
- **电商常识但超出工具能力**（物流/关税/平台政策）→ 引导到官方渠道，
  绝不编造政策数字（延续全项目的防幻觉原则）

四类意图（业务能力边界）：
1. select_product —— 选品分析：跑完整流水线（采集→RAG分析→货源→上架素材）
2. sourcing_only —— 找货源：找家纺网真实 API 搜索（含关键词降级容错）
3. listing_only  —— 上架素材：生成日语标题/关键词/描述/规格翻译
4. qa_ecommerce  —— 电商常识：固定引导（不在工具能力内，不编造）
5. out_of_scope  —— 非电商话题：礼貌拒答
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.config import Settings
from tiktok_ecommerce.models.product import Product

logger = get_logger(__name__)

# ---------------- 会话上下文 ----------------
# 让聊天"能继续聊下去"：记住最近一次选品/货源/素材结果，
# 用户说"第一条货源生成素材"时直接用上下文，而不是重新搜索。


@dataclass
class ConversationContext:
    """一次会话的最近业务结果（供后续消息引用，如"第一条货源"）。"""

    products: list[dict] = field(default_factory=list)   # TikTok 竞品（含 images）
    offers: list[dict] = field(default_factory=list)     # 货源（含 url/images）
    report: dict | None = None                            # 选品评估
    listing: dict | None = None                           # 上架素材
    listing_path: str = ""
    last_query: str = ""
    last_intent: str = ""
    supplier_source: str = ""   # 会话级货源平台（"1688"/"jiafang"...；空=默认找家纺网）

    def has_content(self) -> bool:
        return bool(self.offers or self.products or self.listing)

    def to_payload(self) -> dict[str, Any]:
        return {
            "products": self.products[:5],
            "report": self.report,
            "offers": self.offers[:6],
            "listing_path": self.listing_path,
        }


# 上下文引用：只有强指代（这个/刚才/第N条）才算引用上下文；
# "找 XX 货源"是正常搜索指令，不触发上下文分支
CONTEXT_PRONOMINAL_TOKENS = [
    "这个", "这条", "刚才", "上面", "第一个", "第二个", "第三个",
    "第一条", "第二条", "第三条", "第一个货源", "第一条货源",
    "这个货源", "这个商品", "这个链接",
]
_CONTEXT_ORDER_RE = re.compile(r"第([一二三四五六七八九十0-9]+)(?:条|个|款)")

# ---------------- 意图触发词（中文 + 日文） ----------------
SELECT_TOKENS = [
    "分析", "能不能卖", "能卖吗", "适合卖", "适不适合卖", "值得卖", "选品",
    "怎么样", "好卖吗", "可以做吗", "好卖", "卖得动", "评测", "调研", "能不能做",
    "分析して", "売れる", "選品", "どう", "リサーチ", "トレンド",
]
SOURCE_TOKENS = [
    "货源", "找货", "代发", "供应商", "进货", "采购", "拿货", "找",
    "仕入れ", "卸先", "代行", "サプライヤー",
]
LISTING_TOKENS = [
    "上架", "标题", "文案", "翻译", "素材", "listing", "出品", "生成",
    "タイトル", "コピー", "翻訳", "出品文", "商品説明",
]
PROFIT_TOKENS = [
    "利润", "能赚", "赚多少", "毛利", "净利", "利润率", "成本", "划算吗",
    "利润测算", "算下利润", "赚不赚", "回本",
    "利益", "もうけ", "コスト", "儲かる",
]
QA_TOKENS = [
    "运费", "物流", "关税", "政策", "平台", "日本站", "回款", "入驻",
    "开店", "配送", "国际", "税费", "怎么发货", "发货",
    "送料", "関税", "政策", "出店", "決済",
]
# 带货视频脚本（对标 tiktok-viral-factory：自动生成日文带货口播脚本）
SCRIPT_TOKENS = [
    "带货脚本", "视频脚本", "口播", "脚本", "台本", "短视频文案",
    "ショート動画", "台本", "ナレーション", "口上", "原稿", "シナリオ",
]
# 货源平台切换：聊天说"去1688找货源 / 换回找家纺网 / 去其他地方找货源"
# → switch_supplier 意图，动态切换货源源并（带商品词时）立即搜索
SUPPLIER_SWITCH_TOKENS = [
    "1688", "找家纺", "家纺网", "别的平台", "别的货源", "其他平台",
    "其他货源", "其他地方", "换个货源", "换货源", "换到", "换回", "改成",
    "切换", "切到", "alibaba",
]
# 切换动作词（纯切换句里剥掉，避免"去1688找货源"的"去"被误当商品词）
_SWITCH_ACTION_WORDS = [
    "去", "用", "换回", "换到", "换成", "切换", "切到", "以后", "默认",
    "都", "的话", "把", "帮我", "请", "我", "到",
]
# 平台解析（长词优先）：1688/找家纺/家纺网 分别映射到数据源名
_SUPPLIER_SOURCE_WORDS: list[tuple[str, str]] = [
    ("找家纺", "jiafang"), ("家纺网", "jiafang"), ("1688", "1688"),
    ("alibaba", "1688"),
]
# 只说"其他/别的平台"没点名时给的可选提示
_SUPPLIER_CHOICES_HINT = "目前可选：找家纺网（默认，家纺垂直站）、1688（综合批发）。"
# 自我介绍/问候（问助手本身 → 老实介绍自己，引导回电商；不属于范围外）
SELF_INTRO_TOKENS = [
    "你是谁", "你是干啥的", "你是干什么的", "你是干嘛的", "你是什么",
    "你谁啊", "你叫什么", "介绍一下你自己", "介绍下自己", "介绍一下",
    "你的功能", "你能干什么", "你能做什么", "你会什么", "你会做什么",
    "你会干嘛", "你能干嘛", "你是做啥的", "你是做什么的", "你是干嘛的",
    "你是啥", "你是做什么", "你主要做什么", "你能帮我做什么", "你可以做什么",
    "你好", "在吗", "hi", "hello", "こんにちは", "お前は誰",
]
# 纯闲聊/范围外高频词（提前命中，避免误判为选品）
SCOPE_OUT_TOKENS = [
    "天气", "吃饭", "睡觉", "游戏", "八卦", "新闻", "股票",
    "恋爱", "心情", "音乐", "电影", "给我写", "写个代码",
]
# 引导补充商品词的停用词（从消息里剥掉意图词/语气词后剩余即商品词）
STOP_WORDS = [
    "帮我", "请", "请问", "我想", "我要", "一下", "可以", "吗", "呢",
    "啊", "呀", "吧", "的", "了", "这个", "那个", "给我", "看看", "一下下",
    "お願い", "を", "は", "です", "ます", "して", "の",
]

OUT_OF_SCOPE_REPLY = (
    "不好意思，我是TikTok电商选品助手，只回答商品选品、竞品分析、"
    "找货源、上架素材这些电商相关的问题。你说的内容不在我的回答范围内，"
    "换个电商问题试试吧～比如：帮我分析 ボックスシーツ 能不能卖。"
)
QA_REPLY_TEMPLATE = (
    "这个问题属于电商常识/平台政策范围，我的核心能力是商品选品、货源匹配和上架素材生成。"
    "关于「{topic}」的具体规则（费率、时效、政策原文），建议直接查 TikTok Shop 官方卖家中心"
    "或日本站平台公告，避免信息过时。你可以试试问我：帮我分析「商品名」能不能卖 / "
    "找「商品名」的货源 / 生成「商品名」的上架素材。"
)
NEED_PRODUCT_REPLY = (
    "你想分析哪个商品呢？告诉我商品名就行，比如：\n"
    "· 帮我分析 ボックスシーツ 冬用 能不能卖\n"
    "· 找 牛奶绒床笠 四件套 的货源\n"
    "· 生成 法兰绒床笠 的上架素材"
)
SELF_INTRO_REPLY = (
    "你好，我是 TikTok 电商选品助手（日本站主推）🔍\n"
    "我的核心能力是帮你把「卖什么」这件事做扎实：\n"
    "· 选品分析：采集 TikTok 真实竞品 + 评论 RAG 分析 + 货源匹配 + 日文上架素材（全流程自动跑）\n"
    "· 找国内货源：找家纺网真实货源，一件代发，还支持用商品图找同款\n"
    "· 生成上架素材：日文标题 / 关键词 / 描述 / 规格翻译，一键导出\n"
    "我只服务电商相关的问题（商品选品、竞品分析、货源、上架），其他话题不在我的能力范围。\n"
    "你可以直接说：帮我分析 ボックスシーツ 冬用 能不能卖。"
)

_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("select_product", SELECT_TOKENS),
    ("profit", PROFIT_TOKENS),
    ("sourcing_only", SOURCE_TOKENS),
    ("script_only", SCRIPT_TOKENS),  # 带货脚本优先于上架素材（"短视频文案"易歧义）
    ("listing_only", LISTING_TOKENS),
    ("qa_ecommerce", QA_TOKENS),
]


_PUNCT = " ，。？！!?、\n\t：:；;＂“”‘’（）()"


def parse_supplier_source(message: str) -> str | None:
    """从消息里解析目标货源源：找家纺/家纺网→jiafang，1688/alibaba→1688。

    只认明确平台名；"别的/其他平台"没点名 → None（由调用方给出可选提示）。
    """
    text = message.strip().lower()
    for word, src in _SUPPLIER_SOURCE_WORDS:
        if word in text:
            return src
    return None


def classify_intent(message: str) -> str:
    """规则意图分类：自我介绍 → 范围外 → 电商意图（优先级 select > sourcing > listing > qa）。"""
    text = message.strip().lower()
    if not text:
        return "out_of_scope"
    # 自我介绍/问候（问助手本身）优先于范围外：老实介绍自己
    if any(t in message for t in SELF_INTRO_TOKENS):
        return "self_intro"
    # 纯闲聊高频词提前拦截
    if any(t in message for t in SCOPE_OUT_TOKENS):
        return "out_of_scope"
    # 货源平台切换（"去1688找货源/换回找家纺网"）→ 专属意图，优先于 select/sourcing
    if any(t in message for t in SUPPLIER_SWITCH_TOKENS) and (
            "货源" in message or "找" in message or "搜" in message
            or "1688" in message or "家纺" in message):
        return "switch_supplier"
    for intent, tokens in _INTENT_KEYWORDS:
        if any(t in message for t in tokens):
            return intent
    return "out_of_scope"


def has_context_ref(message: str) -> bool:
    """消息是否引用了"刚才/第一条/这个货源"等上下文（仅强指代，避免误判搜索）。"""
    return has_strong_context_ref(message) or bool(_CONTEXT_ORDER_RE.search(message))


def has_strong_context_ref(message: str) -> bool:
    """强指代（这个/刚才/第N条）——明确指向上下文；无上下文时也应引导。"""
    return any(t in message for t in CONTEXT_PRONOMINAL_TOKENS)


def context_order_index(message: str) -> int | None:
    """解析"第N条" → 0 基索引（默认 None=第一条/整体）。"""
    m = _CONTEXT_ORDER_RE.search(message)
    if not m:
        return None
    raw = m.group(1)
    cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}
    if raw.isdigit():
        return int(raw) - 1
    if raw in cn:
        return cn[raw] - 1
    return None


def extract_product(message: str) -> str | None:
    """从消息中提取商品词：剥掉意图词/语气词后剩余内容。

    剥词按长度降序（长词优先），避免"适不适合卖"被"适合卖"先行截断；
    返回 None 表示没有商品词（需引导用户补充）。
    """
    text = message.strip()
    all_tokens = [t for _, tokens in _INTENT_KEYWORDS for t in tokens] + STOP_WORDS
    for t in sorted(all_tokens, key=len, reverse=True):
        text = text.replace(t, " ")
    # 剥掉首尾标点，取剩余
    parts = [p.strip(_PUNCT) for p in text.split() if p.strip(_PUNCT)]
    product = " ".join(parts).strip(_PUNCT)
    if not product:
        return None
    return product[:60]


# 共享会话上下文（模块级单例：本地 uvicorn 单进程可跨请求共享；
# 生产多进程/多实例部署时应换 Redis 等外部存储）
# key = "{user_id}:{conversation_id}" —— 按用户隔离，两个用户同 ID 不会串数据
_SHARED_CONTEXTS: dict[str, ConversationContext] = {}
_MAX_CONTEXTS = 500  # 容量上限：超限清最旧，防内存无限膨胀


class ChatService:
    """聊天路由服务：意图分类 + 动作执行 + 回复组装 + 会话上下文。"""

    def __init__(self, settings: Settings, pipeline_getter: Any, supplier_crawler: Any,
                 listing_agent: Any, contexts: dict[str, ConversationContext] | None = None,
                 supplier_factory: Any = None, script_generator: Any = None):
        self.settings = settings
        self.pipeline_getter = pipeline_getter
        self.supplier_crawler = supplier_crawler
        self.listing_agent = listing_agent
        # 运行时货源平台切换工厂：chat 说"去1688找货源" → factory("1688") 建真实 crawler
        self.supplier_factory = supplier_factory
        # 带货脚本生成器（由 API 层注入；None 时该意图降级为引导）
        self.script_generator = script_generator
        # 会话上下文：conversation_id → 最近一次业务结果（默认模块级共享，跨请求生效）
        self._contexts = contexts if contexts is not None else _SHARED_CONTEXTS
        self._user_id = ""  # 当前请求用户（handle/handle_stream 开头设置，_ctx 用于隔离）

    def _supplier_crawler_for(self, source: str | None):
        """解析指定货源源（1688/jiafang/sample/api）；无指定 → 默认注入 crawler。"""
        src = (source or "").strip().lower()
        if src and self.supplier_factory:
            logger.info("[chat] 切换货源源 → %s", src)
            return self.supplier_factory(src)
        return self.supplier_crawler

    def _search_with_platform_fallback(self, src: str, keywords: list[str],
                                       top_n: int, conversation_id: str = "",
                                       ) -> tuple[list[Any], str, str]:
        """在指定货源源搜索；1688 直连不可用（登录墙/风控）时自动回退找家纺网。

        返回 (offers, 实际使用的平台, 说明文案)。企业级降级：不把错误丢给用户，
        而是切回可用平台继续出货源，并如实说明切换原因。
        """
        try:
            crawler = self._supplier_crawler_for(src or None)
            offers = crawler.search_offers(keywords[:3], top_n=top_n)
            return offers, (src or "jiafang"), ""
        except CrawlerError as e:
            if src == "1688":
                # 1688 直连默认未启用（JS 渲染+登录墙+风控）：自动回退找家纺网
                logger.warning("[chat] 1688 不可用，回退找家纺网: %s", e)
                self._ctx(conversation_id).supplier_source = ""  # 会话源重置为默认
                try:
                    offers = self.supplier_crawler.search_offers(keywords[:3], top_n=top_n)
                    return offers, "jiafang", "1688 直连需要登录态或开放平台 API（当前未配置），已自动切回找家纺网："
                except Exception as e2:
                    logger.exception("[chat] 回退找家纺网也失败")
                    return [], "1688", f"1688 暂不可用（{type(e).__name__}），且找家纺网也搜索失败（{type(e2).__name__}）。"
            raise

    # ---------------- 会话上下文 ----------------

    def _ctx(self, conversation_id: str) -> ConversationContext:
        cid = conversation_id or "default"
        key = f"{self._user_id}:{cid}"
        if key not in self._contexts:
            # 容量上限：超限清最旧（FIFO 按插入顺序，防内存无限膨胀）
            if len(self._contexts) >= _MAX_CONTEXTS:
                oldest = next(iter(self._contexts))
                self._contexts.pop(oldest, None)
            self._contexts[key] = ConversationContext()
        return self._contexts[key]

    def _save_result(self, conversation_id: str, intent: str, query: str,
                     data: dict[str, Any] | None) -> None:
        if not data:
            return
        ctx = self._ctx(conversation_id)
        ctx.products = data.get("products") or []
        ctx.offers = data.get("offers") or []
        ctx.report = data.get("report")
        ctx.listing = data.get("listing")
        ctx.listing_path = data.get("listing_path") or ""
        ctx.last_query = query
        ctx.last_intent = intent

    def _classify_with_context(self, message: str, conversation_id: str) -> str:
        """基础意图 + 上下文引用（"第一条货源生成素材" → 不再重新搜索）。"""
        intent = classify_intent(message)
        ctx = self._ctx(conversation_id)
        if intent in ("out_of_scope", "self_intro", "switch_supplier"):
            return intent
        if ctx.has_content() and has_context_ref(message):
            # 引用货源/商品 + 素材词 → 基于上下文生成素材；否则 → 基于上下文回答
            if intent == "listing_only" or any(t in message for t in
                                               ("素材", "上架", "标题", "关键词", "描述", "翻译")):
                return "listing_context"
            if intent == "profit" or any(t in message for t in
                                         ("利润", "赚", "毛利", "净利", "成本", "回本", "划算")):
                return "profit"  # 利润测算：优先用上下文竞品售价/货源进价估算
            if intent == "sourcing_only" or any(t in message for t in
                                                ("货源", "价格", "代发", "链接", "这个")):
                return "sourcing_context"
            if "分析" in message or "能不能" in message or "卖" in message:
                return "select_product"  # 分析类仍重新选品（上下文仅供参考）
        # 强指代但无上下文内容 → 引导先找货源/先选品，而不是拿指代词去搜索
        if has_strong_context_ref(message) and not ctx.has_content():
            if any(t in message for t in ("素材", "上架", "标题", "关键词", "描述", "翻译")):
                return "listing_context"
            return "sourcing_context"
        return intent

    def handle(self, message: str, region: str = "JP", category: str = "bedding",
               language: str = "ja", conversation_id: str = "",
               user_id: str = "") -> dict[str, Any]:
        """处理一条用户消息，返回聊天响应（reply + intent + data）。"""
        self._user_id = str(user_id or "")
        intent = self._classify_with_context(message, conversation_id)

        if intent == "self_intro":
            return {"reply": SELF_INTRO_REPLY, "intent": "self_intro", "data": None}
        if intent == "switch_supplier":
            return self._switch_supplier(message, conversation_id)
        if intent == "select_product":
            return self._run_selection(message, region, category, language, conversation_id)
        if intent == "profit":
            return self._run_profit(message, conversation_id)
        if intent == "sourcing_only":
            return self._run_sourcing(message, top_n=6, conversation_id=conversation_id)
        if intent == "listing_only":
            return self._run_listing(message, language, conversation_id=conversation_id)
        if intent == "script_only":
            return self._run_script(message, conversation_id)
        if intent == "listing_context":
            return self._run_listing_from_context(message, language, conversation_id)
        if intent == "sourcing_context":
            return self._run_sourcing_from_context(message, conversation_id)
        if intent == "qa_ecommerce":
            topic = _strip_tokens(message, QA_TOKENS) or message[:20]
            return {
                "reply": QA_REPLY_TEMPLATE.format(topic=topic),
                "intent": "qa_ecommerce",
                "data": None,
            }
        return {
            "reply": OUT_OF_SCOPE_REPLY,
            "intent": "out_of_scope",
            "data": None,
        }

    def handle_stream(self, message: str, region: str = "JP", category: str = "bedding",
                      language: str = "ja", conversation_id: str = "",
                      user_id: str = "") -> Any:
        """流式处理：yield 事件 dict（SSE 推送）。

        事件类型：
        - {"type":"status","stage":...,"text":...}   阶段进度（真实流水线执行中）
        - {"type":"delta","text":"..."}              回复文本片段（打字机效果）
        - {"type":"done","reply":...,"intent":...,"needs_product":...,"data":...}
        - {"type":"error","text":"..."}              失败
        体验目标（像市面大模型）：开场白先流式打出 → 每个真实阶段完成立刻追加
        一段结果小结（边跑边出字）→ 完成事件带卡片。
        重活用后台线程跑，进度/小结经线程安全队列推给 SSE。
        上下文：conversation_id 相同的会话，后续消息可引用上次结果
        （如"第一条货源生成素材"→ 不重新搜索，直接用上次货源）。
        """
        import queue
        import threading
        import time

        self._user_id = str(user_id or "")
        intent = self._classify_with_context(message, conversation_id)

        # ---- 快速分支：自我介绍 / 范围外 / 电商常识 / 缺商品词：直接流式输出 ----
        if intent == "self_intro":
            for chunk in _chunk_text(SELF_INTRO_REPLY):
                yield {"type": "delta", "text": chunk}
                time.sleep(0.018)
            yield {"type": "done", "reply": SELF_INTRO_REPLY, "intent": intent,
                   "needs_product": False, "data": None}
            return
        if intent == "switch_supplier":
            yield from self._stream_switch_supplier(message, conversation_id)
            return
        if intent == "profit":
            # 利润测算：本地计算，快速流式输出
            result = self._run_profit(message, conversation_id)
            reply = result["reply"]
            for chunk in _chunk_text(reply):
                yield {"type": "delta", "text": chunk}
                time.sleep(0.012)
            yield {"type": "done", "reply": reply, "intent": intent,
                   "needs_product": result.get("needs_product", False),
                   "data": result.get("data")}
            return
        if intent == "out_of_scope":
            reply = OUT_OF_SCOPE_REPLY
            for chunk in _chunk_text(reply):
                yield {"type": "delta", "text": chunk}
                time.sleep(0.018)
            yield {"type": "done", "reply": reply, "intent": intent,
                   "needs_product": False, "data": None}
            return
        if intent == "qa_ecommerce":
            topic = _strip_tokens(message, QA_TOKENS) or message[:20]
            reply = QA_REPLY_TEMPLATE.format(topic=topic)
            for chunk in _chunk_text(reply):
                yield {"type": "delta", "text": chunk}
                time.sleep(0.018)
            yield {"type": "done", "reply": reply, "intent": intent,
                   "needs_product": False, "data": None}
            return

        # ---- 缺商品词（select/listing）----
        if intent in ("select_product", "listing_only", "script_only"):
            product = extract_product(message)
            if not product:
                reply = NEED_PRODUCT_REPLY
                for chunk in _chunk_text(reply):
                    yield {"type": "delta", "text": chunk}
                    time.sleep(0.018)
                yield {"type": "done", "reply": reply, "intent": intent,
                       "needs_product": True, "data": None}
                return

        # ---- 上下文快速分支：引用上次货源/竞品，不再重新搜索 ----
        if intent == "listing_context":
            yield from self._stream_listing_from_context(message, language, conversation_id)
            return
        if intent == "sourcing_context":
            yield from self._stream_sourcing_from_context(message, conversation_id)
            return

        # ---- 重活分支：后台线程跑 → 阶段步骤 + 阶段小结边跑边出（前端并入"深度思考"面板） ----
        q: queue.Queue = queue.Queue()

        def on_progress(stage: str, text: str, update: Any = None) -> None:
            q.put({"type": "status", "stage": stage, "text": text})
            summary = _stage_summary(stage, update, region=region)
            if summary:
                q.put({"type": "delta", "text": summary})

        def _run() -> None:
            try:
                if intent == "select_product":
                    product = extract_product(message) or ""
                    pipeline = self.pipeline_getter(
                        self.settings, category_name=category, enabled_stages=None)
                    result = pipeline.run(
                        query=product, region=region, category=category,
                        language=language, on_progress=on_progress, parallel=True,
                        supplier_source=self._ctx(conversation_id).supplier_source or None)
                    reply, data = _build_selection_reply(result, product, region)
                    self._save_result(conversation_id, intent, product, data)
                    q.put({"type": "done", "reply": reply, "intent": intent,
                           "needs_product": False, "data": data})
                elif intent == "sourcing_only":
                    keywords_text = _strip_tokens(message, SOURCE_TOKENS + QA_TOKENS)
                    keywords = [k.strip() for k in keywords_text.split() if k.strip()]
                    if not keywords:
                        q.put({"type": "done", "reply": NEED_PRODUCT_REPLY,
                               "intent": intent, "needs_product": True, "data": None})
                        return
                    src = self._ctx(conversation_id).supplier_source or ""
                    platform = "1688" if src == "1688" else "找家纺网"
                    q.put({"type": "status", "stage": "sourcing",
                           "text": f"正在{platform}搜索货源…"})
                    offers, used_src, note = self._search_with_platform_fallback(
                        src, keywords, 6, conversation_id)
                    platform = "1688" if used_src == "1688" else "找家纺网"
                    if not offers:
                        q.put({"type": "done",
                               "reply": f"{note}在{platform}没搜到「{' '.join(keywords)}」的货源，"
                                        f"换个关键词试试（比如：找 牛奶绒床笠 货源）。",
                               "intent": intent, "needs_product": False,
                               "data": {"offers": []}})
                        return
                    lines = [f"{note}在{platform}找到 {len(offers)} 条真实货源："]
                    for o in offers[:5]:
                        lines.append(f"· {o.title[:36]} | {o.price} | {o.supplier_name}")
                    data = {"offers": [o.model_dump() for o in offers]}
                    self._save_result(conversation_id, intent, " ".join(keywords), data)
                    q.put({"type": "done", "reply": "\n".join(lines), "intent": intent,
                           "needs_product": False,
                           "data": data})
                elif intent == "listing_only":
                    product_name = extract_product(message) or ""
                    q.put({"type": "status", "stage": "listing",
                           "text": "正在生成日文上架素材…"})
                    product = Product(title=product_name, price="", currency="JPY",
                                      url="", description="", sales=0, category="bedding")
                    out = self.listing_agent.run(
                        {"products": [product], "report": None, "region": "JP",
                         "language": language, "image_dir": None})
                    listing = out.get("listing")
                    if not listing:
                        q.put({"type": "done",
                               "reply": "素材生成没有产出，请检查 LLM 配置后重试。",
                               "intent": intent, "needs_product": False, "data": None})
                        return
                    reply = (f"「{product_name}」的日文上架素材已生成"
                             f"（含标题/关键词/描述/规格翻译）：\n"
                             f"· 标题：{listing.title}\n"
                             f"· 关键词：{' '.join(listing.keywords[:5])}\n"
                             f"· 素材文件：{out.get('listing_path', '')}")
                    data = {"listing": listing.model_dump(),
                            "listing_path": out.get("listing_path", "")}
                    self._save_result(conversation_id, intent, product_name, data)
                    q.put({"type": "done", "reply": reply, "intent": intent,
                           "needs_product": False,
                           "data": data})
                elif intent == "script_only":
                    product_name = extract_product(message) or ""
                    q.put({"type": "status", "stage": "listing",
                           "text": "正在生成日文带货脚本…"})
                    result = self._run_script(message, conversation_id)
                    reply = result["reply"]
                    q.put({"type": "delta", "text": "✓ 日文带货脚本已生成（含开场钩子/卖点/结尾 CTA）。"})
                    q.put({"type": "done", "reply": reply, "intent": intent,
                           "needs_product": False, "data": result.get("data")})
            except Exception as e:
                logger.exception("聊天流式执行失败: %s", e)
                q.put({"type": "error", "text": f"处理失败了（{type(e).__name__}），"
                                                f"请检查后端日志后重试。"})

        threading.Thread(target=_run, daemon=True).start()

        # 消费队列：status 转发、阶段小结 delta 转发、done 直接结束（文本已分段输出）
        while True:
            ev = q.get()
            if ev["type"] in ("done", "error"):
                yield ev
                return
            yield ev

    # ---------------- 货源平台切换（switch_supplier） ----------------

    def _switch_supplier(self, message: str,
                         conversation_id: str = "") -> dict[str, Any]:
        """切换会话级货源源；带商品词时立即用目标平台搜索。

        - "去1688找货源 / 换回找家纺网"（纯切换）→ 确认切换，会话后续货源走新平台
        - "用1688找 牛奶绒床笠 的货源" → 切换 + 立即搜索
        - "去其他地方找货源"（没点名）→ 给出可选平台提示，保持当前源
        """
        src = parse_supplier_source(message)
        if src is None:
            return {
                "reply": f"可以帮你切换货源平台，{_SUPPLIER_CHOICES_HINT}"
                         f"直接说：去1688找货源 / 换回找家纺网。",
                "intent": "switch_supplier", "data": None,
            }
        ctx = self._ctx(conversation_id)
        prev = ctx.supplier_source or "jiafang（找家纺网）"
        ctx.supplier_source = src
        platform = "1688（综合批发）" if src == "1688" else "找家纺网（家纺垂直站）"
        # 剥掉切换词/货源词/语气词后剩余即商品词
        keywords_text = _strip_tokens(
            message,
            SOURCE_TOKENS + QA_TOKENS + SUPPLIER_SWITCH_TOKENS + _SWITCH_ACTION_WORDS)
        keywords = [k.strip() for k in keywords_text.split() if k.strip()]
        if not keywords:
            return {
                "reply": f"已把货源平台从 {prev} 切换到 {platform}，"
                         f"之后的货源搜索都走它。也可以直接说："
                         f"用{'1688' if src == '1688' else '找家纺'}找 牛奶绒床笠 的货源。",
                "intent": "switch_supplier", "data": None,
            }
        # 带商品词 → 切换 + 立即用目标平台搜索（1688 不可用时自动回退找家纺网）
        offers, used_src, note = self._search_with_platform_fallback(
            src, keywords, 6, conversation_id)
        platform = "1688（综合批发）" if used_src == "1688" else "找家纺网（家纺垂直站）"
        if not offers:
            return {
                "reply": f"{note}已切换目标为{platform}，但在该平台没搜到「{' '.join(keywords)}」"
                         f"的货源，换个关键词试试。",
                "intent": "switch_supplier", "data": {"offers": []},
            }
        lines = [f"{note}已切换目标为{platform}，找到 {len(offers)} 条真实货源："]
        for o in offers[:5]:
            lines.append(f"· {o.title[:36]} | {o.price} | {o.supplier_name}")
        data = {"offers": [o.model_dump() for o in offers]}
        self._save_result(conversation_id, "sourcing_only", " ".join(keywords), data)
        return {"reply": "\n".join(lines), "intent": "switch_supplier", "data": data}

    def _stream_switch_supplier(self, message: str,
                                conversation_id: str = "") -> Any:
        """流式版切换（SSE）：快速分支直接输出，不需要后台线程。"""
        import time
        result = self._switch_supplier(message, conversation_id)
        reply = result["reply"]
        for chunk in _chunk_text(reply):
            yield {"type": "delta", "text": chunk}
            time.sleep(0.012)
        yield {"type": "done", "reply": reply, "intent": result["intent"],
               "needs_product": False, "data": result.get("data")}

    # ---------------- 意图动作 ----------------

    def _run_selection(self, message: str, region: str, category: str,
                       language: str, conversation_id: str = "") -> dict[str, Any]:
        product = extract_product(message)
        if not product:
            return {"reply": NEED_PRODUCT_REPLY, "intent": "select_product",
                    "needs_product": True, "data": None}
        try:
            pipeline = self.pipeline_getter(
                self.settings, category_name=category, enabled_stages=None)
            result = pipeline.run(
                query=product, region=region, category=category, language=language,
                parallel=True,
                supplier_source=self._ctx(conversation_id).supplier_source or None)
        except Exception as e:
            logger.exception("聊天选品失败: %s", e)
            return {"reply": f"选品分析暂时跑失败了（{type(e).__name__}），"
                             f"请检查后端日志后重试。", "intent": "select_product", "data": None}
        if result.get("error"):
            return {"reply": f"选品分析遇到问题：{result['error']}", "intent": "select_product",
                    "data": None}
        reply, data = _build_selection_reply(result, product, region)
        self._save_result(conversation_id, "select_product", product, data)
        return {"reply": reply, "intent": "select_product", "data": data}

    # ---------------- 利润测算（profit） ----------------

    _PROFIT_PARAM_RE = {
        "selling": re.compile(r"售价\s*[:：=]?\s*(\d+)"),
        "cost": re.compile(r"(?:进价|成本)\s*[:：=]?\s*(\d+)"),
        "shipping": re.compile(r"运费\s*[:：=]?\s*(\d+)"),
        "ads": re.compile(r"广告\s*[:：=]?\s*(\d+)"),
    }

    def _extract_profit_params(self, message: str) -> dict[str, float] | None:
        """从消息提取显式参数（售价/成本/运费/广告）；无任何参数 → None。"""
        params: dict[str, float] = {}
        for key, pattern in self._PROFIT_PARAM_RE.items():
            m = pattern.search(message)
            if m:
                params[key] = float(m.group(1))
        return params or None

    def _profit_from_context(self, conversation_id: str) -> dict[str, Any] | None:
        """用会话上下文估算：最近竞品售价(JPY) + 最近货源进价(CNY)。"""
        ctx = self._ctx(conversation_id)
        selling = 0.0
        cost = 0.0
        shipping = 0.0
        if ctx.products and ctx.products[0].get("price_value"):
            selling = float(ctx.products[0]["price_value"])
        if ctx.offers and ctx.offers[0].get("price_value"):
            cost = float(ctx.offers[0]["price_value"])
        if not selling and not cost:
            return None
        if selling <= 0 or cost <= 0:
            return {"partial": True, "selling": selling, "cost": cost}
        return {"selling": selling, "cost": cost, "shipping": shipping}

    def _run_profit(self, message: str,
                    conversation_id: str = "") -> dict[str, Any]:
        """利润测算：显式参数优先，其次用上下文（最近竞品售价/货源进价）估算。"""
        from tiktok_ecommerce.services.profit import ProfitRequest, compute_profit

        params = self._extract_profit_params(message)
        ctx = self._ctx(conversation_id)
        ctx_hint = ""
        if params is None:
            got = self._profit_from_context(conversation_id)
            if got is None:
                return {
                    "reply": ("利润测算需要售价和进价。可以告诉我具体数字，格式：\n"
                              "· 售价3000 成本80 运费50（售价日元，成本/运费人民币）\n"
                              "· 或者先让我 分析某商品 或 找货源，再用 这个利润多少 自动估算"),
                    "intent": "profit", "needs_product": True, "data": None,
                }
            if got.get("partial"):
                return {
                    "reply": ("只拿到部分数据：售价≈{sell} JPY、进价≈{cost} CNY。"
                              "补全后我可以帮你算利润（格式：售价3000 成本80 运费50）").format(
                        sell=got["selling"], cost=got["cost"]),
                    "intent": "profit", "data": None,
                }
            params = got
            ctx_hint = "（按上次竞品售价与货源进价估算）"
        elif ctx.products and ctx.offers and "cost" not in params:
            # 给了售价但没给成本 → 用上下文货源进价补充
            if ctx.offers[0].get("price_value"):
                params.setdefault("cost", float(ctx.offers[0]["price_value"]))
                ctx_hint = "（成本按上次货源进价估算）"

        if "selling" not in params or "cost" not in params:
            missing = "、".join(
                k for k, label in (("selling", "售价"), ("cost", "成本")) if k not in params)
            return {
                "reply": f"还缺 {missing}。格式参考：售价3000 成本80 运费50（售价日元，成本/运费人民币）。",
                "intent": "profit", "data": None,
            }

        try:
            req = ProfitRequest(
                selling_price_jpy=params["selling"],
                cost_cny=params.get("cost", 0),
                shipping_cny=params.get("shipping", 0),
                ads_jpy=params.get("ads", 0),
            )
            r = compute_profit(req, default_fx=self.settings.fx_cny_jpy or 21.0)
        except Exception as e:
            logger.exception("利润测算失败: %s", e)
            return {"reply": f"利润测算失败了（{type(e).__name__}），请检查参数后重试。",
                    "intent": "profit", "data": None}

        emoji = "✅" if r.net_profit_jpy > 0 else "⚠️"
        reply = (
            f"{emoji} 单件利润测算{ctx_hint}：\n"
            f"· 售价 {r.selling_price_jpy:.0f} JPY｜进价折 {r.cost_jpy:.0f} JPY｜运费折 {r.shipping_jpy:.0f} JPY\n"
            f"· 平台佣金 {r.platform_fee_jpy:.0f} + 支付费 {r.payment_fee_jpy:.0f}"
            f"{f' + 广告 {r.ads_jpy:.0f}' if r.ads_jpy else ''}\n"
            f"· 毛利 {r.gross_profit_jpy:.0f} JPY → 净利 {r.net_profit_jpy:.0f} JPY"
            f"（净利率 {r.net_margin * 100:.1f}%）\n"
            f"· {f'广告投入约 {r.break_even_units:.1f} 件回本' if r.break_even_units else '无广告投入，无需回本'}\n"
            f"汇率 {r.fx_used:.0f}（CNY→JPY）与费率均为估算，见数据卡明细。"
        )
        data = {"profit": r.model_dump()}
        return {"reply": reply, "intent": "profit", "data": data}

    def _run_sourcing(self, message: str, top_n: int = 6,
                      conversation_id: str = "") -> dict[str, Any]:
        keywords_text = _strip_tokens(message, SOURCE_TOKENS + QA_TOKENS)
        keywords = [k.strip() for k in keywords_text.split() if k.strip()]
        if not keywords:
            return {"reply": NEED_PRODUCT_REPLY, "intent": "sourcing_only",
                    "needs_product": True, "data": None}
        src = self._ctx(conversation_id).supplier_source or ""
        platform = "1688" if src == "1688" else "找家纺网"
        offers, used_src, note = self._search_with_platform_fallback(
            src, keywords, top_n, conversation_id)
        platform = "1688" if used_src == "1688" else "找家纺网"
        if not offers:
            return {"reply": f"{note}在{platform}没搜到「{' '.join(keywords)}」的货源，"
                             f"换个关键词试试（比如：找 牛奶绒床笠 货源）。",
                    "intent": "sourcing_only", "data": {"offers": []}}
        lines = [f"{note}在{platform}找到 {len(offers)} 条真实货源："]
        for o in offers[:5]:
            lines.append(f"· {o.title[:36]} | {o.price} | {o.supplier_name}")
        data = {"offers": [o.model_dump() for o in offers]}
        self._save_result(conversation_id, "sourcing_only", " ".join(keywords), data)
        return {
            "reply": "\n".join(lines),
            "intent": "sourcing_only",
            "data": data,
        }

    def _run_listing(self, message: str, language: str,
                     conversation_id: str = "") -> dict[str, Any]:
        product_name = extract_product(message)
        if not product_name:
            return {"reply": NEED_PRODUCT_REPLY, "intent": "listing_only",
                    "needs_product": True, "data": None}
        try:
            # 用户只给了商品名 → 构造最小商品上下文，ListingAgent 生成文案
            product = Product(title=product_name, price="", currency="JPY",
                              url="", description="", sales=0, category="bedding")
            out = self.listing_agent.run(
                {"products": [product], "report": None, "region": "JP",
                 "language": language, "image_dir": None})
        except Exception as e:
            logger.exception("聊天生成素材失败: %s", e)
            return {"reply": f"素材生成失败了（{type(e).__name__}），请稍后重试。",
                    "intent": "listing_only", "data": None}
        listing = out.get("listing")
        if not listing:
            return {"reply": "素材生成没有产出，请检查 LLM 配置后重试。",
                    "intent": "listing_only", "data": None}
        data = {"listing": listing.model_dump(), "listing_path": out.get("listing_path", "")}
        self._save_result(conversation_id, "listing_only", product_name, data)
        return {
            "reply": f"「{product_name}」的日文上架素材已生成（含标题/关键词/描述/规格翻译）：\n"
                     f"· 标题：{listing.title}\n"
                     f"· 关键词：{' '.join(listing.keywords[:5])}\n"
                     f"· 素材文件：{out.get('listing_path', '')}",
            "intent": "listing_only",
            "data": data,
        }

    # ---------------- 带货视频脚本（script_only） ----------------

    _SCRIPT_PROMPT = """你是 TikTok Shop 日本站带货短视频编剧。为商品「{product}」写一条 30-45 秒的日文带货口播脚本。

要求：
1. 全篇日语（贴近日本消费者），语气口语化、有临场感
2. 结构：开场 3 秒钩子（痛点/好奇）→ 卖点演示（2-3 个，具体到使用场景）→ 结尾 CTA（引导下单/进直播间）
3. 含台本标注：[开场画面] [口播] [产品特写] 等
4. 输出纯文本，不要 JSON

商品补充信息：{context}"""

    def _run_script(self, message: str,
                    conversation_id: str = "") -> dict[str, Any]:
        """生成日文带货视频脚本（LLM 生成；未配置时诚实降级引导）。"""
        product_name = extract_product(message)
        if not product_name:
            return {"reply": NEED_PRODUCT_REPLY, "intent": "script_only",
                    "needs_product": True, "data": None}
        if self.script_generator is None:
            return {
                "reply": "带货脚本生成器尚未配置（需要 LLM），先配置 LLM 后再试。"
                         "你可以先用：生成 X 的上架素材。",
                "intent": "script_only", "data": None,
            }
        # 上下文补充：最近货源/竞品信息让脚本更具体
        ctx = self._ctx(conversation_id)
        context_lines = []
        if ctx.offers:
            o = ctx.offers[0]
            context_lines.append(f"货源：{o.get('title', '')}（{o.get('price', '')}）")
        if ctx.report and isinstance(ctx.report, dict):
            if ctx.report.get("summary"):
                context_lines.append(f"选品结论：{ctx.report.get('summary', '')[:80]}")
        context = "\n".join(context_lines) or "暂无补充信息"
        try:
            resp = self.script_generator.invoke(
                self._SCRIPT_PROMPT.format(product=product_name, context=context))
            script = str(getattr(resp, "content", "") or "").strip()
            if not script:
                raise ValueError("脚本为空")
        except Exception as e:
            logger.exception("带货脚本生成失败: %s", e)
            return {"reply": f"带货脚本生成失败了（{type(e).__name__}），请稍后重试。",
                    "intent": "script_only", "data": None}
        return {
            "reply": f"「{product_name}」的日文带货脚本（30-45秒口播）：\n\n{script}",
            "intent": "script_only",
            "data": {"script": script, "product": product_name},
        }

    # ---------------- 上下文引用分支（不重新搜索） ----------------

    def _pick_context_offer(self, conversation_id: str, message: str) -> dict | None:
        """按"第N条"选上下文里的货源（默认第一条）。"""
        ctx = self._ctx(conversation_id)
        if not ctx.offers:
            return None
        idx = context_order_index(message)
        if idx is None:
            idx = 0
        if idx >= len(ctx.offers):
            idx = 0
        return ctx.offers[idx]

    def _run_listing_from_context(self, message: str, language: str,
                                  conversation_id: str) -> dict[str, Any]:
        """用会话上下文里的货源生成上架素材（跳过 TikTok 搜索/RAG）。"""
        ctx = self._ctx(conversation_id)
        offer = self._pick_context_offer(conversation_id, message)
        if not offer:
            return {"reply": "我还没有上次的货源结果。你可以先让我找货源，比如：找 牛奶绒床笠 货源。",
                    "intent": "listing_context", "needs_product": True, "data": None}
        try:
            product = Product(
                title=offer.get("title") or ctx.last_query or "商品",
                price=offer.get("price", ""), currency="JPY",
                url=offer.get("url", ""), description="", sales=0, category="bedding",
                images=[i for i in (offer.get("images") or []) if i],
            )
            out = self.listing_agent.run(
                {"products": [product], "report": None, "region": "JP",
                 "language": language, "image_dir": None})
        except Exception as e:
            logger.exception("上下文生成素材失败: %s", e)
            return {"reply": f"素材生成失败了（{type(e).__name__}），请稍后重试。",
                    "intent": "listing_context", "data": None}
        listing = out.get("listing")
        if not listing:
            return {"reply": "素材生成没有产出，请检查 LLM 配置后重试。",
                    "intent": "listing_context", "data": None}
        data = {"listing": listing.model_dump(), "listing_path": out.get("listing_path", "")}
        data["offers"] = ctx.offers  # 保留货源卡片
        self._save_result(conversation_id, "listing_context", offer.get("title", ""), data)
        idx = context_order_index(message)
        nth = f"第{idx + 1}条" if idx is not None else "这条"
        return {
            "reply": f"已用刚才找家纺网的第{nth}条货源「{offer.get('title', '')[:30]}」"
                     f"（{offer.get('supplier_name', '')}，{offer.get('price', '')}）生成日文上架素材：\n"
                     f"· 标题：{listing.title}\n"
                     f"· 关键词：{' '.join(listing.keywords[:5])}\n"
                     f"· 素材文件：{out.get('listing_path', '')}\n"
                     f"货源链接：{offer.get('url', '')}",
            "intent": "listing_context",
            "data": data,
        }

    def _run_sourcing_from_context(self, message: str, conversation_id: str) -> dict[str, Any]:
        """基于上下文回答货源问题（比价/链接/详情），不重新搜索。"""
        ctx = self._ctx(conversation_id)
        offer = self._pick_context_offer(conversation_id, message)
        if not offer:
            return {"reply": "我还没有上次的货源结果。你可以先让我找货源，比如：找 牛奶绒床笠 货源。",
                    "intent": "sourcing_context", "needs_product": True, "data": None}
        idx = context_order_index(message)
        nth = f"第{idx + 1}条" if idx is not None else "这条"
        lines = [f"这是刚才找家纺网匹配到的货源（{nth}）信息：",
                 f"· {offer.get('title', '')}",
                 f"· 店铺：{offer.get('supplier_name', '')} | 供货价：{offer.get('price', '')}",
                 f"· 一件代发：{'是' if offer.get('delivery') else '需咨询'}",
                 f"· 商品链接：{offer.get('url', '')}（点击直达）"]
        return {
            "reply": "\n".join(lines),
            "intent": "sourcing_context",
            "data": {"offers": ctx.offers},
        }

    def _stream_listing_from_context(self, message: str, language: str,
                                     conversation_id: str) -> Any:
        """流式版：上下文货源生成素材（短流程，直接 yield 事件）。"""
        import time

        ctx = self._ctx(conversation_id)
        offer = self._pick_context_offer(conversation_id, message)
        if not offer:
            reply = "我还没有上次的货源结果。你可以先让我找货源，比如：找 牛奶绒床笠 货源。"
            for chunk in _chunk_text(reply):
                yield {"type": "delta", "text": chunk}
                time.sleep(0.018)
            yield {"type": "done", "reply": reply, "intent": "listing_context",
                   "needs_product": True, "data": None}
            return
        idx = context_order_index(message)
        nth = f"第{idx + 1}条" if idx is not None else "第一条"
        yield {"type": "status", "stage": "listing",
               "text": f"正在用刚才匹配的{nth}货源生成日文上架素材…"}
        try:
            product = Product(
                title=offer.get("title") or ctx.last_query or "商品",
                price=offer.get("price", ""), currency="JPY",
                url=offer.get("url", ""), description="", sales=0, category="bedding",
                images=[i for i in (offer.get("images") or []) if i],
            )
            out = self.listing_agent.run(
                {"products": [product], "report": None, "region": "JP",
                 "language": language, "image_dir": None})
        except Exception as e:
            logger.exception("上下文流式生成素材失败: %s", e)
            yield {"type": "error", "text": f"素材生成失败了（{type(e).__name__}），请稍后重试。"}
            return
        listing = out.get("listing")
        if not listing:
            yield {"type": "error", "text": "素材生成没有产出，请检查 LLM 配置后重试。"}
            return
        reply = (f"已用刚才找家纺网的{nth}货源「{offer.get('title', '')[:30]}」"
                 f"（{offer.get('supplier_name', '')}，{offer.get('price', '')}）生成日文上架素材：\n"
                 f"· 标题：{listing.title}\n"
                 f"· 关键词：{' '.join(listing.keywords[:5])}\n"
                 f"· 素材文件：{out.get('listing_path', '')}\n"
                 f"货源链接：{offer.get('url', '')}")
        data = {"listing": listing.model_dump(), "listing_path": out.get("listing_path", ""),
                "offers": ctx.offers}
        self._save_result(conversation_id, "listing_context", offer.get("title", ""), data)
        yield {"type": "delta", "text": f"✓ 已用{nth}货源生成日文素材（标题/关键词/描述/规格翻译）。"}
        yield {"type": "done", "reply": reply, "intent": "listing_context",
               "needs_product": False, "data": data}

    def _stream_sourcing_from_context(self, message: str, conversation_id: str) -> Any:
        """流式版：基于上下文回答货源问题。"""
        import time

        ctx = self._ctx(conversation_id)
        offer = self._pick_context_offer(conversation_id, message)
        if not offer:
            reply = "我还没有上次的货源结果。你可以先让我找货源，比如：找 牛奶绒床笠 货源。"
            for chunk in _chunk_text(reply):
                yield {"type": "delta", "text": chunk}
                time.sleep(0.018)
            yield {"type": "done", "reply": reply, "intent": "sourcing_context",
                   "needs_product": True, "data": None}
            return
        idx = context_order_index(message)
        nth = f"第{idx + 1}条" if idx is not None else "这条"
        reply = (f"这是刚才找家纺网匹配到的货源（{nth}）信息：\n"
                 f"· {offer.get('title', '')}\n"
                 f"· 店铺：{offer.get('supplier_name', '')} | 供货价：{offer.get('price', '')}\n"
                 f"· 一件代发：{'是' if offer.get('delivery') else '需咨询'}\n"
                 f"· 商品链接：{offer.get('url', '')}（点击直达）")
        for chunk in _chunk_text(reply):
            yield {"type": "delta", "text": chunk}
            time.sleep(0.018)
        yield {"type": "done", "reply": reply, "intent": "sourcing_context",
               "needs_product": False, "data": {"offers": ctx.offers}}


def _strip_tokens(text: str, tokens: list[str]) -> str:
    """从文本中剥掉指定 token 与停用词，返回剩余内容。"""
    out = text
    for t in tokens:
        out = out.replace(t, " ")
    for w in STOP_WORDS:
        out = out.replace(w, " ")
    return out.strip(_PUNCT)


def _chunk_text(text: str, max_len: int = 32) -> list[str]:
    """把回复文本切成流式输出块（打字机效果）：优先按行，行长超限再切。"""
    if not text:
        return [""]
    chunks: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        if len(line) <= max_len:
            chunks.append(line)
            continue
        # 长行按标点/空格/固定长度切
        buf = ""
        for ch in line:
            buf += ch
            if len(buf) >= max_len and ch in " .,;，。；！？、!?":
                chunks.append(buf)
                buf = ""
        if buf:
            chunks.append(buf)
    return chunks or [text[:max_len]]


def _stage_summary(stage: str, update: Any, region: str = "JP") -> str | None:
    """把某阶段的产物压缩成一句流式小结（像大模型逐步展示处理过程）。

    无产物/产物为空 → 返回 None（只显示 status 转圈，不追加文本）。
    """
    if not isinstance(update, dict):
        return None
    if stage == "crawler":
        products = update.get("products") or []
        if not products:
            # 采集为空：若有品类过滤说明则如实展示（如"搜到的都不是床上用品"）
            return update.get("filtered_note")
        first = products[0]
        title = getattr(first, "title", "") or (first.get("title", "") if isinstance(first, dict) else "")
        t = title[:26] + ("…" if len(title) > 26 else "")
        return f"✓ 采集到 {len(products)} 个真实竞品（JP），例如「{t}」。"
    if stage == "analyzer":
        report = update.get("report")
        if not report:
            return None
        summary = getattr(report, "summary", None) or (report.get("summary", "") if isinstance(report, dict) else "")
        return f"✓ 评论分析完成：{summary[:60]}"
    if stage == "sourcing":
        offers = update.get("offers") or []
        if not offers:
            return None
        top = offers[0]
        price = getattr(top, "price", "") or (top.get("price", "") if isinstance(top, dict) else "")
        label = None
        sb = getattr(top, "score_breakdown", None) or (top.get("score_breakdown", {}) if isinstance(top, dict) else {})
        if isinstance(sb, dict):
            label = sb.get("visual_label")
        hint = f"，Top1 视觉「{label}」" if label else ""
        return f"✓ 匹配到 {len(offers)} 条真实货源（最低 {price}）{hint}。"
    if stage == "listing":
        if update.get("listing_path"):
            return f"✓ 日文上架素材已生成：{update['listing_path']}"
        return None
    return None


def _product_with_lifecycle(p: Product) -> dict:
    """竞品序列化时附加生命周期字段（规则引擎真实评论时间驱动）。"""
    d = p.model_dump()
    from tiktok_ecommerce.services.lifecycle import analyze_lifecycle
    ins = analyze_lifecycle(p)
    if ins.stage:
        d["lifecycle_stage"] = ins.stage
        d["lifecycle_trend"] = ins.trend
        d["lifecycle_confidence"] = ins.confidence
        d["lifecycle_window"] = ins.window_advice
    return d


def _build_selection_reply(result: dict[str, Any], product: str,
                           region: str) -> tuple[str, dict[str, Any]]:
    """把流水线结果组装成（回复文本, 结构化数据），供同步/流式聊天共用。"""
    report = result.get("report")
    offers = result.get("offers") or []
    products = result.get("products") or []
    listing_path = result.get("listing_path") or ""

    lines = [f"帮你分析了「{product}」（{region}站）："]
    if products:
        lowest = min((p.price_value for p in products), default=0)
        lines.append(f"· 采集到 {len(products)} 个真实竞品，最低 ¥{lowest}")
    elif result.get("filtered_note"):
        # 品类过滤后为空：如实说明，不把非家纺商品当结果
        lines.append("· " + result["filtered_note"])
    if report:
        summary = getattr(report, "summary", None) or str(report)[:120]
        suggestion = getattr(report, "suggestion", "")
        lines.append(f"· 结论：{summary}")
        if suggestion:
            lines.append(f"· 建议：{suggestion[:120]}")
    if offers:
        top = offers[0]
        label = (top.score_breakdown or {}).get("visual_label")
        img_hint = f"（已用商品图匹配，Top1 视觉：{label}）" if label else ""
        lines.append(f"· 匹配到 {len(offers)} 条真实货源，最低 {top.price} {img_hint}")
    if listing_path:
        lines.append(f"· 日文上架素材已生成：{listing_path}")
    data = {
        "products": [_product_with_lifecycle(p) for p in products[:5]],
        "report": report.model_dump() if report else None,
        "offers": [o.model_dump() for o in offers[:6]],
        "listing_path": listing_path,
        "filtered_note": result.get("filtered_note"),
    }
    # 决策增强：推荐评分 / 市场价位分布 / 关键词建议（与工作台口径一致）
    from tiktok_ecommerce.services.keyword_mining import extract_keyword_insights
    from tiktok_ecommerce.services.market import build_market_overview
    from tiktok_ecommerce.services.scoring import compute_selection_score
    from tiktok_ecommerce.services.lifecycle import aggregate_competitors
    if not result.get("error"):
        data["score"] = compute_selection_score(result)
        data["market_overview"] = build_market_overview(products)
        data["keyword_insights"] = extract_keyword_insights(result, "bedding", query=product)
        # 生命周期/跟卖窗口（真实评论时间序列驱动，市面项目对标点）
        data["lifecycle"] = aggregate_competitors(products)
        lc_summary = data["lifecycle"].get("summary", "")
        if lc_summary and lc_summary != "评论时间数据不足，无法判断阶段分布":
            lines.append(f"· 生命周期：{lc_summary}")
    return "\n".join(lines), data
