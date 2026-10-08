# 交接文档：research-tree 证据一致性改进轮（S0–S7）

交接时间：2026-10-08。分支 `bug-fix-1008`（起点 `253d50d`）。任务定义：
[`plans/research-tree-implementation-and-real-scenarios.md`](plans/research-tree-implementation-and-real-scenarios.md)（下称实施文档）。
状态总表与缺陷映射：[`plans/design/test-logs/implementation-status.md`](plans/design/test-logs/implementation-status.md)。

**结论先行：S0 尚未完成终审，S1 有未提交的半成品（git stash），S2–S7 未开始。** 不要把任何阶段报告为 PASS。

## 1. 当前状态

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| S0 | IN_PROGRESS | 实现、REG、两端真实场景（a02）已完成；Fable 终审 `S0-r3` 给出 3 MAJOR，修复已提交（`249870a`），但**需要在新构建上重跑两端场景（a03）并再做一次终审** |
| S1 | IN_PROGRESS（未提交） | 代码在 `git stash@{0}`（"S1 WIP: identity, claim revisions, review basis"），既有测试已调通，S1 的 REG 与场景尚未写 |
| S2–S7 | NOT_STARTED | — |

## 2. S0 已完成的内容（已提交）

- 场景底座（`scripts/scenarios/`，说明见其 README）：ToyOpt Lab 生成器（`scripts/make_rt_test_project.py`，固定切分 train/explore/c1/c2 及内容身份、真实 CPU 训练、写 manifest 的 runner、冻结参考方法）；本地执行适配器 `local_exec.py`（按 key 幂等、实测用量、故障窗口、**调度服务模式 `serve`**——Codex 沙箱会杀死命令的子进程，必须由控制器在沙箱外运行 `python3 tools/local_exec.py serve`）；独立 scorer；只读 observer；`record.py`（记录校验：观测模型/effort、会话原文、恢复前后 observer、真实 reviewer 等）。
- REG-S0-01..05 与适配器测试：`tests/test_scenarios.py`。
- `plans/real-run-error.md` #1–#19 全部修复并有测试，映射表在 implementation-status.md。
- 场景中发现并修复的产品缺陷：冻结前可单独更正 `repo_path`；Codex 立项提示补上生效的 `db_fields`；`update_task` 重述自己的指派不再被拒；Codex 新主会话 SessionStart 时告知如何 `research_control attach` 接管。
- 证据：`plans/design/test-logs/S0-claude.md`、`S0-codex.md`、`scenarios/S0/**/record.json`；评审 `plans/design/reviews/S0-r1..r3.md`；预检原始输出 `test-logs/S0-precheck/`。

## 3. S0 剩余工作（按顺序）

1. **处理 S0-r3 未修完的项**（见 `plans/design/reviews/S0-r3.md` 的发现列表，“修复对照”一节尚未填写）：
   - MAJOR 1：原始证据必须进仓库（或带校验和的持久位置 + 已提交索引）。`scripts/scenarios/s0_records.py` 目前只复制 4 个小文件；需要把 observer-final / observer-before-resume / observer-after-resume / db-snapshot / launches.jsonl / 会话原文（可 gzip）放进每个 attempt 目录，记录里用仓库相对路径。
   - MAJOR 2：observed_effort 要从会话原文读取（Claude 会话 jsonl 里有 `"effort":"medium"`；Codex 会话里有 `reasoning_effort`）；恢复证据要用恢复前后两份 observer 计算（`record.py` 已强制要求 `observer_before/observer_after`）。C1 断言改为只由 commands.jsonl 计算；R1 的“产品拒绝”要从会话原文里取 STAT_MISMATCH 文本作证据。
   - MAJOR 3：Codex 恢复必须经插件的接管入口（`research_control attach`）。hook 已修（`249870a`），需在新项目重测。
   - MINOR：已修 scorer 计数、effort 依据、文档；尚未处理的：s0_records 的 C1/R1、Codex a02 中途替换 `tools/local_exec.py` 的说明（sha 与原因）、S0-claude.md a01 的源码行、构建日志（命令、退出码、BUILD.json、测试数）进 test-logs。
