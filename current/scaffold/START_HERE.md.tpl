# {{PROJECT_NAME}}：项目接管入口

这是任何项目角色接管本项目时的唯一入口。本项目不绑定具体软件、模型、平台或品牌。

## 项目概览

- 项目：{{PROJECT_NAME}}
- 类型：{{PROFILE_LABEL}}（`{{PROJECT_PROFILE}}`）
- 治理模式：{{GOVERNANCE_MODE_LABEL}}（`{{GOVERNANCE_MODE}}`）
- 选择依据：{{GOVERNANCE_REASON}}
- 简介：{{PROJECT_DESCRIPTION}}
- 创建日期：{{CREATED_DATE}}

## 第一步：确认模式与角色

默认只读 Hot Context：

1. 本文件的项目概览与 `AGENTS.md` 简短规则；
2. `docs/CURRENT_STATE.md` 当前事实；
3. 由当前角色执行 `ai-resume` 生成的 `.ai/runtime/context.json`（CONTEXT_LOAD_MANIFEST），含唯一活动批次、选定索引及读取边界。

接管者必须声明项目所有者、项目经理主智能体（PM）、审核/分析、代码执行器或集成审核角色。首次承担角色或规则改变时读取 `PROJECT.toml`、Standard 的 `docs/ROLE_BOUNDARIES.md` 和 `.ai/AUTOMATION_CONTRACT.md`。普通任务按 manifest 精确加载 R/AC、Cxx、DEC 正文与代码；不默认全文读取需求、架构、决定、日志、旧验收和测试原始输出。

Standard 的详细协议见 `docs/CONTEXT_LOADING_PROTOCOL.md`，执行规则见 `docs/AI_EXECUTION_RULES.md`。工具可校验完整文件，但送入 AI 的只有本任务必需内容。

## Lite 模式接管

Lite 只保留小项目最需要的事实：

- 当前需求：`docs/PRODUCT_REQUIREMENTS.md`
- 验收条件：`docs/ACCEPTANCE_CRITERIA.md`
- 需求历史：`docs/REQUIREMENT_CHANGELOG.md`
- 追踪证据：`docs/REQUIREMENT_TRACEABILITY_MATRIX.md`
- 当前状态：`docs/CURRENT_STATE.md`
- 重要决定：`docs/DECISIONS.md`
- 历史执行：`docs/logs/YYYY-MM.md`

Lite 默认单执行器顺序开发，不启用正式发布、交付和结案门禁。它提供轻量需求与执行规划，不等同于 Standard 的完整架构、阶段规划和正式交付文档。需求仍必须使用 `R-NNN.n`，语义变化仍必须保存完整历史。

出现以下任一情况时，项目经理主智能体应建议项目所有者升级 Standard：

- 项目进入多阶段或预计持续数周；
- 需要并行代码执行；
- 需要正式客户交付或多个发布版本；
- 出现复杂架构、部署、敏感数据或高风险操作；
- 正式需求达到六项以上；
- 需要角色边界、完整审计或长期维护。

正常情况下升级前先完成活动批次和未关闭变更。若活动批次已因项目复杂度上升如实记录为 `BLOCKED` 或 `PARTIAL`，可由项目所有者授权，通过安全挂起入口保留未完成内容、测试状态、变更和 Git 指纹，再继续升级；禁止伪造 PASS 或手工删除运行状态。

升级只激活文档和门禁，不改变原 Git、需求编号、历史或代码。升级后必须根据当前代码和需求补全架构、开发计划与项目记忆，并完成一次 Standard 基线审计；审计通过前禁止继续批次，挂起的原批次会在审计通过后自动恢复。

## Standard 模式接管

按最低够用的上下文级别恢复：

### 连续工作

1. 使用当前对话记忆；
2. 读取 `docs/CURRENT_STATE.md` 与当前 manifest；
3. 检查活动批次和未关闭变更；
4. 只读取当前任务相关文档或 Git diff。

### 新窗口

1. 读取角色边界和自动化契约；
2. 读取当前状态和活动批次摘要；
3. 检查需求版本、活动批次、未关闭变更和 Git；
4. 按任务读取需求、验收、架构、规划或代码。

### 完整审计

仅在首次建立基线、阶段/正式发布审计、架构重构、严重事实冲突或所有者要求时执行。审核全部当前事实文档，记录冲突、解决结果和项目经理复核，通过后才进入下一阶段。

## 固定恢复优先级

1. 项目已结案：只允许查询、审计或在所有者授权后显式重开；
2. Standard 升级基线待审计：先补全和审核架构、计划、记忆及当前实现；
3. 已登记但未完成文档写回的变更：先完成文档；
4. 其他未关闭变更：完成实现、测试和重新验收；
5. 活动批次：继续当前批次；
6. 无未完成事项：按当前需求和计划继续。

## 长期记忆原则

- 当前对话负责高效连续工作；
- 当前状态负责快速恢复；
- 需求登记表和生成文档负责完整语义历史；
- Standard 的项目记忆负责低成本跨窗口接管；
- Git diff 和哈希负责识别变化；
- 完整历史按需检索，不默认加载。

聊天记录不是最终权威来源。用户反馈改变产品行为时，必须先登记和修订需求，再修改实现和测试。

## 项目类型提醒

{{PROFILE_GUIDANCE}}

建议按需扩展文档：{{PROFILE_SUGGESTED_DOCS}}

## 用户只需要说

```text
读取 START_HERE.md，按当前治理模式和正确角色接管并继续。
```
