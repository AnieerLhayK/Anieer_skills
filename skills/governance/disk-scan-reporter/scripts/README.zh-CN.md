# 脚本

`disk_scan_report_runtime` 是 Workspace 支持的入口。从 Workspace 根目录传入当前 session ID；它会创建独立 TASK 和限定到报告目录的 lease，调用 `disk_scan.py`，执行 30 天报告保留规则，并记录回执。扫描器 CLI 的 `--record-id` 和 `--lease` 由该受管 runtime 提供。

`disk_scan.py` 执行有边界的只读元数据扫描，并生成 Markdown 和带 schema 版本的 JSON 报告，包含分类错误、每个根目录的覆盖率、逻辑大小和分配大小，以及硬链接感知的字节总数。

`disk_scan_manual.py` 处理显式 `--deep-scan` 请求：不重跑盘点、不受自动晋级条件限制，目标共享总预算；保留源码仓库、保护路径和链接边界。清理由独立的 Workspace 执行器处理，入口见 `references/cleanup.md`，不进入只读扫描器的审计源码范围。

`init_config.py` 从 Git 样例创建外部扫描配置，或通过 `--migrate-current` 复制当前配置；外部写入前必须用 `--record-id` 和 `--lease` 提供有效的 `external_write` TASK 与 lease，已有外部文件时拒绝覆盖。活动审计策略必须与审查过的模板一致；`--sync-audit-policy` 需要明确确认，并在覆盖前创建、验证回滚副本。

`audit_guard.py` 静态检查生产脚本中已配置的破坏性操作，将报告写入限制在已批准的根目录，并提供浅层的前/后快照辅助工具。

两者均从技能目录运行，详见 `SKILL.md`。
