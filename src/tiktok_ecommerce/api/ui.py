"""Web 选择页面：品类按钮 + 流程阶段勾选 + 一键运行选品。

- GET /                → 选择页面（HTML）
- GET /api/v1/categories → 品类列表（页面加载时拉取，自动渲染按钮）

设计动机：演示时直接在浏览器点按钮选品类（床上用品/电子/服装），
勾选要跑的阶段，输入商品关键词即可触发全链路流水线 —— 直观展示"可扩展品类体系"。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from tiktok_ecommerce.categories.registry import list_categories

router = APIRouter()

PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TikTok 跨境选品 Agent - 控制台</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Microsoft YaHei', -apple-system, sans-serif; background: #f0f4f8; color: #1f2937; padding: 24px; }
  .wrap { max-width: 860px; margin: 0 auto; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .sub { color: #6b7280; font-size: 14px; margin-bottom: 24px; }
  .card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 16px; }
  .card h2 { font-size: 15px; color: #374151; margin-bottom: 12px; }
  .btn-group { display: flex; flex-wrap: wrap; gap: 10px; }
  .cat-btn { border: 2px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 12px 16px; cursor: pointer; font-size: 14px; text-align: left; min-width: 170px; transition: all .15s; }
  .cat-btn.active { border-color: #2563eb; background: #eff6ff; }
  .cat-btn .name { font-weight: 700; }
  .cat-btn .desc { color: #6b7280; font-size: 12px; margin-top: 4px; }
  .chk { display: inline-flex; align-items: center; gap: 6px; margin-right: 16px; font-size: 14px; }
  .chk input { width: 16px; height: 16px; }
  .field { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .field label { display: block; font-size: 13px; color: #6b7280; margin-bottom: 4px; }
  .field input, .field select { padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; min-width: 200px; }
  .run-btn { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 24px; font-size: 15px; cursor: pointer; }
  .run-btn:disabled { background: #93c5fd; cursor: not-allowed; }
  #result { white-space: pre-wrap; background: #111827; color: #d1fae5; border-radius: 8px; padding: 16px; font-size: 13px; max-height: 420px; overflow: auto; display: none; }
  .tip { font-size: 12px; color: #9ca3af; margin-top: 8px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>TikTok 跨境选品 Agent · 控制台</h1>
  <div class="sub">基于多 Agent 流水线：采集竞品 → RAG 分析 → 货源匹配 → 上架素材（主推：床上用品 · 日本站日语文案）</div>

  <div class="card">
    <h2>① 选择品类</h2>
    <div class="btn-group" id="categoryBtns"></div>
  </div>

  <div class="card">
    <h2>② 选择流程阶段</h2>
    <div id="stageChecks">
      <label class="chk"><input type="checkbox" value="crawler" checked> 采集竞品</label>
      <label class="chk"><input type="checkbox" value="analyzer" checked> 商品分析</label>
      <label class="chk"><input type="checkbox" value="sourcing" checked> 货源匹配</label>
      <label class="chk"><input type="checkbox" value="listing" checked> 上架素材</label>
    </div>
    <div class="tip">只勾选需要的阶段，流水线自动裁剪（如只跑「分析」可跳过采集）</div>
  </div>

  <div class="card">
    <h2>③ 输入商品信息</h2>
    <div class="field">
      <div><label>商品关键词 / 链接</label><input id="product" value="純棉 ボックスシーツ 1.8m" style="min-width:260px;"></div>
      <div><label>目标市场</label>
        <select id="region">
          <option value="JP" selected>日本 JP</option>
          <option value="US">美国 US</option>
          <option value="UK">欧洲 UK</option>
        </select>
      </div>
      <div><label>上架文案语言</label>
        <select id="language">
          <option value="ja" selected>日本語（默认·日本站）</option>
          <option value="en">English 英语</option>
          <option value="es">Español 西语</option>
          <option value="fr">Français 法语</option>
          <option value="de">Deutsch 德语</option>
          <option value="ko">한국어 韩语</option>
        </select>
      </div>
      <div><button class="run-btn" id="runBtn">运行流水线</button></div>
    </div>
  </div>

  <div class="card" style="display:none" id="resultCard">
    <h2>运行结果</h2>
    <div id="result"></div>
  </div>
</div>

<script>
(function () {
  "use strict";
  var categories = [];
  var selectedCategory = "bedding";

  function loadCategories() {
    fetch("/api/v1/categories").then(function (r) { return r.json(); }).then(function (list) {
      categories = list;
      var box = document.getElementById("categoryBtns");
      box.innerHTML = "";
      list.forEach(function (c) {
        var btn = document.createElement("button");
        btn.className = "cat-btn" + (c.name === selectedCategory ? " active" : "");
        btn.dataset.name = c.name;
        btn.innerHTML = '<div class="name">' + c.display_name + '</div><div class="desc">' + c.description + '</div>';
        btn.onclick = function () {
          selectedCategory = c.name;
          document.querySelectorAll(".cat-btn").forEach(function (b) { b.classList.remove("active"); });
          btn.classList.add("active");
        };
        box.appendChild(btn);
      });
    });
  }

  function collectStages() {
    return Array.prototype.filter.call(
      document.querySelectorAll("#stageChecks input:checked"),
      function (el) { return el.checked; }
    ).map(function (el) { return el.value; });
  }

  document.getElementById("runBtn").onclick = function () {
    var btn = this;
    btn.disabled = true;
    btn.textContent = "运行中…";
    var payload = {
      product: document.getElementById("product").value,
      region: document.getElementById("region").value,
      category: selectedCategory,
      language: document.getElementById("language").value,
      stages: collectStages()
    };
    fetch("/api/v1/selections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); }).then(function (data) {
      var out = "品类: " + selectedCategory + " | 语言: " + document.getElementById("language").value + "\n\n";
      if (data.report) {
        out += "【选品评估】\n" + JSON.stringify(data.report, null, 2) + "\n";
      }
      if (data.offers && data.offers.length) {
        out += "\n【货源对比】\n" + data.offers.map(function (o) {
          return "  [" + o.match_score + "] " + o.title + " | " + o.price + " | " + o.min_order + " | " + o.delivery;
        }).join("\n") + "\n";
      }
      if (data.listing_path) { out += "\n【素材包】" + data.listing_path + "\n"; }
      if (data.error) { out += "\n【错误】" + data.error + "\n"; }
      document.getElementById("result").textContent = out;
      document.getElementById("resultCard").style.display = "block";
      btn.disabled = false;
      btn.textContent = "运行流水线";
    }).catch(function (err) {
      document.getElementById("result").textContent = "请求失败: " + err.message;
      document.getElementById("resultCard").style.display = "block";
      btn.disabled = false;
      btn.textContent = "运行流水线";
    });
  };

  loadCategories();
})();
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """选择页面。"""
    return HTMLResponse(PAGE_HTML)


@router.get("/categories")
def categories() -> list[dict[str, str]]:
    """可用品类列表。"""
    return list_categories()
