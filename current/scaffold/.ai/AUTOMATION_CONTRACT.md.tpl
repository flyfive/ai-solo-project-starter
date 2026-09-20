# V1.9.0 Standard 工具无关多智能体自动化契约

本文件供具备本地文件、终端和 Git 权限、并承担明确项目角色的智能体读取。用户不输入内部命令，也不维护 JSON。

Standard 模式采用严格状态机：未完成执行只能记录为 `PARTIAL/BLOCKED` 并保持活动批次；只有主测试与必需集成测试分别全部真实通过、无阻塞且满足必要人工验收的 `PASS` 批次才能关闭。项目结案后进入终态，除非项目所有者授权显式重开；任何已经结案的发布版本永久冻结。

## 1. 角色声明

任何执行活动前必须先明确角色：

- `project_manager_agent`
- `analysis_review_agent`
- `code_executor`
- `integration_reviewer`

角色权限以 `docs/ROLE_BOUNDARIES.md` 和 `PROJECT.toml` 为准。具体软件或模型名称不得替代角色声明。

同一时间只允许一个活跃项目经理主智能体。分析审核角色默认只读；代码执行器不能修改共享语义文档；并行代码执行必须经过集成审核。

## 2. 接管与上下文计划

首次进入或外部文件发生变化时，承担当前角色的智能体内部运行恢复流程并声明任务。工具生成覆盖式 `context.json`，返回：

- 默认 Hot/Task 读取与显式 full 审查；
- 必须读取的最小文件集合；
- 按任务和角色可选读取的文档；
- 当前任务引用、源指纹和相关内容是否 stale；
- 默认不读取的历史与无关文档。

同一窗口每条消息不得重复运行恢复流程。已读取且未变化的文件不完整重读，优先查看 Git diff 或变化章节。

固定恢复优先级：

1. `captured` 变更：先完成文档写回；
2. 其他未关闭变更：完成实现、测试和重新验收；
3. 活动批次：继续当前状态；
4. 无未完成事项：按当前计划继续。

## 3. 项目记忆摘要

`docs/PROJECT_MEMORY.md` 由两部分组成：

- 自动状态区：工具更新阶段、批次、未关闭变更、优先级和最近审计；
- 语义摘要区：项目经理主智能体维护项目定位、核心规则、关键架构、禁止项、重要变化和未决事项。

正式源和派生索引同步；只有 PROJECT_MEMORY 的跨任务引用实际受影响才更新其摘要，不重复复制正文。

## 4. 登记变更

用户提出调整后，项目经理主智能体写入临时 `change_request.json`，至少包含：

```json
{
  "source": "manual_acceptance",
  "origin_batch_id": "P2-004",
  "raw_feedback": "移动端取消应用内音量控制，桌面端保留",
  "change_types": ["requirement_change", "ui_behavior_change"],
  "affected_implementation": ["移动端控制栏", "跨端 UI 测试"],
  "requires_reacceptance": true
}
```

工具生成变更编号、所需文档类别、文档哈希和实现工作区指纹。

默认文档矩阵：

| 类型 | 必须更新 |
|---|---|
| `bug_fix` | 无强制语义文档，仍需测试、状态和日志 |
| `requirement_change` | requirements、acceptance、decision |
| `acceptance_change` | acceptance、decision |
| `architecture_change` | architecture、plan、decision |
| `plan_change` | plan、decision |
| `ui_behavior_change` | requirements、acceptance、decision |
| `pitfall_rule` | pitfall |
| `execution_rule_change` | rules、decision |
| `role_boundary_change` | roles、rules、decision |

## 5. 文档优先验证

项目经理主智能体先修改必需的共享语义文档，不修改实现。工具验证：

- 必需文档相对登记时哈希发生变化；
- 登记后没有新增实现文件变化；
- Git 可用于严格工作区指纹。

失败时不得继续实现，必须恢复抢先发生的实现修改。

## 6. 批次与并行执行

批次开始请求必须包含批次、阶段、目标、范围、验收条件、关联变更和授权状态。存在未关闭变更时，批次必须优先处理全部变更。

