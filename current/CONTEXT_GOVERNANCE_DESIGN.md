# V1.9.0 Context Governance 设计

## 数据与读取边界

L1：START_HERE 项目简述、AGENTS 简短规则、CURRENT_STATE、runtime/context.json。后者是 CONTEXT_LOAD_MANIFEST，包含当前活动批次摘要、PM/执行器定位提示、选定索引行、L2选择器、L3入口、freshness 和字节度量；禁止嵌入历史审计、全量 pending 对象、测试正文或完整索引。

L2：ai-context read --kind requirement --id R-001 返回当前需求及全部 AC/语义/追踪，不带 revisions；architecture C01 返回 Markdown 章节；decision DEC-... 返回指定正文。ai-context index 支持 kind/id 筛选和分页。默认不输出全量索引。机器内部验证/哈希可以读完整文件，这不是将内容送入 AI。

L3：ai-context cold --path 项目内证据路径 --reason regression/history_conflict/compatibility/owner_request/referenced_evidence。要求明确原因；默认有界行区间，支持继续读取。ai-context history --kind requirement/batch/change/decision --id 精确查找历史位置。Cold 查询记录读取清单与实际返回字节，原始证据不进入默认 manifest。

## 索引

Standard 的 .ai/context_index.json 是可重建派生物，只有 metadata/locator/hash，不保存完整正文。requirements 取自现有 JSON，新增可选 module、summary、architecture_refs、decision_refs 均为正式语义，修订与 link 白名单保持一致。Architecture 使用稳定 Cxx 标题与 CONTEXT JSON 注释（summary、requirements、code_paths、decisions、red_lines）。未登记稳定 ID 的旧文档采用明确旧章节 ID，不能猜测映射。Decision 兼容旧内联条目；新 Standard 决策正文写入 docs/decisions/ID.md，旧 DECISIONS 保留引用。

## 新鲜度

索引记录源哈希，health/Hook 检查索引与当前源重建结果一致；正文、ID、引用重复或缺失时失败。ai-resume/refresh 可重建派生索引，但相关选定正文变化后 active.context_fingerprint 仍保持旧值，任务标记 stale。PM 使用 refresh --accept-changes --actor-role project_manager_agent 确认已重新读取并更新活动任务版本。无关历史增长不改变任务 fingerprint。

## 写回和审计

现有 project.py 继续持有状态机、需求事务、升级、发布、交付门禁。辅助 context_engine.py 只提供提取/索引/证据/Unit 操作。入口前置验证及必要后置刷新接入现有函数；事务失败不刷新假状态。派生 CURRENT_STATE 自动区不参与语义审计哈希，手工当前有效摘要参与；Decision 独立文件全部纳入完整审计与基线哈希。语义需求/架构变化继续要求原有文档优先和决定记录；PROJECT_MEMORY 改为引用摘要，移除强制重复抄写要求，保留必要影响记录。

## Parent Batch 与测试

旧 single/parallel 请求保持兼容。Standard 可添加 work_units（唯一 unit_id、scope、context_refs、required_test_level），作为唯一活动父批的内部工作。Unit 结果必须有真实测试及证据；失败/阻塞记录不可覆盖，只允许同 Unit 再尝试，父批不能关闭直到全部 Unit pass。父批指定 required_checks，记录适用的 consumer/browser/package/report/checks；不适用项必须解释，缺项不能通过。

测试层级 L1 局部、L2 模块、L3 父批回归、L4 阶段集成、L5 发布。安全/数据完整性/migration/高风险最少 L4；父批最少 L3。不自动认定命令退出0等于需求满足。证据 capture 执行已授权本地 argv（不用 shell），保存 stdout/stderr、exit、环境、工作树指纹和层级，机器 JSON 与简短摘要；import 支持浏览器 trace/SQL 等已有输出，要求真实路径与来源，失败优先返回相关片段。摘要只保存失败列表/变化/数字/环境/原始路径。

## 兼容范围

新初始化保留8 profiles、Lite/Standard/Auto、旧命令、旧 JSON请求、旧编号。Lite 只增加一个辅助脚本（预计22文件），索引/协议/父批只在 Standard 启用。模板包新协议纳入校验；Lite→Standard 自动生成 Standard 索引，保留挂起与基线审计。新字段不冒充旧项目自动迁移；迁移必须备份、手动确认、验证原有事实与 Gate。

## 实现与验收顺序

审计→小模块和接口→精确提取/失效→协议与模板→父批与证据→旧54测试→新增真实项目/16类型矩阵/长历史→修复→固定源包和ZIP/SHA。报告记录真实字节与用例结果，不报告估算 token。所有失败日志保留到候选外验证目录，最终必要报告随包交付。
