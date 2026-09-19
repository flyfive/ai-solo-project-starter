# V1.9.1 测试/验收设施设计（实现前审查）

审查基点：本地 e52872f；current/VERSION=1.9.0，工作树干净。本轮不访问任何业务项目。版本规则为 major.minor.patch；采用向后兼容的 1.9.1，旧 schema 1.9.0 不改名、不自动迁移。

## 已有能力与缺口

| 主题 | 1.9.0 已有 | 本次缺口 |
|---|---|---|
| 上下文/批次 | Hot/Task/Cold、context_refs、freshness、Parent/Unit、原门禁 | 复用，不建第二状态机 |
| 证据 | ai-evidence 的 run/import、raw SHA、失败保留、L1-L5 | 显式 kind、coverage、四层独立身份、只读审计 |
| 验收 | task_contract、scoped checks、人工验收分离 | runtime-required 不得接受 model/static；绑定本合同覆盖范围 |
| 排错 | debug_checkpoint；investigation 禁止 ai-start 实现 | 持久止损计数、所有者范围决定、接管摘要 |
| 身份 | 文件 SHA、工作树/实现树指纹、项目路径约束 | Candidate 白名单独立于合同/Harness；拒绝链接和路径逃逸；mtime 仅审计 |
| 升级 | 旧请求兼容、Lite→Standard、需求历史与冻结发布 | 人工三方合并说明；不改写旧证据 |

## 接入方案

继续使用 project.py 与 context_engine.py；不新增运行依赖、常驻服务或生成项目文件。ai-evidence 增加显式 acceptance_contract 路径，action=preflight/run/audit。旧 run/import 保留原行为与旧 fingerprint，不为旧记录补造新保障。新协议 schema=acceptance/1 独立于旧项目 schema；新治理任务应使用新合同，兼容路径不是新保障。

合同记录 candidate_revision、candidate_source_hash（允许文件清单的规范 JSON SHA）、acceptance_contract_revision/hash、harness_revision、evidence_run_id，并记录 approval_id、participants、timeout、rule version、权限依据、覆盖要求。Hash 由工具计算核对，不由 PASS 布尔值代替。Candidate 文件不得包含本次 run ID、审批号、合同 hash、输出目录等会话绑定；这是设计审查规则，不做字符串搜索伪证明。

合同 identity 不含 run_id：同一合同可执行多个新 run；contract revision ≠ candidate revision。candidate manifest 显式枚举实际代码文件；harness manifest 单独固定。只有候选字节/规范路径/文件类型/链接状态参与候选身份；目录 mtime/atime 默认 audit-only。额外 volatile 硬门必须显式理由和预期值。声明 capability 与 required capability 比较提供四种 compatibility 结果；能力真实性及产品/安全语义仍由 PM/所有者审核，工具不能证明语义。

Preflight 不执行 argv，只校验 schema、文件身份、命令入口、授权记录、覆盖计划、兼容性与新证据目录。run 自动重复 preflight 后以排他 mkdir 占用新 run，向 Harness 传递冻结合同与独立输出目录；不改 Candidate。Harness 保存实际 runtime-result.json 与原始输出，Auditor 只读检查并另存 audit/summary；重新审计产生新审计文件，绝不修改 runtime 原件。缺少实际运行报告/原始引用不能 PASS。工具记录进程确实执行及声明的 kind/participants/entrypoint；无法自动证明 Harness 内部业务语义或外部手工声明真实，审查责任不消失。

Coverage 使用现有批次 AC/required_checks 的 ID，不产生另一份需求源；新协议 planned/high-risk/L3+ 必须结构化 coverage，简单新协议也明确所需检查。每条 required_evidence_kind 精确匹配实际 kind，runtime 必须对应捕获进程与原始证据；L1-L5 与 kind 正交。人工证据仍需所有者授权，不能由自动测试代替。

调查通过现有 ai-context 增加 investigation 操作，在原 runtime 区仅有活动状态，旧记录进原 history。记录最新 debug_checkpoint 和累计 attempts/候选 identities/失败门禁；高风险至少一个正数止损边界。达到边界持久 blocked/owner_decision_required；ai-start、运行证据、Unit PASS、完成 PASS 被入口门禁拒绝。外部调查尝试需如实登记；直接编辑源码/绕过工具不在本地工具强制能力内。所有者决定需角色、明确授权、理由和证据引用，扩大边界不清零计数。scope_expansion 是显式类别申报，未知新基础设施同样须申报；不声称静态分析能识别所有扩张。

