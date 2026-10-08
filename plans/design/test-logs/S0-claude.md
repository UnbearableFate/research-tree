# S0 Claude Code 真实场景记录

宿主 Claude Code 2.1.294，主会话 `claude-haiku-5-5`（会话记录中 effort medium），`--permission-mode auto`，经 Herdr pane
启动；插件为构建快照 `--plugin-dir <dist 快照>/plugins/research-tree`。项目均由 `make_rt_test_project.py` 新建（ToyOpt Lab），
控制器文件在项目外 `<项目>.ctl/`；原始会话、运行文件与观察器输出的位置见各记录 `record.json`（持久目录
`/home/yu/workspace/rt-scenarios/S0/`）。

| 尝试 | 源码 | 结果 | 说明 |
| --- | --- | --- | --- |
| a01 | `3375c8d` + S0-r1 修复（未提交前的工作树，见 source_ref） | PASS（被 a02 取代） | 之后共享代码又改（冻结前改 repo_path、update_task 指派重述），按 §2.6 在最终构建上重跑 a02 |
| a02 | `7047965`（最终 S0 构建，调度服务模式） | PASS | 记录：`scenarios/S0/claude/*/a02/record.json` |

## a02 过程（用户输入见 commands.jsonl）

1. `/research-tree prepare` → `/research-tree init`：RLD（Haiku）写目标、最小设定、协议（synthetic_proxy）、文献与 H-0001，请求确认。
2. 用户要求“基线导入并 valid 后暂停，不写结果文档、不 evaluate”，随后 `/research-tree confirm`。
3. 根 worker 经 `tools/local_exec.py`（调度服务）运行框架 sanity 与 3 个 seed 的参考方法；导入后暂停。观察器：3 个有效 run 的
   DB 值与独立 scorer 完全一致（0.805 / 0.7525 / 0.8175），曲线步数、模型、预测与实测 usage 齐全。
4. SC-S0-02：用户交出写错的报告（s42 写 0.905、均值 82.5）。RLD 原样登记为草稿后 `set_document_current` 被接口以 STAT_MISMATCH
   拒绝，`evaluate_experiment` 因结果文档非现行被拒；没有产生 evaluation。修正版登记后评估为 EV-0001，均值 79.16666666666667 pp，
   与独立重算一致；E-0001 设为 SOTA。
5. `/exit` 后新会话：`/research-tree status` 与“恢复当前工作”只读核对，未启动新运行（启动账本与 run 列表不变）；`/research-tree build`、
   `check` → page_version = db_version = 73，未过期。

## 观察到的问题与处理

- 根 worker 在数据库之外跑了框架 sanity 与一次 seed 42 重复检查（5 次进程启动中 2 次无 run 记录）。观察器如实计入；本项目未设
  total_limit，接口不要求预留。属于 agent 行为，记录为遗留观察，S6 的作业计量场景再检验。
- a01 中发现：项目创建时 repo_path 指向项目根目录（prepare 的 uv init 产生的空 git 仓库），冻结前无法单独更正 → 已修复（`b45974c`，
  冻结前且无实验时可单独设置 repo_path；REG `HarnessSanityFirstTest.test_repo_path_can_be_corrected_before_the_freeze`）。
