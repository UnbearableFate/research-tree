# S0 构建与测试日志

源码：`af603a4aa7295a002c39f01b350904e5d7f91b8c`（未提交：5 个文件，均为记录/文档）；时间 2026-10-08T18:40:41Z；机器 fern01。

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `python3 scripts/build_plugins.py --target all` | 0 | claude: 63 files; /home/yu/workspace/research-tree/dist/research-tree-claude-0.1.0.zip codex: 71 files; /home/yu/workspace/research-tree/dist/research-tree-codex-0.1.0.zip  |
| `claude plugin validate dist/claude` | 0 | ✔ Validation passed  |
| `claude plugin validate dist/claude/plugins/research-tree` | 0 | ✔ Validation passed  |
| `claude plugin test dist/claude/plugins/research-tree` | 0 |  33 pass  0 fail Ran 33 tests across 1 file. [0.55s]  |
| `.venv/bin/python -m unittest discover -s dist/codex/plugins/research-tree/tests -p test_codex_adapter.py` | 0 | Ran 29 tests in 11.317s OK  |
| `.venv/bin/python scripts/check_codex_install.py dist/codex` | 0 |   "tools": 6,   "evidence": "/tmp/research-codex-install-u_5z18a_"  |
| `.venv/bin/python -m unittest discover -s tests` | 0 | Ran 20 tests in 8.062s OK  |
| `.venv/bin/python -m unittest discover -s shared/research-tree/tests` | 0 | Ran 326 tests in 333.295s OK  |

BUILD.json：

```json
{
 "target": "claude",
 "name": "research-tree",
 "version": "0.1.0"
}
```
