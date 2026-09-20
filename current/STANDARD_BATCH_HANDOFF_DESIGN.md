# Standard non-success batch successor handoff

## Why

BLOCKED/PARTIAL ≠ PASS。责任已明确移交时，也不应永久占用唯一 active slot。此能力仅让 Standard 的真实非成功批次在所有者授权下进入 handed_off；它不是验收、豁免、取消或成功关闭。

|路径|原事实|槽位与后续|
|---|---|---|
|normal PASS close|通过原测试/审核/适用人工验收|finalize_batch 更新 last_closed_batch|
|incomplete attempt|partial/blocked|保留 active 和失败尝试|
|Lite promotion suspension|Lite 升级前的真实未完成|保留待升级批次，原升级审计后恢复|
|Standard successor handoff|partial/blocked → handed_off（非成功终态）|释放 active，只允许冻结定义中的具名继任启动|

## Identity and authorization

复用现有 batch request：继任合同为 project root 内的 JSON，至少含 batch_id/stage_id/title/goal/scope/acceptance_criteria，另有 status=planned。它不是新 task registry；可选 task_contract/context_refs/risk 等仍使用原 validate_request。路径、SHA-256、successor_batch_id 强绑定，拒绝链接/逃逸/缺失或漂移；启动请求归一化后须与冻结定义一致。源与继任不可相同。

owner_authorization 必须为对象，绑定 source_batch_id、successor_batch_id、granted=true、source_ref={path,sha256} 和 note。记录由 project_manager_agent 提交。工具验证绑定和证据文件，不声称从文件内容自动证明所有者身份；PM 必须据真实反馈登记。拒绝 boolean、无引用、哈希漂移及错误身份。

## Durable facts and runtime lock

仅使用时创建 .ai/history/batch_handoffs/<handoff_id>/source_active.json（原 active 字节）和 record.json（schema=batch_handoff/1）。record 保存源身份/状态/阶段/标题/开始时间/阻塞/快照 SHA、继任合同身份、责任列表、原因、授权、Git、交接时间。status 永为 handed_off；activation_status 仅允许 pending_successor → consumed，消费时增加 consumed_at/consumed_by_batch_id，其余历史字段保持不变；state 中导航哈希随激活元数据在同一事务更新。不可把 handed_off 写入 last_closed_batch。

.ai/runtime/pending_batch_handoff.json 是锁，绑定 handoff_id、源/继任 ID、历史路径/哈希和源快照哈希。project_state 可选 pending_batch_handoff、last_handed_off_batch、handoff_history 保存当前指针和导航；缺省不存在，旧项目不增加告警。原需求、acceptance、stage_acceptance、last_closed_batch 不变。

## Transactions and original gates

交接使用已有 atomic_file_transaction：快照、历史、state、日志、marker、PROJECT_MEMORY、CURRENT_STATE、context/index/HANDOFF、删除 active 与 input 同一事务。继任启动先通过既有升级基线、Change、阶段、风险、调查止损及上下文门禁，再事务创建 active、消费 record、更新 state/摘要和删除 marker/request。任一可捕获写入异常全部恢复；注入第一个、中间和尾部写入故障验证。该机制沿用本地单写者假设，不提供断电恢复、并发写者或 hostile-host 防篡改保证。

存在任何 open pending_changes 就拒绝交接；不迁移变更所有权。继任启动重新检查 marker/state/record/快照/owner 引用/合同哈希与身份，重复或漂移拒绝。继任仅携带 inherited_handoff 责任与证据引用，不继承 manual acceptance、stage PASS、manager review、release approval 或需求 PASS。没有使用 finalize_batch。

## Context and health

pending 时恢复优先级为 start_handoff_successor，并显示具名继任及历史记录导航；只读必要绑定，不把完整历史塞入 Hot。active successor 只显示交接身份/记录路径，责任正文按需读取。health 检查 active+marker 非法并存、孤儿/缺失 marker、缺失/已消费历史、身份和哈希漂移。普通旧项目无交接数据时走原行为。

不涉及多 parent、DAG、数据库/服务、分布式锁、跨批 Change 或新 registry。配置 schema_version 继续 1.9.0，产品目标 1.9.2。实现及测试不包含任何下游业务代码或证据。
