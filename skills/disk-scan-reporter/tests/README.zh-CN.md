# 测试

`test_disk_scan.py` 涵盖分类、排除规则、链接处理、深度、文件/时间预算、覆盖状态、记录限制、路径隐私、报告渲染、CLI 失败状态、错误类别、分配大小、硬链接去重、JSON 往返、未知 schema 拒绝以及无删除契约。

`test_audit_guard.py` 涵盖破坏性 API 检测、允许的写入根目录、接合点（junction）逃逸拒绝以及浅层快照比较。

运行方式：`python -m unittest discover tests`。