并行执行请求示例：

```json
{
  "batch_id": "P2-003",
  "stage_id": "P2",
  "title": "前后端并行实现",
  "goal": "完成一个可集成验收的业务闭环",
  "scope": ["后端接口", "前端页面"],
  "acceptance_criteria": ["接口契约一致", "集成测试通过"],
  "execution_mode": "parallel",
  "execution_threads": [
    {
      "thread_id": "backend",
      "role": "code_executor",
      "scope": ["后端接口"],
      "allowed_paths": ["backend/app", "backend/tests"]
    },
    {
      "thread_id": "frontend",
      "role": "code_executor",
      "scope": ["前端页面"],
      "allowed_paths": ["frontend/src", "frontend/tests"]
    },
    {
      "thread_id": "contract-review",
      "role": "analysis_review_agent",
      "scope": ["接口契约一致性审核"],
      "allowed_paths": []
    }
  ]
}
```

代码执行器只接收明确范围，不得直接改变产品基线。并行代码执行线程必须拥有不重叠的文件边界或隔离工作区，并分别返回执行报告。

存在多个代码执行线程时，批次结果提交前必须完成集成审核，至少验证：

- 文件冲突和重复实现；
- 接口、数据和行为契约一致性；
- 集成构建和回归测试；
- 共享语义文档由唯一责任角色写回；
- 所有执行线程的风险与阻塞已汇总。

批次结果必须记录真实测试、下一项任务、长期记忆影响、关联变更和项目经理主智能体复核。

批次状态规则：

- `PASS`：至少一项测试或检查，且全部为 `pass`，不得存在 blocker；
- `PARTIAL`：本次工作只完成一部分，必须记录未完成原因，活动批次和变更保持打开；
- `BLOCKED`：受依赖、环境或授权阻塞，必须记录 blocker，活动批次和变更保持打开；
- `PARTIAL/BLOCKED` 不进入人工验收，也不得被当作批次关闭；
- 变更只有处于已实现状态，或在需要重新验收时得到项目所有者通过后才能关闭。

并行执行还必须包含：

```json
{
  "manager_review": {
    "status": "approved",
    "reviewer": "project_manager_agent",
    "note": "范围、测试和风险符合批次要求"
  },
  "integration_review": {
    "status": "approved",
    "reviewer_role": "integration_reviewer",
    "note": "并行结果已集成，无未解决冲突",
    "tests": [
      {"name": "集成构建", "status": "pass", "details": "通过"}
    ]
  }
}
```

需要人工验收时，批次进入等待状态，不能自行关闭。

集成审核的 `tests` 不得缺失，且每项状态都必须精确为 `pass`。必需的并行集成审核只能由 `integration_reviewer` 角色批准。`fail`、`blocked`、`not_run`、未知状态、缺失测试或错误审核角色都会拒绝批准并保持活动批次和关联变更未关闭；错误必须指出具体测试及状态。主测试通过不能替代集成测试通过。

用户未通过或通过但有调整时，先登记新变更、完成文档写回验证，再开始同批返工。

## 7. 完整上下文审计

阶段切换前，项目经理主智能体读取全部当前事实文档并写入临时 `audit_result.json`：

```json
{
  "stage_id": "P2",
  "status": "passed",
  "documents_read": [
    "docs/ROLE_BOUNDARIES.md",
    "docs/PROJECT_MEMORY.md",
    "docs/CURRENT_STATE.md",
    "docs/PRODUCT_REQUIREMENTS.md",
    "docs/ACCEPTANCE_CRITERIA.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT_PLAN.md",
    "docs/DECISIONS.md",
    "docs/PITFALLS.md"
  ],
  "conflicts": [],
  "resolutions": [],
  "summary": "当前事实与角色边界一致，可进入下一阶段",
  "manager_review": {
    "status": "approved",
    "reviewer": "project_manager_agent",
    "note": "需求、架构、计划、角色边界与实现状态一致"
  }
}
```

