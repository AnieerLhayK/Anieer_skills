# Disk Scan Reporter（磁盘扫描报告器）

`disk-scan-reporter` 检查 Windows 磁盘用量，支持明确指定目录的只读深扫，并可在原 chat 中执行用户明确批准的精确清理批次。扫描器读取文件系统元数据，输出 Markdown 和 JSON 报告。

扫描器不修改被扫描文件、不提权、不更改系统设置，也不创建缺失目标。清理由独立的 Workspace 执行器在用户批准后完成，详见 [cleanup.md](references/cleanup.md)。

## 运行

从本技能目录执行：

```powershell
python scripts/disk_scan.py --config config/scan_config.json
```

可选控制参数：

```powershell
python scripts/disk_scan.py --config config/scan_config.json --max-depth 6
python scripts/disk_scan.py --config config/scan_config.json --json-only
python scripts/disk_scan.py --config config/scan_config.json --md-only
python scripts/disk_scan.py --config config/scan_config.json --deep-scan "D:\Dev\package-cache"
```

输出目录在需要时会自动创建。未指定 `--output` 时，扫描器依次使用
`AI_TOOL_STAGING_DIR`、Workspace 的 `runtime_roots.staging` 配置、系统临时目录，
并在其中使用 `disk-scan-reporter/` 子目录。显式输出仍沿用原有的策略批准根目录检查，
以兼容既有调用方；新自动任务应省略 `--output`，将报告保存在 source 之外。
缺失的扫描根目录不会被创建，而是记录在 `skipped` 下。

## 配置扫描

默认两阶段字段见当前 `config/scan_config.json`；以下字段仅适用于兼容的单阶段 `scan_paths` 配置：

- `scan_paths`：要检查的显式根路径。环境变量（如 `%USERPROFILE%` 和 `%LOCALAPPDATA%`）会被展开。
- `exclude_paths`：要跳过的绝对路径或目录名称。
- `large_file_mb`、`very_large_file_mb`、`old_file_days`：分类阈值。
- `max_depth`：在每个已配置根目录下的递归深度限制。
- `follow_symlinks`：默认为 `false`；除非明确需要遍历链接，否则保持为 false。
- `max_report_items`：限制详细候选记录的数量，而汇总计数器继续反映整个扫描结果。
- `max_diagnostic_items`：独立限制存储的错误和跳过路径详细信息的数量，同时保留总计数器。
- `max_files_per_run`：在达到配置的观察文件数量后停止遍历，并报告 `PARTIAL_BUDGET_EXHAUSTED`。
- `max_scan_seconds`：限制整个运行的经过遍历时间。
- `audit_policy`：指定同一配置目录中的策略文件名。
- `report_path_mode`：默认为 `relative`，将本地绝对路径替换为带编号的扫描根标签。仅在报告将保留在本地且需要精确路径时设置为 `absolute`。

默认配置使用 `two_stage_plan`：先以 C=3 层、60 秒/10 万文件，D=4 层、120 秒/20 万文件做盘点；这些目录用量都是已观测下界。C 盘严格超过 4 GiB、D 盘严格超过 8 GiB 的合资格目录才晋级完整递归深扫，每个目标最多 180 秒/10 万文件，整次最多 15 分钟。系统路径和链接不遍历；应用、开发根目录与 `${LOCAL_PATH}` 仅盘点，绝不自动晋级。旧的 `scan_paths` 单阶段配置仍受支持。

明确请求 `--deep-scan` 时，仅扫描指定的绝对目录，可重复传入多个目标；不重跑盘点，可越过大小阈值和 `review_only`。整批共享 900 秒／50 万文件上限，不受原单目录预算限制。此只读请求免 TASK，不重复请示，也不改变今后自动扫描范围。系统保护、链接、`.git`、源码仓库及配置排除项仍有效；总预算耗尽后直接给出部分结论和未覆盖范围。

## 阅读报告

