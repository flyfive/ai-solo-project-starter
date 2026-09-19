# V1.8.x / V1.9.0 → V1.9.1 人工升级与迁移

可以继续原版，不必为了模板新能力迁移接近完成的项目。没有自动迁移器，本轮未访问/修改任何真实项目。

1. 保存 Git HEAD、未提交文件、需求/AC/revisions、活动状态、原始证据、发布冻结记录和项目扩展的完整备份。
2. 在独立临时目录初始化相同模式/profile 的 1.9.1 参考项目，只作比较。不要在真实项目执行 starter init。
3. **不得直接复制 PROJECT.toml 或 project.py 覆盖真实项目。** 对旧模板原版、项目现状、新模板做三方合并；project-specific governance extensions 同样三方合并，包括 context_engine、Hook、配置、模板包和规则。没有原版对照或扩展来源不明则停止合并。
4. 保留旧 schema、需求永久 ID、Git、状态、语义锁、全部修订和所有历史证据。新模板版本为 1.9.1，兼容 state/bundle schema 仍为 1.9.0；不要仅改字符串冒充迁移完成。
5. Candidate/Harness/Contract/Evidence 分层是治理能力升级，**不允许因此重写旧测试历史**。旧请求/证据走原契约；只有新任务显式绑定 acceptance/1 才取得新保障。旧 PASS 不自动满足新类型/合同，新合同使用新 run。失败/阻塞原件永久保留。
6. 合并各项授权/限额/角色策略，重新核对 Lite 隐藏 Standard 模板包哈希，保持原 Lite→Standard 授权及基线审计。不要移除旧 Change 或活动批次解除阻塞。
7. 在备份分支运行原项目测试、health、Hook、接管/上下文失效、需求历史比对，以及本项目适用的新合同/止损用例；得到所有者决定后才切换。
8. 回退到备份工具/规则/配置与相容状态；新运行证据另行保留，不能通过 Git reset/覆盖目录删掉期间原始证据。

兼容范围：旧 V1.8.1-compatible batch/request、旧 ai-evidence run/import 和旧实现 fingerprint 保持；不宣称任意自定义工具补丁可以无冲突升级。仅更改验收设施不要求候选假 revision，但产品/安全语义改变继续 Change/revise 并验证受影响行为。新本地工具不是操作系统沙箱，也不能自动识别所有未申报范围扩张。
