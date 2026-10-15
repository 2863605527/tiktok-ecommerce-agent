# 架构设计

## 分层设计

| 层 | 职责 | 关键约束 |
|----|------|---------|
| Entry（CLI / API） | 用户入口，参数校验，结果展示 | 不写业务逻辑 |
| Pipeline（LangGraph） | Agent 编排、状态流转 | 只做编排，不实现业务 |
| Agents | 单 Agent 业务（采集/分析/货源/素材） | 依赖接口，不依赖具体实现 |
| Crawlers | 数据采集，输出 Pydantic 模型 | 数据必须真实，禁止编造 |
| RAG | 向量化、入库、检索、过滤 | 检索结果质量决定回答质量 |
| Services | 跨模块业务（落盘、格式化） | 复用而非重复 |
| Common | 日志/异常/LLM/文本 | 全项目统一标准 |

## 依赖方向

```
Entry → Pipeline → Agents → {Crawlers, RAG, Services}
                          ↘ Common / Models / Config
```

依赖只向内，禁止反向依赖；Common/Models/Config 被所有层依赖，但不得依赖上层。

## 数据流

```
用户输入(关键词/链接)
  → crawler_agent: 采集竞品商品+评论 → 清洗 → 向量库（知识库）
  → analyzer_agent: RAG 检索 → LLM 结构化评估 → SelectionReport
  → sourcing_agent: 报告关键词 → 爬货源 → 打分 → SupplierOffer[]
  → listing_agent: 生成文案 → 处理图片 → ListingPackage（素材包）
```

## 关键决策记录（ADR）

1. **向量库抽象接口**：`VectorStore` 协议，当前 Milvus 实现，未来可换 Chroma/ES，Agent 无感。
2. **配置用 pydantic-settings**：类型安全、环境变量覆盖、启动即校验，优于裸 yaml。
3. **日志 JSON 化**：便于采集到 ELK/Loki，结构化告警。
4. **异常统一体系**：AppError 基类 + 稳定错误码，API 层统一转换为 HTTP 错误结构。
5. **防幻觉三防线**：检索分数过滤 / prompt 只依据资料 / 货源数据只来自爬虫。

## 扩展点

- 新增 Agent：实现 `BaseAgent.run`，在 `SelectionPipeline` 注册节点
- 新增数据源：实现 `ProductCrawler` / `SupplierCrawler` 接口
- 换向量库：实现 `VectorStore` 接口
- 异步化：LangGraph 支持 async 节点，可改造为异步流水线