每次运行都会在解析后的输出根目录下写入带时间戳的文件：

```text
disk-scan-reporter/disk_report_YYYY-MM-DD_HHMMSS.md
disk-scan-reporter/disk_report_YYYY-MM-DD_HHMMSS.json
```

schema 2.0 的 Markdown 报告分别展示盘点下界、路径策略与晋级决定、深扫覆盖和人工审查候选；盘点使用盘符标签，深扫使用晋级根相对路径。

JSON 报告声明 `schema_version`、`tool_version` 和确定性的 SHA-256 `config_fingerprint`。读取器兼容历史 schema 1.0；新报告使用 schema 2.0，并应按 `references/report_schema.json` 校验。

工具 2.1 在 schema 2.0 中增加可选的 `run_mode` 与 `request` 字段。手动报告标记盘点为 `not_run`、深扫为 `manual_shared_budget`，记录相对盘符的请求目标和共享预算；指纹包含实际请求及预算。历史 1.0 与自动 2.0 报告仍可读取。

使用默认的相对路径模式时，`<scan_root_1>` 等标签映射到本地配置中按顺序排列的 `scan_paths` 条目。这减少了报告共享时用户名和本地布局的泄露。相对模式并非匿名化：每个根目录下的文件名和目录名仍可能包含敏感信息。

## 安全与覆盖审计

使用以下命令运行独立的静态审计：

```powershell
python scripts/audit_guard.py
```

`config/audit_policy.json` 定义了生产源代码根目录、破坏性 API 和命令标记、允许的运行时写入根目录以及浅快照行为。如果静态审计发现配置了破坏性操作，扫描器将默认失败关闭。显式报告输出仅接受在 `reports/`、`state/` 或 `logs/` 下；解析出的默认 staging 目录会被单独加入允许列表。两类路径都同时进行词法和解析路径的包含检查。

每份报告包含每个根目录的覆盖信息：

- 遍历是否已启动并完成；
- 观察到的文件和目录数量；
- 深度、排除、链接、重复和不受支持条目的跳过情况；
- 权限、未找到、中断、元数据和未知错误；
- 从字节总数中排除的硬链接重复项；
- 文件/时间预算耗尽情况；
- 覆盖状态，如 `COMPLETE_WITHIN_CONFIG`、`PARTIAL_WITH_EXPLAINED_SKIPS`、`PARTIAL_BUDGET_EXHAUSTED`、`PARTIAL_PERMISSION_LIMITED` 或 `FAILED`。

覆盖范围是根据已配置的根目录和预算进行评估的，而不是针对整个驱动器。请参阅 `references/coverage_schema.md`。

可选的直接子级前后快照记录计数、根目录修改时间和名称哈希。它可以标记明显的并发更改，但无法证明没有文件内容发生变化。

风险含义：

- `LOW`：相对常见的审查候选对象，但仍从不自动清理。
- `MEDIUM`：在考虑任何操作前检查所有权和当前使用情况。
- `HIGH`：不确定、与依赖相关，或未经仔细手动审查则不安全的项目。
- `DO_NOT_TOUCH`：系统、源代码控制或明确受保护的内容。

任何风险标签都不等于删除许可。自动清理无法安全地从文件元数据推断所有权、可恢复性、活跃使用或业务价值。

## 工作区集成

源代码包位于 `skills/governance/disk-scan-reporter`。分类注册表记录默认审计权限、明确批准后的清理权限、执行模式、必需文件和 Codex 暴露；平台目录不是独立副本，不得直接编辑。

## 每周扫描与后续处理

每周任务自动只读扫描，每次提供覆盖和候选摘要。你可在结果所在 chat 中直接要求定向深扫。清理前会展示精确路径、逐项删除方式、影响及恢复／备份状态；你一次批准后原 chat 执行，Codex 自动办理 TASK、最长一小时的精确路径租约、复查及关闭。移入回收站通常不释放所在磁盘空间。批准不延续到下一次周任务。
