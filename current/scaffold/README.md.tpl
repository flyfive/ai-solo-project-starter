# {{PROJECT_NAME}}

{{PROJECT_DESCRIPTION}}

## 当前配置

- 项目类型：{{PROFILE_LABEL}}（`{{PROJECT_PROFILE}}`）
- 治理模式：{{GOVERNANCE_MODE_LABEL}}（`{{GOVERNANCE_MODE}}`）
- 模板版本：V1.9.1

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

## 测试设施合同（V1.9.1，按需）

新 planned / 高风险 / L3+ 测试任务采用 acceptance/1 的结构化 coverage；简单任务按风险选择。兼容的旧输入没有这些新增保证，不得借兼容路径规避已经声明的新合同。L1-L5 描述测试范围，evidence_kind 描述证据性质，两者不能互相代替。

四层职责：Candidate 是被测实现；Acceptance Contract 是本次授权、允许代码清单及验收要求；Harness 负责环境、进程、故障与采集；Auditor 只读核对证据。Candidate 不得硬编码本次 run_id、approval_id、报告目录、contractHash 或 expected evidence path。冻结 Candidate 不冻结 Harness/Contract。仅测试设施/审核语义合法改变且候选及产品/安全语义不变时，contract revision ≠ candidate revision，不得制造假代码 revision。产品/安全语义改变仍走原 Change/revise、授权和回归。

PM 把合同保存在项目内任务相关位置。批次请求用 `acceptance_contract` 引用这个相对 JSON 文件；合同 coverage 的 criterion_id 覆盖本批 acceptance_criteria/required_checks，以及 fix 的 original_symptom 或 feature 的 entry_wiring。不强迫纳入关联需求的全部 AC。修改合同后需原文档优先检查和 PM 的 ai-context refresh --accept-changes 重新审阅；新 hash 使旧 PASS 不能关闭新合同批次。

合同 schema=acceptance/1，字段如下（JSON 对象；工具内部维护，不给用户增加表单）：

- revision、approval_id、acceptance_rule_version；authorization={granted:true,note:既有授权依据}。
- candidate={revision,files:[{path,sha256}],entrypoint,capabilities:[]}。files 明确覆盖全部实际实现文件，不许故意遗漏；entrypoint 必须位于清单内。
- harness={revision,files:[{path,sha256}],entrypoint,executable,executable_sha256,supported_schema:["acceptance/1"],argv:[executable,entrypoint,...]}。executable 是规范绝对解释器路径（例如 Path(sys.executable).resolve()），path/entrypoint 是项目相对路径。候选和 Harness 清单分开。
- required_capabilities、participants（非空数组）、timeout_seconds（1–3600）。product_or_safety_semantics_changed=true 要求候选变更；compatibility_decision=incompatible 显式拒绝。能力清单及语义是否改变须审核，不是机器推断。
- coverage=[{criterion_id,requirement,required_evidence_kind,actual_entrypoint,actual_participants}]。required_evidence_kind 为 static/model/runtime/integration/manual/simulation/browser/external-system 之一；actual_entrypoint 必须属于已核验清单。可选 planned_evidence_kind 不得与所需类型冲突。

用既有 `ai-evidence --input <request.json>`，请求包含 actor_role、level、action=preflight/run、run_id、acceptance_contract（合同对象），可选 purpose=batch/stage/release。preflight 只读检查，不启动进程、不创建证据目录；正式 run 内再次 preflight。run_id 只出现在运行请求与独立运行身份中，不参与合同 hash。新合同/新 run 均不得覆盖旧目录。

Preflight 比较 capability/schema，返回 compatible_without_candidate_change、requires_harness_change、requires_candidate_change 或 incompatible。检查规范路径、实际 bytes SHA-256、regular file、清单、启动目标、链接/reparse/路径逃逸、授权依据、所需入口、coverage、输出目录不复用及基本写权限。默认 mtime/atime 不参与身份；只有 volatile_identity=[{path,field:"directory_mtime_ns",expected,reason}] 明确声明才升级为硬门。该权限检查不是操作系统沙箱，不保证后续环境不变或消除 TOCTOU。

Harness 通过环境变量 AI_ACCEPTANCE_CONTRACT 读取冻结合同副本，AI_EVIDENCE_DIR 取得本次输出目录，AI_EVIDENCE_RUN_ID 取得独立 run。不得把它们写回 Candidate。Harness 在输出目录生成 runtime-result.json：

```json
{"candidate_runtime_status":"PASS","coverage":[{"criterion_id":"G1","evidence_kind":"runtime","actual_entrypoint":"candidate.py","actual_participants":["worker"],"actual_evidence":["candidate.log"],"status":"pass"}]}
```