## 验证与发布边界

先写真实初始化/CLI/状态重读反例，再实现。覆盖 T1–T15，增加路径/篡改/绕过反例。保留失败原始输出；完整正式回归仅在实现完成后执行。打包从 Git 跟踪候选清单临时导出，避免把 current 内忽略的私人旧报告带入包，ZIP/SHA 输出 releases 新目录；不覆盖历史包。本轮只本地提交：既有维护规则要求明确授权后才能推送，过去 CI 推送授权不扩展到本轮。

## 轻量边界

完整字段协议放生成项目已有 README 的按需章节；AGENTS/规则只加导航。默认接管不装入合同全文、coverage/raw/尝试历史。成功返回路径、状态和计数。新增状态仅在使用调查或证据时生成，不增加用户表单。旧证据永远按旧契约验证，不自动改写。

## 实施与最终代码验证（2026-09-19 至 09-20）

本地维护入口 current 已升级 1.9.1；历史快照、旧包、旧报告和真实业务项目未修改。新功能只扩展 context_engine 及现有模板，不增加生成项目初始文件或运行依赖。Lite/Standard 仍为 23/36 文件。project.py 旧核心状态机未改写；build_package.py 已由 VERSION 读取版本，无需改动版本算法。

最终正式 Python 入口：143/143 通过，0 失败，0 unittest 显式跳过，115.397 秒；测试期间 62 个源文件字节不变。环境 Windows、Python 3.14.5、Git 2.54.0.windows.1、Node 24.15.0。平台条件分支仅代表本机路径，不能据此声称 Linux/Python 3.11 或远端矩阵本轮已运行。

| 验证类别 | 实际结果 |
|---|---|
| existing regression | 原 regression 54/54、context efficiency 25/25、轻量增强 16/16、页面 7/7、public readiness 9/9，共 111/111 |
| new hardening regression | 32/32；T1–T15 加真实异常、旧 PASS/新合同拒绝、批次闭环、授权/范围/原始文件反例 |
| packaging regression | 原完整回归中的 3 项 ZIP 路径/链接、缓存排除、ZIP+SHA 事务用例均通过；实际本批发行包另按白名单导出后验证 |
| migration compatibility | 原 Lite→Standard/挂起/审计恢复/事务回滚/需求历史用例通过；T12 实际旧请求运行；新旧证据不能互换绕过 fingerprint。没有迁移任何真实项目 |

保留了实现前 18 项反例中的 17 项失败；针对性迭代中的目录路径验证缺陷和测试异常注入位置错误均保留原日志并修复。第一次完整运行 141/142：临时样例保留环境开关与旧清理用例冲突（测试设施配置失败），撤去开关而不改断言后 142/142。随后自审发现审计接口需拒绝新合同/新 run 借用旧 PASS，补反例后最终 143/143。原始日志只在本地 validation/hardening-20260919，各次结果不互相覆盖。

## 交付前自审：强制与规则边界

