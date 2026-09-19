# Context Loading / Handoff Protocol

## 默认接管

1. 读取 START_HERE 项目简述及 AGENTS 稳定规则。
2. 由当前角色内部运行 ai-resume，读取 CURRENT_STATE 与 ai-resume 的 JSON 返回（或 .ai/runtime/context.json，二选一）。
3. 检查唯一活动批次、未关闭 Change、当前阻断、next_step、freshness。
4. 查看 manifest.selected_index 中本批 R/C/DEC 索引行；按 task_selectors 精确提取正式正文与 AC。
5. 读取分配范围内代码，核对实现与正式事实，执行；普通任务不全文读取需求、架构或历史。
6. 完成后只更新受影响正式事实、必要追踪证据及当前摘要，归档原始证据，再刷新索引和接管信息。

## 三层结构

| 层级 | 内容 | 默认读取 |
|---|---|---|
| L1 Hot | START_HERE、AGENTS、CURRENT_STATE、活动批次摘要及选定索引 | 是 |
| L2 Task | 相关当前 Requirement+AC、Cxx 正文、相关 Decision、当前阶段/代码 | 由明确引用选择 |
| L3 Cold | 旧需求修订、已关闭批次/Change、开发日志、旧验收/包、完整测试/终端/浏览器证据 | 否，必须有检索原因 |

PROJECT.toml/角色边界/稳定执行契约在首次承担角色或规则发生变化时读取，不能因已读旧版本而忽略规则变化。索引是派生导航，不是产品事实源，不要把整个 .ai/context_index.json 发送给新执行器。

## PM 内部接口

```text
python tools/project.py ai-resume --json
python tools/project.py ai-context index --kind requirement --id R-001
python tools/project.py ai-context read --kind requirement --id R-001
python tools/project.py ai-context read --kind architecture --id C01
python tools/project.py ai-context read --kind decision --id DEC-YYYYMMDD-001
python tools/project.py ai-context refresh
python tools/project.py ai-context refresh --accept-changes --actor-role project_manager_agent --reason "已重读并核对变更正文"
python tools/project.py ai-context history --kind batch --id P1-001 --reason regression
python tools/project.py ai-context cold --path docs/logs/YYYY-MM.md --reason compatibility --offset 100 --limit 40
python tools/project.py ai-resume --mode full --full-reason stage_audit
```

内部命令由有本地能力的角色执行，用户不需要记忆命令。cold 支持行区间，read 精确返回完整选中正文；全文与摘要均不能跨越项目路径边界。history 返回精确版本或归档路径；二进制证据通过对应查看工具读取，不能把二进制当作文本解释。

## 引用格式

批次请求增加可选 context_refs：requirements=[R-001]、architecture=[C01]、decisions=[DEC-...]。Requirement 增加 module、summary、architecture_refs、decision_refs，属于语义，修改必须 revise。Architecture 使用 `## C01 | 名称`，其下可填写：

```text
<!-- CONTEXT: {"summary":"一句话职责","requirements":["R-001"],"code_paths":["src"],"decisions":[],"red_lines":["不可破坏的边界"]} -->
```

正文位置、AC、最近 Change、章节哈希自动生成。未指定引用不等于可以猜测范围，PM 必须根据 scope 补全；如果确实是无产品需求的治理维护批次，明确说明即可。旧内联 Decision 保留并按 ID 提取，新增 Standard Decision 保存到 docs/decisions。

## Freshness / 冲突

源内容变化使索引校验失败；ai-resume/refresh 可重建索引。活动任务绑定的相关正文变化仍标记 stale，必须 PM 确认后刷新。无关历史不会加入 must_read。health/Hook 阻止过期索引或无效引用；原有文档优先、语义锁和 Change 门禁仍独立执行。归档尝试、原始证据和读取回执不可通过刷新删除。

## 完整审查

仅允许 first_baseline、architecture_refactor、stage_audit、release_audit、fact_conflict、owner_request。完整审查不自动载入全部历史，历史仍精确追溯。审查后 ai-resume 回到 Hot/Task，结果压缩为当前事实和索引。

## 分层测试兼容

新 context_refs/Parent Batch/提升级别启用持久 layered_test_contract；阶段验收要求 L4 purpose=stage，发布要求 L5 purpose=release。ai-evidence 请求显式声明 purpose。旧请求保留原有严格 PASS/集成测试规则；新项目 PM 应使用精确引用启用新契约。证据记录源事实与实现指纹，代码或正式事实改变后重新验证，不能复用过期结果。

默认只读一份 manifest；HANDOFF_CURRENT 为替代导航，不与 CURRENT_STATE/manifest 叠加。README 字段说明仅建立/结束新契约任务时按节读取，排错节只在排错时读取；已读且未变不重复。完整最新检查点位于 active_batch.debug_checkpoint，CURRENT_STATE 只导航，旧尝试不进入 Hot。

V1.9.1 活动调查存在时，manifest.investigation 仅含当前边界状态和最新检查点；owner_decision_required 优先阻止自动继续。合同全文、coverage 和旧 raw 不进 Hot，按 README 对应节读取。