这只是结构例子，不是证据。必须真正运行入口，并保存 candidate.log 等原始输出；不可用 bool、literal object 或 model-only assertion 冒充 runtime。工具验证实际捕获进程、类型精确匹配、入口/参与者与原始非空文件引用。static/model PASS 不能满足 runtime-required；summary/合同本身不能代替执行日志。Harness 必须如实报告，工具不能证明其内部语义或阻止有文件权限者伪造内容。manual 类型还需合同中的 manual_acceptance={actor_role:"project_owner",approved:true} 及真实原始反馈；仍不能代替原批次/阶段人工验收流程。

工具分别冻结 candidate_revision/source_hash、acceptance_contract_revision/hash、harness_revision/source_hash、evidence_run_id；保存 contract.json、stdout/stderr、runtime-result.json、runtime.json、summary.json。运行原件与审核结果分开；action=audit、summary=原摘要路径只重读原运行，追加 audit-*.json 和可由正常 ai-finish evidence_refs 消费的 summary-audit-*.json，不再次启动 Harness。新摘要绑定原 candidate/harness/contract/run、runtime/raw 哈希、原失败摘要和新审计文件，保留原批次、测试级别及上下文；原摘要、运行和历史审计逐字节保留。缺失绑定、原件篡改或审计失败均不能完成验收。外部审核工具自身崩溃可用 auditor_error 记录实际错误，分类 AUDITOR_FAILURE，不改运行 PASS/FAIL。不得把旧 PASS 搬到新合同；新合同必须新 run。

失败分类：CANDIDATE_FAILURE、HARNESS_FAILURE、AUDITOR_FAILURE、ENVIRONMENT_BLOCKED、CONTRACT_INCOMPATIBLE、EVIDENCE_INSUFFICIENT。NOT_RUN 表示有可靠依据确认候选未启动（例如 preflight 拒绝或 Harness 启动前失败）；Harness 已启动但报告缺失、损坏或与退出状态冲突时记 UNKNOWN，不能把未证实运行写成确定未运行。扫描器缺依赖属于 Harness；审计崩溃不得覆盖已有 runtime 结果。所有失败/阻塞原件保留，成功只返回简短摘要和路径，原日志按需读。

Harness 退出/报告约定：退出 0 表示报告正常完成，候选仍可明确报告 FAIL；退出 1 仅在报告为 FAIL、coverage 有失败项、harness_status="completed" 且无设施错误时表示 CANDIDATE_FAILURE。退出码至少为 2 或信号退出、harness_status="failed"、实际采集错误均属于 HARNESS_FAILURE，不能由候选失败声明覆盖。缺失/损坏/冲突报告保留原文、真实退出码和已有原始文件，候选状态 UNKNOWN；有效候选 FAIL 与设施错误分开记录。报告声明 NOT_RUN 时，若 Harness 已启动，须 harness_status="failed" 并用 not_run_evidence 引用本次目录内非空的启动前失败日志；合同或报告自身不能充当该依据。这里信任经审查 Harness 的如实报告，不提供系统级启动监控或语义证明。历史 NOT_RUN 记录不回写，也不能据新约定推断旧记录已经证明未启动。

## 调查止损与范围决定（仅调查/范围变化时读取）

复用 `ai-context investigation --path <request.json>`；无需启动实现批次。action=start、actor_role=project_manager_agent、investigation_id、risk_level；可选正整数 max_iterations、max_candidate_revisions、max_failed_gates、owner_review_after，高风险至少一项。scope_expansion_forbidden 缺省 true，不表示 false 能授予新权限。一个活动调查保存在原 runtime 区，历史进入原 history 区；不创建第二业务批次。

action=record 保存现有格式 debug_checkpoint，可选 candidate 清单、failed_gate_evidence（失败 summary 路径）；外部调查尝试必须如实登记。每次新协议运行自动计一次 iteration，候选 hash 去重计 revisions，失败自动计 failed_gates；旧执行入口也计次数。达到任一边界即 blocked/owner_decision_required=true，入口阻止下一运行、实现批次、Unit PASS、完成 PASS；不自动设计新 revision/helper/threat model/系统工具。拒绝重启同一未关闭调查清零计数；中断接管只显示当前状态和最新检查点，旧尝试不进 Hot。

发现新服务/数据库/MQ/长期 secret/native helper/管理员权限/驱动/加密体系/威胁模型、由项目受控执行转向 hostile-host、任务外基础设施，均先报告 scope expansion。action=scope、scope_expansion=[具体类别]、reason、当前角色，持久 OWNER_SCOPE_DECISION_REQUIRED；planned 批次请求也接受 scope_expansion 并阻断。分类需要执行角色如实申报，不是通用意图识别器。

继续或结束必须 action=owner-decision、actor_role=project_owner、owner_authorization=true、decision=continue/close、reason、decision_evidence=实际反馈文件。继续可明确增加边界但不清零计数；范围扩张还须 approved_scope_expansion 精确批准所报类别。用户反馈由 PM 据实登记，此本地角色协议不是身份认证系统。关闭调查不等于授权新能力，不等于测试 PASS；正常任务仍受原需求/Change/风险/人工验收规则约束。绕开工具直接执行或编辑文件无法由本工具禁止。
