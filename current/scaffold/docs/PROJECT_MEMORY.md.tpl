# {{PROJECT_NAME}} 项目记忆摘要

> 本文件是面向 AI 的“温记忆”，用于快速恢复上下文，不替代完整需求、架构和历史文档。
> 只保存当前有效、跨批次仍重要的事实；采用覆盖式维护，不得按批次无限追加。

<!-- AUTO:PROJECT_MEMORY_STATUS:START -->
## 自动运行状态

- 更新时间：{{CREATED_DATE}}
- 当前阶段：项目探索与需求定义
- 活动批次：无
- 未关闭变更：0
- 当前优先级：建立需求基线
- 最近完整审计：尚无
<!-- AUTO:PROJECT_MEMORY_STATUS:END -->

## 1. 项目定位

- 项目名称：{{PROJECT_NAME}}
- 项目类型：{{PROFILE_LABEL}}
- 一句话目标：{{PROJECT_DESCRIPTION}}
- 目标用户：待与用户确认。
- 核心价值：待与用户确认。

## 2. 当前核心业务规则

- 待需求讨论确认后，由 AI 维护当前有效规则。
- 这里只保留跨模块、容易遗忘或会影响后续开发的规则。

## 3. 关键架构决定

- 待架构确认后填写关键技术边界。
- 完整架构细节以 `ARCHITECTURE.md` 为准。

## 4. 已确认禁止项与授权边界

- 高风险操作以 `PROJECT.toml` 为准。
- 待补充项目专属禁止项。

## 5. 最近重要需求变化

- 尚无。
- 仅保留仍会影响当前实现的少量变化；完整原因进入 `DECISIONS.md` / `decisions/`。

## 6. 当前重点与未决事项

- 与用户逐步确认产品形态、需求、架构和开发规划。

## 7. 权威文档导航

| 需要确认的信息 | 权威来源 |
|---|---|
| 当前需求 | `PRODUCT_REQUIREMENTS.md` |
| 需求修订历史 | `REQUIREMENT_CHANGELOG.md` |
| 需求与实现／测试追踪 | `REQUIREMENT_TRACEABILITY_MATRIX.md` |
| 验收口径 | `ACCEPTANCE_CRITERIA.md` |
| 当前架构 | `ARCHITECTURE.md` |
| 阶段和计划 | `DEVELOPMENT_PLAN.md` |
| 当前进展 | `CURRENT_STATE.md` |
| 决策原因 | `DECISIONS.md` / `decisions/` |
| 避坑规则 | `PITFALLS.md` |
| 客户交付与结案 | `DELIVERY_AND_CLOSURE.md` |
| 历史执行 | `logs/YYYY-MM.md` |

## 维护规则

1. 同一事实只能在一个权威文档中保存完整版本；本文件只做短摘要和导航。
2. 只有本文件跨任务摘要/引用实际受影响时才更新；需求和架构正文变更由派生索引刷新，不在这里复制正文。
3. 删除已经失效的摘要，不保留流水账。
4. 不超过 300 行或 30 KB；接近上限时压缩，而不是继续拆分摘要。
5. 同一对话窗口连续工作时主要依赖当前对话，只在本文件变化时增量读取。