工具验证文档存在并记录审计到机器状态和月度日志。未通过审计时禁止阶段切换。

## 8. 正式需求登记与修订

项目经理主智能体通过结构化需求更新登记：

- `create`：分配新的永久编号与 `.1` 初始版本；
- `revise`：产品语义变化，自动递增修订号；必须提供 `expected_current_version` 和真实未关闭 `change_id`；
- `link`：仅更新实现文件/模块/提交引用、自动测试/报告/状态/证据、人工验收证据/结果以及发布基线/交付物等纯追踪关系，不递增修订号；必须提供 `expected_current_version`；
- `sync`：重建当前需求、验收、修订台账和追踪矩阵自动区。

正式需求登记只接受 `project_manager_agent` 角色。代码执行器不得直接修改登记表或自动生成区。

`link` 使用严格允许字段集合，嵌套的人工验收对象只接受状态、日期和证据说明，验收条件对象只接受编号、状态、证据和说明。标题、正文、业务规则、角色、平台、范围、优先级语义、验收条件描述、验收方法、客户可见行为、发布目标、用户操作说明、已知限制语义、非功能要求以及删除/废弃/移出范围决定均不在允许集合中。遇到这些字段必须在任何写入前整体拒绝，并提示登记真实未关闭变更后使用 `revise`；不得静默忽略或部分写入。

每个 `R-NNN.n` 修订快照必须深拷贝并保存当时的完整需求语义，包括标题、状态、类别、优先级、正文、理由、客户可见性、发布阻断、发布目标、验收条件描述与方法、用户操作说明、说明核对状态、帮助说明、已知限制和需求备注。修订台账必须能脱离当前版本完整还原任一旧版本；当前语义字段必须与最新修订快照一致，直接改登记表造成的语义漂移必须拒绝。

非空 `release_target` 必须在需求创建和修订时通过仅含 ASCII 数字的 SemVer 校验，非法值整体拒绝且不得写入。健康检查必须把登记表中的非法目标报告为 `FAIL`。已存在 closed 基线的版本不得再作为新建或修订需求的目标。

需求登记表与四份自动生成文档必须作为一个事务写入。所有内容先生成并解析验证；任何替换失败时恢复登记表和全部派生文档，不能留下半写入。

需求变化与待处理变更同时存在时，项目经理先用变更编号修订对应需求，再完成其他决策和项目记忆写回，最后执行文档优先验证。

## 9. 发布基线

发布基线创建前必须满足：

- 无活动批次和未关闭变更；
- 当前完整审计有效；
- Git 工作区干净并存在唯一 HEAD；
- 需求登记表与四份生成文档一致；
- 所有纳入当前发布范围的 active 需求均达到 `COMPLETE`；`release_blocking` 是强制阻断子集，但不是唯一要求完整追踪的需求；
- 客户可见需求具有经过最终产品核对的实际使用说明。

基线创建前必须对全部 active 需求分类并记录：本次纳入、无目标版本、未来版本、未处理的过期目标、已由历史结案基线覆盖的旧版本需求以及无法精确匹配的目标。无目标版本需求纳入本次门禁；未来版本需求显式列入范围报告但不纳入本次实现门禁；没有已结案历史基线保护的过期目标或无法精确匹配的目标必须阻止发布，不能静默跳过。

基线保存需求版本快照、需求范围分类、文档哈希、原始 Git 提交、已提交实现树哈希和审计记录。每个基线拥有不可复用编号；同一发布版本不得覆盖旧基线，替代时必须显式引用 `supersedes_baseline_id`，旧基线保留为历史。基线创建和替代必须在全部预检查后以跨文件事务写入，失败时恢复基线文件、索引、项目状态和日志。当前需求、追踪文档、Git 历史关系或实现内容变化后，旧基线自动失效。

任何状态为 `closed` 的基线及其发布版本永久冻结，禁止覆盖、替代、重建、删除或作为被替代对象。项目重开必须由项目所有者同时提供最近结案版本、新开发版本、原因和授权说明；新版本按语义版本规则比较且必须更高。重开后只允许为锁定的新开发版本创建基线，未结案的活动基线仍可按规则显式替代。

