"""HTTP 基础设施：带重试、限速、UA 轮换、代理支持的会话。

企业级要点：
- tenacity 指数退避重试，只对"可重试的网络异常"重试（分层：内层重试原始异常，外层统一转 CrawlerError）
- 令牌桶限速 + 随机抖动，礼貌抓取，降低被风控识别概率
- User-Agent 轮换、可选代理（日本站需海外/住宅代理）
- 统一超时与请求头，同时支持 HTML 与 JSON 接口（第三方数据 API）
"""
from __future__ import annotations

import random
import time
from threading import Lock
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tiktok_ecommerce.common.exceptions import CrawlerError

# 常见桌面浏览器 UA 池（轮换降低指纹一致性）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]


class RateLimiter:
    """令牌桶限速器：相邻请求间隔 min_interval + 随机抖动（模拟真人节奏）。"""

    def __init__(self, min_interval: float = 3.0, jitter: float = 0.8):
        self.min_interval = min_interval
        self.jitter = jitter
        self._last: float = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            target = self.min_interval + random.uniform(0, self.jitter)
            delta = now - self._last
            if delta < target:
                time.sleep(target - delta)
            self._last = time.monotonic()


class HttpClient:
    """统一 HTTP 客户端（HTML / JSON 通用）。"""

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: int = 10,
        min_interval: float = 3.0,
        max_retries: int = 3,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(min_interval)
        self._extra_headers = headers or {}
        if user_agent:
            self.session.headers.update({"User-Agent": user_agent})
        if proxy:
            # 形如 http://user:pass@host:port 或 http://host:port
            self.session.proxies.update({"http": proxy, "https": proxy})

    def _build_headers(self, referer: str | None) -> dict[str, str]:
        """每次请求轮换 UA，可附带 Referer / 鉴权头。"""
        headers = dict(self._extra_headers)
        # 未在额外头里显式指定 UA 时轮换
        if "User-Agent" not in headers:
            headers["User-Agent"] = random.choice(USER_AGENTS)
        if referer:
            headers["Referer"] = referer
        return headers

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _do_request(
        self, method: str, url: str, *,
        params: dict | None = None,
        json_body: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """内层：只负责发请求与重试，抛出原始 RequestException 供 tenacity 判定。"""
        self.limiter.wait()
        return self.session.request(
            method, url,
            params=params,
            json=json_body,
            data=data,
            files=files,
            headers=headers,
            timeout=self.timeout,
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """外层：统一状态码检查与异常转换（CrawlerError 不参与重试）。"""
        try:
            resp = self._do_request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            raise CrawlerError(
                f"请求失败({status}): {url}", detail=str(e)
            ) from e

    @staticmethod
    def _decode_text(resp: requests.Response) -> str:
        """响应文本解码（中文站点编码探测）。

        背景：部分中文站点（如 91家纺）响应头不带 charset，requests 默认按
        ISO-8859-1 解码，中文全部乱码。这里做两层兜底：
        - 响应头已声明 charset（非 latin-1）→ 用 requests 解码结果
        - 否则按 utf-8 → gb18030 顺序探测字节（91家纺=UTF-8，1688 类站点=GBK）
        """
        declared = (resp.encoding or "").lower()
        if declared and declared != "iso-8859-1":
            return resp.text
        raw = resp.content
        for enc in ("utf-8", "gb18030"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return resp.text  # 实在无法探测则退回 requests 默认

    def get(self, url: str, *, params: dict | None = None,
            referer: str | None = None) -> str:
        """GET 页面，返回 HTML 文本（中文站点自动做编码探测）。"""
        resp = self._request(
            "GET", url, params=params, headers=self._build_headers(referer)
        )
        return self._decode_text(resp)

    def get_json(
        self, url: str, *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict | None = None,
        method: str = "GET",
    ) -> dict:
        """请求 JSON 接口（第三方数据 API / 官方 API 通用），返回 dict。"""
        merged = self._build_headers(None)
        if headers:
            merged.update(headers)
        resp = self._request(
            method, url, params=params, json_body=json_body, headers=merged
        )
        try:
            return resp.json()
        except ValueError as e:
            raise CrawlerError(f"响应不是合法 JSON: {url}", detail=resp.text[:200]) from e

    def post_file(
        self, url: str, *,
        files: dict,
        data: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        """multipart/form-data 上传文件（如 RAGFlow 上传文档）。

        files 例：{"file": ("doc.md", b"...", "text/markdown")}
        注意：不显式设置 Content-Type，交由 requests 自动生成 boundary。
        """
        merged = self._build_headers(None)
        merged.pop("Content-Type", None)
        if headers:
            merged.update(headers)
        resp = self._request("POST", url, data=data, files=files, headers=merged)
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}
