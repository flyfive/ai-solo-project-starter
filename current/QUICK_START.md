# V1.9.2 快速开始

1. 进入自己克隆或解压的 current 目录，打开 [使用说明.html](使用说明.html)。预填和留空回退都是作者示例，必须核对并填写自己的实际模板路径；目标目录保持独立。
2. 填写新项目名称、简介、目录、类型和 Lite/Standard/Auto。
3. 把初始化提示词交给具备文件、终端和 Git 权限的 PM。
4. 打开生成的新项目，发送：读取 START_HERE，按 Hot/Task/Cold 协议接管，先确认当前需求及活动批次引用。

初始化会验证配置、Git、初始提交、Hook 与索引。Lite 初始23文件，Standard36文件（各含一份模板许可声明）。Auto 不是第三模式。没有正式交付的小型自用工具优先 Lite；长期或正式交付项目选择 Standard。

日常只告诉 AI 需求与反馈。新执行器先取得 CURRENT_STATE 和 CONTEXT_LOAD_MANIFEST，按本批 R/C/DEC 读取正文；不要默认全文读取需求、架构、决策或日志。任务相关正文变化后先让 PM 重读刷新。

Lite 变大时由所有者明确授权升级 Standard，保留原目录、Git和历史；被阻塞批次可安全挂起，升级审计通过后恢复。该操作仍不同于旧 V1.8.1 项目的跨版本迁移，后者见人工迁移指南。

正式交付仍需 ready 交付物、变更后重新验收、已结案清单不改写；继续开发以更高版本显式重开。

目标目录必须是独立的新项目目录，不在工作区根目录或 current 内初始化业务项目。维护工具自身时按仓库入口继续，日常只维护 current；上述治理及交付说明不作为工具自身每次小改动的交付门槛。

工作区测试从 current 运行 `python -B run_tests.py --report-dir ../validation/local-run`，原始输出不写入源码目录。

运行需 Python 3.11+ 与 Git，完整测试另需 Node.js 24。采用 [MIT](LICENSE)，署名 FeiXiaorong；生成材料及业务代码边界见 [许可说明](LICENSE_STATUS.md)。

V1.9.1 的可选验证设施合同及调查止损见 [设计与实际验证](TEST_INFRASTRUCTURE_DESIGN.md)；旧项目先读 [人工升级与迁移](UPGRADE_V1.9.1.md)。初始化文件数不变，旧请求没有被自动赋予新保障。

## V1.9.2 Standard 非成功交接

Standard 的 BLOCKED/PARTIAL 可在无未关闭 Change、具名继任已定义且所有者强绑定授权后使用 `ai-handoff-batch`。责任移交不是 PASS，不更改需求或验收；下一次只能启动冻结的继任。原 Lite 升级挂起及旧请求不变。见 [设计](STANDARD_BATCH_HANDOFF_DESIGN.md)、[缺口分析](STANDARD_BATCH_HANDOFF_GAP_ANALYSIS.md)和[人工升级](UPGRADE_V1.9.2.md)。生成项目字段按需读其 README。