## 10. 客户交付、最终验收与结案

有效发布基线形成后，项目经理主智能体生成按发布基线编号隔离的客户文档目录。生成请求必须提供真实存在且位于项目根目录内的相对交付物路径。绝对路径、Windows 盘符、UNC、`..` 逃逸、符号链接或目录链接逃逸均拒绝。工具冻结每个交付物的规范化相对路径、类型、SHA-256、总字节数和文件数量。源码基线后生成的未跟踪构建产物可以作为显式交付物登记；已跟踪源文件不能通过交付物声明绕过实现树门禁。

交付目录已经存在时，默认整体拒绝再次生成；只有显式 `force=true` 才能把全部客户文档、manifest、基线关联和日志作为一个事务重新生成。验证必须核对 `DELIVERY_CHECKLIST.md` 与 manifest 的交付物哈希完全一致。最终验收的基线、报告、项目状态和日志也必须事务写入，失败时完整恢复。

交付验证拒绝：

- 缺失文档或交付物；
- `待补充`、`TODO`、模板变量等占位内容；
- 未覆盖发布基线需求的最终验收报告；
- 未覆盖客户可见功能的用户手册；
- 内部角色、运行 JSON、Hook 或敏感机制泄漏。

项目所有者最终验收由项目经理根据真实反馈登记。最终验收通过且交付文档、交付物哈希、原始基线提交关系与实现树保持有效后，项目才能结案。最终验收和结案均采用事务写入，任一步失败必须恢复原状态。结案后禁止继续启动批次、修订需求或修改已冻结发布；重新开发必须由项目所有者授权，显式指定原结案版本、新阶段、更高的新发布版本、重开原因和授权说明。

## 11. Git Hook

初始化后自动配置 `.githooks/pre-commit`，并记录初始化时实际可运行的 Python 解释器。Hook 先验证该解释器，再探测平台回退命令。提交前拒绝尚未完成文档优先处理的变更。禁止使用 `--no-verify`。

## 12. 工具绑定

核心协议不记录具体工具名称。如确需保存当前会话使用的软件，只能写入被 Git 忽略的本地临时文件，例如：

```text
.ai/runtime/tool_bindings.local.json
```

该文件不得参与需求、架构、规划、角色权限或验收判断。

## 13. 临时状态容量

- `context.json` 和交接摘要覆盖更新；
- `pending_changes.json` 只保留未关闭变更；
- 请求载荷使用后删除；
- 活动批次关闭后清理；
- 长期历史进入权威文档、月度日志和 Git。

## V1.9.0 上下文与证据接口

本契约保留原有状态机和授权。默认接管遵守 docs/CONTEXT_LOADING_PROTOCOL.md，不将完整事实/历史嵌入日常输出。ai-context 提供索引、按 ID 正文、freshness 和有原因的 Cold 检索；ai-unit 记录父批内部单元；ai-evidence 保存原始日志与结构化摘要。旧请求字段继续可用；新 context_refs、work_units、required_test_level、risk_tags、required_checks 是可选扩展，声明后必须通过校验。


## 可选任务与排错扩展（兼容 V1.9.0）

沿用原批次状态、checks、证据和人工验收，未携带可选字段的旧输入维持原契约，不补 PASS。task_contract/debug_checkpoint 字段仅在使用时读取 README 的“任务字段与结束核对”/“排错字段”，本契约不重复正文。

## V1.9.1 验证设施边界

新 planned/高风险/L3+ 验证采用 README 的“测试设施合同”；调查/范围扩张按“调查止损与范围决定”按需读取。Candidate、Contract、Harness、Evidence 分离；旧历史不重写，已有治理门禁继续有效。完整字段不在本入口重复。

Standard blocked/partial 且无未关闭 Change 时，可按 README“Standard 非成功批次交接”由 PM 登记强绑定所有者授权；handoff 不是 PASS。pending successor 时只能启动具名继任，禁止删除锁绕过。字段和事务规则只按需读取该节。
