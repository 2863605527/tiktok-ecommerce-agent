<script setup lang="ts">
import { ref } from 'vue'
import { useSelectionStore } from '@/stores/selection'
import { businessApi } from '@/api/business'
import type { DiagnosticsResult } from '@/api/types'
import { useToastStore } from '@/stores/toast'

const store = useSelectionStore()
const toast = useToastStore()

// ---- 一键诊断：真实数据源连通性（SocialCrawl/Milvus/找家纺/LLM） ----
const diagnosing = ref(false)
const diag = ref<DiagnosticsResult | null>(null)

async function runDiag() {
  diagnosing.value = true
  diag.value = null
  try {
    diag.value = await businessApi.runDiagnostics()
    toast.info(`诊断完成：${diag.value.summary}`)
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '诊断调用失败')
  } finally {
    diagnosing.value = false
  }
}
</script>

<template>
  <div class="about">
    <section class="card">
      <h2>当前运行配置</h2>
      <table class="cfg" v-if="store.config">
        <tbody>
          <tr>
            <td>商品数据源</td>
            <td>
              <code>{{ store.config.product_source }}</code>
              <span class="note">{{ store.config.product_source === 'socialcrawl' ? 'SocialCrawl（TikTok Shop 真实商品/评论，JP 站）' : store.config.product_source === 'api' ? 'FastMoss（真实 TikTok 商品/评论）' : '本地样本（离线兜底）' }}</span>
            </td>
          </tr>
          <tr>
            <td>SocialCrawl Key</td>
            <td>
              <span :style="{ color: store.config.has_socialcrawl_key ? 'var(--success)' : 'var(--warn)' }">
                {{ store.config.has_socialcrawl_key ? `已配置 ${store.config.socialcrawl_key_masked}` : '未配置' }}
              </span>
              <span class="note">搜索卡不返回销量字段（JP 小店无公开销量统计），以评分/评论数为热度参考</span>
            </td>
          </tr>
          <tr>
            <td>货源数据源</td>
            <td>
              <code>{{ store.config.supplier_source }}</code>
              <span class="note">{{ store.config.supplier_source === 'jiafang' ? '找家纺网（真实免费货源）' : '本地样本' }}</span>
            </td>
          </tr>
          <tr>
            <td>检索后端</td>
            <td><code>{{ store.config.rag_backend }}</code></td>
          </tr>
          <tr>
            <td>FastMoss Key</td>
            <td>
              <span :style="{ color: store.config.has_fastmoss_key ? 'var(--success)' : 'var(--warn)' }">
                {{ store.config.has_fastmoss_key ? `已配置 ${store.config.fastmoss_key_masked}` : '未配置（商品将使用本地样本）' }}
              </span>
            </td>
          </tr>
          <tr>
            <td>FastMoss 区域</td>
            <td><code>{{ store.config.fastmoss_region }}</code></td>
          </tr>
          <tr>
            <td>找家纺网</td>
            <td><code>{{ store.config.jiafang_base_url }}</code></td>
          </tr>
          <tr>
            <td>LLM / 向量模型</td>
            <td><code>{{ store.config.llm_model }}</code> / <code>{{ store.config.embedding_model }}</code></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="dim">未加载到配置，请确认后端已启动。</p>
    </section>

    <!-- 一键诊断：数据源连通性（第三轮） -->
    <section class="card">
      <h2>一键诊断（真实数据源连通性）
        <button class="diag-btn" :disabled="diagnosing" @click="runDiag">
          {{ diagnosing ? '诊断中…' : '运行诊断' }}
        </button>
      </h2>
      <p class="dim">逐项测试 SocialCrawl 商品源 / Milvus 向量库 / 找家纺网货源 / LLM，单项失败不阻塞其他项。</p>
      <div v-if="diag" class="diag-list">
        <div v-for="item in diag.items" :key="item.name" class="diag-item" :class="item.ok ? 'ok' : 'bad'">
          <span class="diag-dot">{{ item.ok ? '●' : '✕' }}</span>
          <span class="diag-name">{{ item.name }}</span>
          <span class="diag-detail">{{ item.detail }}</span>
        </div>
        <div class="diag-summary" :class="diag.all_ok ? 'ok' : 'bad'">
          {{ diag.summary }} · {{ diag.checked_at }}
        </div>
      </div>
      <p v-else class="dim">点击「运行诊断」检查各数据源是否可用。</p>
    </section>

    <section class="card">
      <h2>如何切换真实数据源</h2>
      <p>打开项目根目录 <code>.env</code> 文件，修改以下两行后重启后端：</p>
      <pre class="code"># 商品数据（TikTok 真实商品/评论）：
#   socialcrawl=SocialCrawl（新账号 100 credits 免费验证，搜索/评论支持 JP）
#   tikhub=TikHub（日常批量付费源，$0.001/次起，填 Key 即切换）
#   api=FastMoss（$0.01/次，需注册充值）
PRODUCT_SOURCE=socialcrawl
SOCIALCRAWL_API_KEY=你的SocialCrawlKey
# TIKHUB_API_KEY=你的TikHubKey

# 货源数据：找家纺网（真实免费货源，无需注册）
SUPPLIER_SOURCE=jiafang      # sample=本地样本 | jiafang=找家纺网 | direct=直连扩展</pre>
      <p class="dim">切换后运行 <code>python scripts/verify_data_source.py</code> 可一键验证真实连通性；或直接用上方「一键诊断」。</p>
    </section>

    <section class="card">
      <h2>流水线说明</h2>
      <table class="cfg">
        <tbody>
          <tr><td>采集竞品</td><td>搜索竞品商品，抽取标题/价格/销量/评论，写入向量库</td></tr>
          <tr><td>商品分析</td><td>检索向量库 → LLM 对评论做痛点/优点聚类，证据引用原文，防幻觉</td></tr>
          <tr><td>货源匹配</td><td>按关键词查找家纺网，六维打分（价格/代发/发货/主营/销量/标题）</td></tr>
          <tr><td>上架素材</td><td>生成目标语言（默认日语）标题/关键词/描述/规格翻译，导出 CSV</td></tr>
          <tr><td>决策增强</td><td>推荐评分（热度/口碑/货源/上架 4 维 0-100）、市场价位分布、关键词建议、单件利润测算</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.about {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
}

.card h2 {
  font-size: 15px;
  margin-bottom: 12px;
}

.cfg {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.cfg td {
  padding: 8px 10px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  vertical-align: top;
}

.cfg td:first-child {
  color: var(--text-dim);
  width: 180px;
  white-space: nowrap;
}

.note {
  margin-left: 10px;
  font-size: 12px;
  color: var(--text-dim);
}

.code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.8;
  margin: 10px 0;
  overflow-x: auto;
}

.dim {
  color: var(--text-dim);
  font-size: 12px;
}

/* ---- 一键诊断 ---- */
.diag-btn {
  margin-left: 12px;
  border: 1px solid var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: var(--radius-sm);
  padding: 5px 16px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
  vertical-align: middle;
}

.diag-btn:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}

.diag-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.diag-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diag-item {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-size: 12px;
  background: var(--bg);
}

.diag-item.ok .diag-dot {
  color: var(--success);
}

.diag-item.bad .diag-dot {
  color: var(--danger);
}

.diag-dot {
  flex: 0 0 auto;
  font-size: 12px;
}

.diag-name {
  flex: 0 0 150px;
  font-weight: 700;
  color: var(--text);
}

.diag-detail {
  color: var(--text-dim);
  word-break: break-all;
}

.diag-summary {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 700;
}

.diag-summary.ok { color: var(--success); }
.diag-summary.bad { color: var(--danger); }
</style>
