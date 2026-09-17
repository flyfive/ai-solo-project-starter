# {{PROJECT_NAME}}

{{PROJECT_DESCRIPTION}}

## 当前配置

- 项目类型：{{PROFILE_LABEL}}（`{{PROJECT_PROFILE}}`）
- 治理模式：{{GOVERNANCE_MODE_LABEL}}（`{{GOVERNANCE_MODE}}`）
- 模板版本：V1.9.0

任何项目角色先读取 `START_HERE.md`，再按当前治理模式接管。

## 共同项目资产

- 当前需求：`docs/PRODUCT_REQUIREMENTS.md`
- 验收标准：`docs/ACCEPTANCE_CRITERIA.md`
- 需求修订历史：`docs/REQUIREMENT_CHANGELOG.md`
- 需求追踪：`docs/REQUIREMENT_TRACEABILITY_MATRIX.md`
- 当前状态：`docs/CURRENT_STATE.md`
- 重要决定：`docs/DECISIONS.md`
- 历史执行：`docs/logs/YYYY-MM.md`

## Lite 极简治理

Lite 面向一至三天、单执行器、自用且没有正式交付的小项目。它保留需求编号、完整修订历史、验收、状态、决定、日志和 Git，但不启用并行执行、正式发布基线、客户交付和结案门禁。Lite 是轻量需求与执行规划，不等同于 Standard 的完整架构、阶段规划和正式交付文档。

项目变大时，由项目所有者授权，项目经理主智能体通过 `ai-promote-standard` 原地升级。若 Lite 批次已因复杂度增加而 `BLOCKED/PARTIAL`，先通过正式入口安全挂起。升级不会改变项目目录、Git、需求编号、需求历史或现有代码；升级后必须完成 Standard 基线审计，审计前禁止继续批次。

## Standard 标准治理

Standard 面向数周或数月、多模块、多阶段、多执行器或有正式交付目标的项目。除共同资产外，还启用角色边界、项目记忆、架构、开发计划、避坑、发布、交付、最终验收和结案规则。

## 共同稳定性规则

- 产品语义变化必须形成新需求修订，`link` 只能更新纯追踪证据；
- 声称完成的测试必须真实通过；
- 提交必须通过 Git Hook；
- 需求编号和历史不得因治理模式升级而改变；
- Standard 发布基线不可覆盖，已结案版本永久冻结；
- 交付物必须位于项目根目录内并按 SHA-256 验证。

## 任务字段与结束核对（按需）

建立/结束新契约任务或规则变化时读本节；保留原 goal/scope/acceptance_criteria/context_refs 与分层证据要求。调查不启动实现，复杂/含糊/高风险沿用原规划；先查事实，再集中询问重要未知。

task_contract：kind=small_change/planned，work_type=fix/feature/other，risk_reason，unchanged_behaviors，reference_paths（少量存在文件）或 no_reference_reason。small_change 不允许风险标记、授权需求、阶段跳转、并行/父批；不以行数判断风险。旧输入缺省无新增保障。

checks 以本批条件原文作键，fix 另有 original_symptom，feature 另有 entry_wiring；status=pass/fail/not_run。pass 给 details 与当前本批 ai-evidence summary 的 evidence，其他状态给 reason。缺证据不关闭；不扩张无关 AC、不倒改需求、不无限复核，人工验收独立。

## 排错字段（仅排错按需）

原 batch_result 的 debug_checkpoint：symptom、expected、hypothesis、next_check、evidence_refs；eliminated=[{cause,evidence_refs}]。reproduction=reproduced/not_reproduced（缺省）/environment_blocked；root_cause_status=unknown（缺省）/confirmed，confirmed 需 reproduced 与 root_cause_evidence；不代表机器证明根因。工具保存 evidence_hashes，原观察文件不得改写冒用。

PARTIAL/BLOCKED 保存中断进度，旧尝试留历史；接管只读最新摘要及引用，遵守阻塞优先级。未复现/环境故障不称已确认或已验证；诊断/修复/复测不拆三份文档/执行器。跨任务教训归已有 PITFALLS/Decision。

## 模板材料许可

复制的工具脚本和实质性模板部分采用 MIT，声明见 [NOTICE.template.txt](NOTICE.template.txt)。不替新增业务代码选择许可证，不覆盖已有 LICENSE；第三方材料遵守其适用许可。本节无需加入日常必读上下文，分发或核对来源时按需读取。
