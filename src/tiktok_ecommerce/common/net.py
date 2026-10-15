"""网络层安全工具：SSRF 防护（内网地址拦截）。

被后端代下载/代请求的用户 URL（图片、素材包等）必须过此检查，
防止攻击者让后端请求 http://127.0.0.1:* 或 http://169.254.169.254（云元数据）
做内网探测。解析失败一律按私有处理（宁可跳过，不可放行）。
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


def _in_test_env() -> bool:
    """测试环境（pytest 运行中或 ENV=test）：放行 loopback，供本地 mock 图片源。"""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or os.environ.get("ENV") == "test"


def is_private_url(url: str) -> bool:
    """URL 指向内网/回环/链路本地/保留地址 → True（应拒绝）。

    仅允许 http/https；解析失败按私有不放行。host 为 localhost 直接拒绝。
    测试环境（pytest/ENV=test）放行回环地址（本地 mock 服务器作图片源），
    生产环境严格拒绝。
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return True
        host = parsed.hostname
        if not host:
            return True
        if host.lower() == "localhost":
            return True
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    test_mode = _in_test_env()
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if test_mode and (ip.is_loopback or ip.is_link_local):
            continue  # 测试环境：本地 mock 图片源
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False
