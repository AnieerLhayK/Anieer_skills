# Disk Scan Reporter（磁盘扫描报告器）

`disk-scan-reporter` 是一个只读的 Windows 磁盘用量诊断技能。它仅扫描已配置的路径，读取文件系统元数据，对手动审查候选对象进行分类，并输出一份人类可读的 Markdown 报告和一份机器可读的 JSON 报告。

它从不删除、移动、重命名、压缩、截断或修改用户文件。它不运行清理工具、不请求管理员权限、不更改系统设置，也不创建缺失的扫描目标。

## 运行

从本技能目录执行：

```powershell
python scripts/disk_scan.py --config config/scan_config.json
```

可选控制参数：

```powershell
python scripts/disk_scan.py --config config/scan_config.json --output reports
python scripts/disk_scan.py --config config/scan_config.json --max-depth 6
python scripts/disk_scan.py --config config/scan_config.json --json-only
python scripts/disk_scan.py --config config/scan_config.json --md-only
```

输出目录在需要时会自动创建。未指定 `--output` 时，扫描器依次使用
`AI_TOOL_STAGING_DIR`、Workspace 的 `runtime_roots.staging` 配置、系统临时目录，
并在其中使用 `disk-scan-reporter/` 子目录。显式输出仍沿用原有的策略批准根目录检查。
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

## 阅读报告

每次运行都会在解析后的输出根目录下写入带时间戳的文件：

```text
disk-scan-reporter/disk_report_YYYY-MM-DD_HHMMSS.md
disk-scan-reporter/disk_report_YYYY-MM-DD_HHMMSS.json
```

schema 2.0 的 Markdown 报告分别展示盘点下界、路径策略与晋级决定、深扫覆盖和人工审查候选；盘点使用盘符标签，深扫使用晋级根相对路径。

JSON 报告声明 `schema_version`、`tool_version` 和确定性的 SHA-256 `config_fingerprint`。读取器兼容历史 schema 1.0；新报告使用 schema 2.0，并应按 `references/report_schema.json` 校验。

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

源代码包位于清单相对路径 `skills/disk-scan-reporter` 下。`workspace_manifest.yaml` 注册了其角色、只读审计权限、报告写入执行模式、必需文件以及 Codex 暴露。清单投影将 Codex 加载表面指回此单一源目录；平台目录不是独立副本，不得直接编辑。

## 未来自动化

后续经过单独审查的自动化可以调度相同的只读命令，仅发送摘要。可能的扩展包括与先前报告的比较、新添加的大文件、增长最快的目录以及每周摘要投递。任何未来的自动化都必须保留不清除的边界，并且不得将建议转化为删除操作。