1. **原版已经覆盖什么？** Hot/Task/Cold、正式事实/工作树新鲜度、需求修订、文档优先、授权、批次/Unit、L1–L5、失败 raw、人工验收和 Lite→Standard 均复用，未重建。
2. **真正新增什么？** acceptance/1：独立身份、preflight、kind/coverage、运行与审核隔离、兼容输出、失败分类；活动调查累计边界及 scope owner gate。
3. **哪些工具强制？** 清单/哈希/路径/类型/启动目标、目录不复用、kind 精确匹配、raw 存在与哈希、批次 coverage、原合同审计、累计止损及 owner 角色/授权记录。**哪些是规则？** Candidate 不硬编码会话参数、完整枚举实现文件、Harness 如实启动/报告真实参与者、范围扩张识别、产品/安全语义认定、授权记录真实性。
4. **仍可能无限修补吗？** 无边界的低风险旧请求、工具外直接编辑/执行、未申报调查或所有者反复追加预算仍可能。高风险新调查必须有边界，达到后不会自动续跑；不承诺操作系统级禁止绕过。
5. **在哪里阻断？** context_engine 的 investigation_guard 接入 ai-start、ai-evidence run、Unit PASS、ai-finish PASS；运行尝试自动累加，达到阈值保存 blocked/owner_decision_required。必须已有所有者反馈才能 continue/close，continue 不清零。
6. **如何机器区分 model/runtime？** 合同 required_evidence_kind 与运行行 evidence_kind 精确比对；runtime 另需捕获的 Harness 进程、PASS runtime 状态、约定入口/参与者及非空 raw 引用。字面 bool、缺 raw、model/static 类型不符均拒绝。工具不能发现被错误/恶意标为 runtime 的模拟程序；Harness 源码与业务真实性必须审查，不能把类型标签称为语义证明。
7. **合同修订是否不再强迫候选修订？** 新路径在候选清单 hash 不变时允许新合同、新 run；真实批次完成测试验证旧 PASS 被拒绝，新 run 可关闭。旧路径仍按旧 fingerprint 验证，不能混用冒充解耦。
8. **volatile metadata 是否分开？** 默认只保存在 audit_metadata，不参与候选 hash；mtime 变化测试通过。显式 volatile_identity 硬门必须 reason/expected，另有真实拒绝用例。
9. **旧项目怎样迁移？** 继续原版或在完整备份分支按 UPGRADE_V1.9.1 三方合并；不得直接覆盖 PROJECT.toml/project.py，不改写需求/Git/状态/历史 evidence。
10. **是否向后兼容？** 已测旧 V1.8.1-compatible 请求和 111 项既有用例均通过，旧 schema/bundle 保持 1.9.0，新字段缺省不授予新保证。不承诺任意项目专属扩展无需人工合并。

## 使用例与负担

小修复：PM 保持原 small_change、范围、原症状检查与适用测试；若采用类型化证据，给批次引用合同，用实际 runtime 原始输出完成 original_symptom，不扩张无关 AC。更改审核规则只修订合同，PM 按原流程重读确认后新 run，候选源码不为 run ID 改动。

中断排错：PM 通过 ai-context investigation 建立 max_iterations=3 的调查；记录现有 debug_checkpoint 的现象、假设、排除原因和下一步，或由 ai-evidence 自动累计实际尝试。新执行器只读 manifest.investigation；第 3 次后进入 blocked，所有者决定前不设计下一 revision 或新 helper。

新增分发文件仅本设计、UPGRADE_V1.9.1 和针对性测试；生成项目初始文件不增加，使用时才在原 runtime/history/evidence 区产生调查状态和每次不可复用的运行/审计记录。完整字段只放生成项目 README，其他规则只导航；普通 Hot 不带合同、coverage 或尝试历史。成功输出是状态/计数/路径，无 Token 或额度节省声明。

## 剩余限制与回退

本轮未运行真实浏览器/系统剪贴板、Linux/远端 CI，也未测试真实项目迁移。能力/参与者/业务语义、真实所有者身份依赖项目角色如实声明和审阅；不是 hostile-host 沙箱。Harness 自行管理其业务资源/子进程；工具有界等待并保留超时，不能保证清理所有外部资源。模板 ZIP 用于初始化分发，包含根目录工作流/入口检查的完整回归应从完整仓库布局运行。

本地基点 e52872f；本次提交之后可用 git revert 撤销该提交中的工具改动（先保存未提交工作），不删除 validation、旧包或已产生的新运行证据。公开同步副本仍为 c29bc6c；本轮未推送、未创建 Release，后续公开更新须接续公共 main 历史并按清单同步，不能合并私人 master。


最终版本一致性检查仅将离线页面三个 V1.9.0 展示/提示词文本同步为 V1.9.1，模式、路径和两个复制入口逻辑未变；这一步另跑页面及 public readiness 针对性套件。最终 143 项全套覆盖上述引擎/模板代码，后续仅报告与页面版本文本调整。

包验证使用公开跟踪清单的 55 个文件，不含忽略的私人旧报告。初始包采集脚本曾按 GBK 解码 UTF-8 子进程输出，属于验证设施错误，未用它判定候选失败；显式 UTF-8 后继续验证保留样例，Lite/Standard 的初始化、初始 Git 提交、真实 Hook 提交、health、ai-context check 与接管全部通过。预期警告为尚无正式需求，Standard 另有尚无完整审计。最终清单、最终包 SHA 与两模式原始日志保存在本地本批验证目录。

## 发布后核对与 V1.9.1 有限审核修补（2026-09-20）

