# Standard non-success batch handoff 缺口分析

基点：本地 a4eaa78；产品 1.9.1。仅审查启动模板 current，未读取下游项目。

|源码入口|已核对行为|缺口|
|---|---|---|
|project.py record_incomplete_attempt|PARTIAL/BLOCKED 写回 active、状态和日志，返回 1，保留批次|未成功责任无法移交后释放槽位|
|project.py finalize_batch|非 pass 立即拒绝；pass 更新 last_closed_batch 并删除 active|不能作为非成功交接入口|
|project.py ai_start|已有 active 立即拒绝；之后按变更、阶段验收和上下文门禁启动|没有 pending successor 锁|
|project.py ai_suspend_for_promotion|仅 Lite，且 blocked/partial；升级挂起事务保留源批次|不能复用于普通 Standard 交接|

现有 atomic_file_transaction 可回滚多文件写入/删除；context_engine 已有 .ai/history、Hot/Task/Cold 与请求字段验证，应复用。现有代码没有 checked_owner_authorization/checked_evidence_ref；已有授权多为 boolean，不能满足本次源/继任双绑定，需要仅为交接增加强绑定校验。task_contract 是批次请求的可选执行约束，没有正式独立 task registry；继任定义采用带 planned 状态的现有 batch request JSON，冻结路径和 SHA，并在启动时验证请求与定义的一致性。

设计边界：仅 Standard blocked/partial，无 open changes；不修改 finalize_batch/last_closed_batch/需求与验收。handoff 事务保存源快照、历史、state、摘要与具名继任锁，最后删除 active；successor 启动在原门禁后事务消费锁。历史只允许 pending_successor→consumed 的激活元数据更新，源事实不可变。单写者、现有事务回滚语义，不引入数据库、多活动批次或分布式锁。
