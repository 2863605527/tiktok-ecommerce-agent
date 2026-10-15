"""认证包：用户存储 + JWT 鉴权依赖。"""
from tiktok_ecommerce.auth.store import User, UserStore

__all__ = ["User", "UserStore"]