2. **重跑两端 a03**：`scripts/scenarios/run_s0.sh <claude|codex> 03 <agent-pane> <scheduler-pane>`（需在 Herdr 内运行；它生成新项目、复制构建快照、启动调度服务与宿主、按固定用户输入走完 SC-COMMON-01 + SC-S0-01/02，恢复前后各存一份 observer）。本次交接前**尚未运行过该脚本**，首次运行请盯着看。辅助脚本 `say.sh`、`waitidle.sh`、`drive_codex.sh` 同目录（路径写死为 `/home/yu/workspace/rt-scenarios/`，用前检查）。Codex 运行需要批准插件 MCP 工具与插件自带脚本的沙箱外执行，`drive_codex.sh` 只自动批准这两类并记入 commands.jsonl。
3. 改 `s0_records.py` 生成 a03 记录 → `python3 scripts/scenarios/record.py summary` 全部 valid。
4. 终审：`python3 scripts/stage_review.py S0 --round 4 --final --design plans/research-tree-implementation-and-real-scenarios.md plans/real-run-error.md --base 253d50d --tests … --evidence …`（Fable 5.1，约 6 USD/次，30 分钟内）。无 CRITICAL/MAJOR 后把状态表 S0 改为 PASS 并提交。
   - 注意：reviewer 以只读工具在仓库 cwd 运行，**读不到仓库外的 `/home/yu/workspace/rt-scenarios`**，所以证据必须在仓库里。

## 4. S1 半成品（stash@{0}）

恢复：`git stash pop`（S0 收尾后再做，避免 S0 场景构建混入 S1 代码）。内容：

- schema v15（`research_tree.sql`、两处 `SCHEMA_VERSION`）：experiment 的 `method_spec_doc_id/method_spec_sha/effective_config/sanity_target_spec_doc_id/sanity_overrides/code_review_waiver_basis`；hypothesis 的 `claim_revision/claim_sha/claim_history`；document 的 `review_basis/review_basis_changed`；decision 的 `basis`；新 doc_type `method_spec`。
- `research_db.py`：`create_experiment(method_config=, sanity_overrides=)` 解析有效配置并登记内容寻址的 method_spec（缺配置 → `METHOD_SPEC_INCOMPLETE`；执行字段见 `EXECUTION_FIELDS`）；导入时 manifest 配置与 spec 不符 → `METHOD_SPEC_MISMATCH`；`update_hypothesis` 产生 claim revision；`review_basis()`（只读）与 `_review_bound()`；`_candidate_rechecks`、`_latest_code_review(exp)`、`_waiver_bound`、sanity 投影、RLD 复核决定的 basis 都改为按当前依据比较；`register_review(basis=)` 比较调用前后依据。
- `discovery.py`：候选 ID 稳定（显式 id → 同 origin+dedup_key → 新号，永不按排序重编号），内容 revision/`content_sha`，缺席候选保留为 `present: false`；`receipt_applies` 只认当前 revision 的回执（门与 `create_hypothesis` 都用）。`review_call.py` 在调用前捕获 basis 并传给登记。
- 测试夹具已改（`METHOD_CONFIG`、评审辅助函数传 `basis`），共享测试全部通过（未加 S1 新测试时）。
- **还没做**：REG-S1-01..06；迁移方法（实施文档 §5.3：旧评审 → needs_recheck、旧实验 legacy_unbound、幂等）；`create_db.upgrade_db` 已会把版本升到 15 但没有数据迁移；两端提示词（先建实验登记 spec 再做 code_review；method_config/sanity_overrides 用法）与工具 schema/只读白名单（`review_basis` 已加入 `READ_METHODS`，适配器侧未查）；resume_package/页面展示失效依据；`make_demo.py` 的 create_experiment 调用需要补配置；规则与 README 同步；然后 S1 的 Fable 评审与两端 SC-S1-01..03。

## 5. 环境与约定

- 测试命令：共享 `.venv/bin/python -m unittest discover -s shared/research-tree/tests`（约 5 分钟，326 项）；`tests/`；`python3 scripts/build_plugins.py --target all`；`claude plugin test dist/claude/plugins/research-tree`；`.venv/bin/python -m unittest discover -s dist/codex/plugins/research-tree/tests -p test_codex_adapter.py`；`scripts/check_codex_install.py dist/codex`。
- 模型矩阵（以实施文档 §2.2 的最后修订为准，effort 均为 medium）：Claude 宿主 `claude-haiku-5-5`、reviewer `openai/gpt-6-luna`（pi）；Codex 宿主 `gpt-6-luna`、reviewer `anthropic/claude-haiku-5-5`（Claude CLI）；阶段评审 `claude-fable-5-1` high。
- 场景项目与原始证据在 `/home/yu/workspace/rt-scenarios/S0/`（每个项目旁有 `.ctl/` 控制器目录、构建快照 `dist-*`、隔离 `codex-home-*`，后者含登录副本，用完应删除）。
- 资源边界、预算与 effort 依据见 implementation-status.md。旧设计包已被用户移出工作树，需要时从 `616d646` 读取。
- 每阶段末按 AGENTS.md：两端真实场景 + Fable 终审后才提交为完成；`codegraph sync` 保持索引更新。
