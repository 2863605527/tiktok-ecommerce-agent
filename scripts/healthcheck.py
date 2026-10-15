"""第一步 · 环境连通性自检（企业级 healthcheck）。

逐项验证项目地基是否就绪，每一项都有明确 PASS / FAIL / WARN：
  1. 依赖是否安装（langchain 等）
  2. 配置是否加载（.env、API Key，脱敏回显）
  3. 数据/输出目录是否就绪
  4. 对话模型连通性（让模型用日语回复，顺带验证日本站场景）
  5. 向量化模型连通性（真实向量维度 vs Milvus 配置维度，不一致会埋坑，立即告警）

用法：
    python scripts/healthcheck.py

退出码：0 = 全部通过；1 = 存在失败项（按提示修复后重跑）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# 兼容"未 pip install -e"直接运行脚本：把 src 加入导入路径
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Windows 控制台/后台管道默认编码可能是 ASCII/GBK，打印日语/中文会直接崩溃，强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def _mask(key: str) -> str:
    """API Key 脱敏：只显示前 6 位和后 4 位。"""
    if not key:
        return "<空>"
    key = key.strip()
    if len(key) <= 12:
        return key[:3] + "***"
    return f"{key[:6]}...{key[-4:]}"


def main() -> int:
    print("=" * 64)
    print("  tiktok-ecommerce-agent · 第一步环境自检")
    print("=" * 64)

    failures: list[str] = []
    warnings: list[str] = []

    # ---------- 1. 依赖检查 ----------
    print("\n[1/5] 检查第三方依赖...")
    missing = []
    for mod in ("langchain_openai", "langgraph", "pymilvus", "fastapi", "pydantic_settings"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"  [FAIL] 缺少依赖: {', '.join(missing)}")
        print("         请先安装：pip install -e \".[dev]\"")
        return 1
    print("  [PASS] 核心依赖均已安装")

    # ---------- 2. 配置加载 ----------
    print("\n[2/5] 加载配置（.env）...")
    try:
        from tiktok_ecommerce.config import get_settings

        settings = get_settings()
    except Exception as e:  # 配置缺失/非法时 pydantic 会抛异常
        print("  [FAIL] 配置加载失败，通常是还没创建 .env 或没填 LLM_API_KEY")
        print(f"         错误: {e}")
        print("         操作: copy .env.example .env  然后用记事本打开填写 Key")
        return 1

    print(f"  [PASS] 对话模型   : {settings.llm.model}  @ {settings.llm.base_url}")
    print(f"         Key        : {_mask(settings.llm.api_key)}")
    print(f"  [PASS] 向量模型   : {settings.llm.embedding_model}  @ {settings.llm.emb_base_url}")
    print(f"         Key        : {_mask(settings.llm.emb_api_key)}")
    print(f"  [INFO] Milvus 维度配置: {settings.milvus.embedding_dim}（向量模型实际维度稍后校验）")

    # Key fail-fast 校验：占位符/中文 Key 会让 HTTP 认证头编码崩溃，提前拦截
    try:
        from tiktok_ecommerce.common.llm import _validate_api_key

        _validate_api_key(settings.llm.api_key, "对话模型 LLM")
        _validate_api_key(settings.llm.emb_api_key, "向量模型 EMBEDDING")
        print("  [PASS] 两个 API Key 均为真实格式（非占位符、纯英文）")
    except Exception as e:
        print(f"  [FAIL] {e.message if hasattr(e, 'message') else e}")
        print("         请用记事本打开 .env，把两个 Key 换成平台申请到的真实 sk- 串后重跑")
        return 1

    # ---------- 3. 目录检查 ----------
    print("\n[3/5] 检查数据/输出目录...")
    try:
        settings.ensure_dirs()
        print(f"  [PASS] 目录就绪: {settings.data_dir} / {settings.output_dir} / {settings.log_dir}")
    except Exception as e:
        print(f"  [FAIL] 目录创建失败: {e}")
        return 1

    # ---------- 4. 对话模型连通性（日语）----------
    print("\n[4/5] 测试对话模型（要求用日语回复，验证日本站场景）...")
    try:
        from tiktok_ecommerce.common.llm import create_llm

        t0 = time.perf_counter()
        llm = create_llm(settings)
        resp = llm.invoke(
            "あなたはTikTokショップの店舗運営者です。"
            "次の1文だけをそのまま日本語で出力してください："
            "「こんにちは、ご質問ありがとうございます。」"
        )
        dt = time.perf_counter() - t0
        reply = (resp.content or "").strip()
        print(f"  [PASS] 对话模型连通（{dt:.2f}s）")
        print(f"         模型回复: {reply}")
        if not any(k in reply for k in ("こんにちは", "ありがとう")):
            warnings.append("对话模型回复不像日语，请确认模型支持日语（DeepSeek/通义/Qwen 均支持）")
    except Exception as e:
        print(f"  [FAIL] 对话模型调用失败: {type(e).__name__}: {e}")
        print("         排查: Key 是否正确 / 是否充值 / BASE_URL 是否能访问")
        failures.append("对话模型")

    # ---------- 5. 向量化模型连通性 + 维度校验 ----------
    print("\n[5/5] 测试向量化模型（真实维度 vs Milvus 配置维度）...")
    actual_dim = None
    try:
        from tiktok_ecommerce.common.llm import create_embedding_fn

        t0 = time.perf_counter()
        embed = create_embedding_fn(settings)
        vec = embed("ボックスシーツ 綿100% オーガニックコットン")  # 日语家纺词
        dt = time.perf_counter() - t0
        actual_dim = len(vec)
        print(f"  [PASS] 向量模型连通（{dt:.2f}s），返回向量维度 = {actual_dim}")
        configured = settings.milvus.embedding_dim
        if actual_dim != configured:
            print(f"  [FAIL] 维度不一致！向量模型实际 {actual_dim} 维，但 MILVUS_EMBEDDING_DIM={configured}")
            print(f"         修复: 把 .env 里 MILVUS_EMBEDDING_DIM 改成 {actual_dim}，否则第四步入库必报错")
            failures.append("向量维度不一致")
        else:
            print(f"  [PASS] 维度与 Milvus 配置一致（{configured}），第四步可直接入库")
    except Exception as e:
        print(f"  [FAIL] 向量模型调用失败: {type(e).__name__}: {e}")
        print("         排查: 向量模型 Key/模型名是否正确（bge-m3 在硅基流动为 BAAI/bge-m3）")
        failures.append("向量模型")

    # ---------- 汇总 ----------
    print("\n" + "=" * 64)
    for w in warnings:
        print(f"  [WARN] {w}")
    if failures:
        print(f"  结果: 未通过（{len(failures)} 项失败: {', '.join(failures)}），按上面提示修复后重跑")
        print("=" * 64)
        return 1
    print("  结果: 全部通过 ✓  地基就绪，可以进入第二步（领域模型 + 单元测试）")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
