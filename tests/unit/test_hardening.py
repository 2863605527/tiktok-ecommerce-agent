"""第三轮安全加固回归：货源多词聚合 / SSRF 拦截 / CSV 公式注入 / 登录限流。"""
from __future__ import annotations

import pytest


# ---------- 找家纺多词聚合（修复：搜"牛奶绒床笠 四件套"只出床笠） ----------

def _fake_offer(title: str, price: str = "¥14.00", supplier: str = "安绮"):
    from tiktok_ecommerce.models.supplier import SupplierOffer
    return SupplierOffer(title=title, price=price, min_order="", delivery="",
                         supplier_name=supplier, url="", images=[])


def test_search_offers_aggregates_all_keywords(monkeypatch):
    """多词输入时逐词搜索并聚合（不再第一个词命中即停）。"""
    from tiktok_ecommerce.crawlers import zhaojiafang as zj

    calls: list[str] = []
    def fake_search_one(self, keyword: str):
        calls.append(keyword)
        if "牛奶绒床笠" in keyword:
            return [_fake_offer("2026新款牛奶绒床笠 90*200cm 单床笠"),
                    _fake_offer("牛奶绒床笠四件套 法兰绒保暖")]  # 含目标词
        if "四件套" in keyword:
            return [_fake_offer("牛奶绒四件套 床单被套加厚保暖")]
        return []

    monkeypatch.setattr(zj.ZhaojiafangSupplierCrawler, "_search_one", fake_search_one)
    crawler = zj.ZhaojiafangSupplierCrawler.__new__(zj.ZhaojiafangSupplierCrawler)
    crawler.client = None
    offers = crawler.search_offers(["牛奶绒床笠", "四件套"], top_n=6)
    assert len(offers) == 3  # 两个词都搜到并聚合
    assert "四件套" in calls  # 关键：第二个词确实被搜索了


def test_search_offers_ranks_target_word_first(monkeypatch):
    """命中目标词（四件套）的货源排最前。"""
    from tiktok_ecommerce.crawlers import zhaojiafang as zj

    def fake_search_one(self, keyword: str):
        if "四件套" in keyword:
            return [_fake_offer("牛奶绒四件套 全棉床单被套")]
        return [_fake_offer("2026新款牛奶绒床笠 单床笠"),
                _fake_offer("纯棉床笠 高密针织")]

    monkeypatch.setattr(zj.ZhaojiafangSupplierCrawler, "_search_one", fake_search_one)
    crawler = zj.ZhaojiafangSupplierCrawler.__new__(zj.ZhaojiafangSupplierCrawler)
    crawler.client = None
    offers = crawler.search_offers(["牛奶绒床笠", "四件套"], top_n=6)
    assert "四件套" in offers[0].title
    assert "床笠" in offers[1].title or "床笠" in offers[2].title


# ---------- 素材打包 SSRF 拦截 ----------

def test_is_private_url_blocks_internal():
    from tiktok_ecommerce.api.v1.listings import _is_private_url
    # 私有网段（任何模式都拦）：10.* / 192.168.* / 172.16-31.*
    assert _is_private_url("http://10.0.0.1/x")
    assert _is_private_url("http://192.168.1.1/x")
    assert _is_private_url("http://172.16.0.1/x")
    # localhost 按 host 名直接拒绝（测试模式同样生效）
    assert _is_private_url("http://localhost/admin")
    # 公网域名放行
    assert not _is_private_url("http://imgniu.zhaojiafang.com/store/goods/1.jpg")
    assert not _is_private_url("https://p16-sign.tiktokcdn-us.com/ok.png")


# ---------- CSV 公式注入防护 ----------

def test_csv_safe_escapes_formula_prefix():
    from tiktok_ecommerce.api.v1.listings import _csv_safe
    assert _csv_safe("=SUM(A1:A9)").startswith("'")
    assert _csv_safe("+1234").startswith("'")
    assert _csv_safe("-1; DROP TABLE").startswith("'")
    assert _csv_safe("@cmd").startswith("'")
    assert _csv_safe("牛奶绒床笠") == "牛奶绒床笠"  # 正常内容不动


# ---------- 登录限流 ----------

def test_login_throttle_locks_after_failures():
    from tiktok_ecommerce.api.v1 import auth as auth_mod
    auth_mod._LOGIN_ATTEMPTS.clear()
    for _ in range(5):
        auth_mod._record_login_failure("demo@x.com", "1.2.3.4")
    with pytest.raises(Exception):
        auth_mod._check_login_throttle("demo@x.com", "1.2.3.4")
    # 其他 IP 不受影响
    auth_mod._check_login_throttle("demo@x.com", "5.6.7.8")
    auth_mod._record_login_success("demo@x.com", "5.6.7.8")


def test_login_throttle_success_resets():
    from tiktok_ecommerce.api.v1 import auth as auth_mod
    auth_mod._LOGIN_ATTEMPTS.clear()
    for _ in range(3):
        auth_mod._record_login_failure("u", "ip")
    auth_mod._record_login_success("u", "ip")
    auth_mod._check_login_throttle("u", "ip")  # 不抛错