上文“未推送/未运行远端 CI”是原报告截止点，不改写其历史。V1.9.1 原实现本地提交为 551645e，本次实际维护基点为后续 b2d712e（已保留），公开提交为 2414e6a252aa5d2a3b0ca29c5a0019a85dd28250；两者属于独立历史，不可互相合并。此次只读回查 [CI 35454320645](https://github.com/flyfive/ai-solo-project-starter/actions/runs/35454320645)，对应上述公开 SHA，完成时间 2026-09-19 16:18:56 UTC，Ubuntu/Windows × Python 3.11/3.14 四组均 success。它证明修补前公开提交的 CI 状态，不证明下述本地修补；本轮不推送或触发远端运行。

### 实际复现与修复范围

先用真实初始化项目、CLI 和持久状态重读新增 8 个反例，修补前 6 个失败、2 个已有能力通过（14.307 秒）；不是规则文字检查。只修改既有 context_engine、对应测试及生成 README 说明，VERSION 保持 1.9.1，不增加生成项目常驻文件、依赖或治理模式。

- **审计闭环**：仅修复 Auditor 后，action=audit 在原 run 追加完整 summary-audit 与 audit 文件，使用现有证据验证函数和正常 ai-finish。绑定原四元组、runtime/raw、原失败摘要与新审计哈希，保留批次、级别和上下文；不改 Candidate/Harness/合同，不再启动 Harness。缺失绑定、原件/审计篡改或审计失败仍拒绝；新合同/新 run 不能借用旧 PASS。没有第二份审计状态机。
- **状态与设施错误**：Harness 已启动却无有效最终报告记 UNKNOWN，捕获已有文件及真实退出码；仅有可靠未启动依据才记 NOT_RUN。退出 1 的一致 FAIL 报告和 completed 标记可表示候选失败；退出至少 2、真实采集错误或冲突报告不能由声明掩盖。完整约定集中在生成 README 的按需证据章节。
- **保留原件**：Lite/Standard 的真实闭环测试先令 Auditor 抛 TypeError，再失败审计、成功审计、完成批次；比较候选、Harness、合同和原运行目录所有已有文件字节，并检查 Harness 执行计数始终为 1。旧失败摘要及历史审计不回写；报告前崩溃产生的候选输出保留。篡改测试使用各自隔离副本，不污染历史证据。

针对性首轮 8/8 通过；补充运行原件/原摘要篡改与损坏 failure_class 反例后，新测试共 10 项，hardening 套件共 42 项。相关 hardening/context efficiency/轻量套件 83/83 通过（221.535 秒），这些重复运行不累计为新增测试数。完整回归的最终结果另附于本节末。

### 边界与回退

NOT_RUN 的启动前失败依据仍依赖经过审查的 Harness 如实报告；没有新增操作系统监控或证明业务语义的能力。历史 NOT_RUN 不回写，也不自动获得新约定的保证。重新审计可修复 Auditor 故障，不能掩盖 Harness/候选真实失败，不能绕过止损或批次上下文门禁。原报告与包是修补前历史产物，保留原字节，本批不重打发行包。测试中的临时 ZIP 回归夹具不作为新发行包。

本次回退应先保存其他未提交工作，再 revert 本批本地修补提交；不要重置维护历史或删除 evidence。本轮未验证修补后 Linux/远端矩阵、真实浏览器/系统剪贴板或真实项目迁移；既有远端成功不替代这些结论。原始反例和测试输出仅保留本地 validation/audit-repair-20260920。

### 本次修补的最终验证

在 Windows / Python 3.14.5、隔离测试 Git 配置下，以正式 run_tests.py 入口运行一次完整回归：**153/153 通过、0 失败、0 显式跳过，119.477 秒**。执行期间 62 个源码文件字节不变；随后仅追加本段测试事实，未改动受测实现。各套件为 regression 54、context efficiency 25、lightweight 16、page prompts 7、public readiness 9、acceptance hardening 42（原 32 + 本次 10），没有将前面的重复运行算为新增测试。

原 Lite/Standard、旧请求兼容、升级、止损与上下文边界用例全部通过；既有打包回归只操作临时夹具。原发行 ZIP 及其 SHA256 文件与修补前哈希相同；ZIP SHA-256 仍为 241b380ce22e77012ebc145ed04e68b865dd5ea7d17c4ea3ce44d379a772f92d。没有重新打包或覆盖旧包。修补后只完成本地验证和本地提交，未推送；修补前远端 CI 与本次结果分开。
