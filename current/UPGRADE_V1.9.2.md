# 人工升级到 V1.9.2

这是向后兼容新增能力，旧项目不使用交接时无需迁移数据或增加 PROJECT.toml 必填字段。产品 template_version 为 1.9.2；配置/状态 schema_version 保持 1.9.0。只有需要 Standard non-success handoff 才使用 ai-handoff-batch；Lite 升级挂起语义不变。

可继续原版；需要能力时，先保存 Git 分支/完整备份，再将原模板、当前项目及新模板三方合并。至少关联检查 tools/project.py、tools/context_engine.py 和相关规则/README；不得直接复制整个 project.py 或 PROJECT.toml 覆盖真实项目。项目专属治理扩展必须人工保留并验证。不得覆盖已有 LICENSE、需求、状态、Git、未关闭 Change 或历史证据。

BLOCKED/PARTIAL 先保留真实尝试；无 open changes 时，由 PM 根据所有者对源和具名继任的明确授权登记交接。交接不是 PASS，不能迁移未关闭 Change 或跳过验收。继任合同与授权引用在启动前必须仍保持冻结哈希；如不一致，停止并由所有者决定，不手工删除锁绕过。

升级验证：旧请求、正常 PASS、未完成记录、验收返工、Lite→Standard、health/pre-commit，以及 Standard 交接→具名继任事务闭环。旧证据不重写，不把历史结果升级成新增保障。本模板不会自动迁移任何真实项目。

详细语义见 [交接设计](STANDARD_BATCH_HANDOFF_DESIGN.md)，字段与命令见生成项目 README 的“Standard 非成功批次交接”。
