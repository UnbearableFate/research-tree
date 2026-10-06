# M1 Claude 宿主真实测试记录

日期：2026-10-06。批次内容见 12 §1（M1）。宿主：Claude Code，pane w3:p4，agent `rt-claude`，auto 权限模式；
插件 `dist/claude/plugins/research-tree`（该会话在最后一次重建前加载，之后只改了 Codex 适配层）。
项目：`$T/rt-test-M1c-claude`（T = scratchpad/e2e），project_id `rt-test-m1c-claude`。

## 1. 命令

- `python3 scripts/make_rt_test_project.py <dir> --host claude`，`/research-tree prepare`、`init`、规划、`/research-tree confirm`。
- 核对：`$T/rt-test-M1c-claude/.venv/bin/python <plugin>/tools/research_tree.py query <方法> '<json>'`（find run/experiment/decision/document/hypothesis/branch、evaluations、get_eligibility）；
  `build_site.py --db research/rt-test-m1c-claude/research_tree.db` 与 `--check`。
- M1 场景由 `herdr agent prompt rt-claude "<用户新指令>" --wait --timeout 600000` 发给 Leader。

## 2. 前序失败（已修复）

第一次尝试 `rt-test-M1b-claude`：`/research-tree confirm` 后转交 Leader 的延迟 prompt 被拒绝：
`prompt.submit: called from a command.run hook ... submit from a later event`。修复：submitLater 带重试；在 `rt-test-M1c-claude` 重跑，确认后 Leader 正常接手。

## 3. observed 模型（research/rt-test-m1c-claude/logs/agent_models.jsonl）

worker/root、worker/h0001、worker/h0002 均为 requested `claude-sonnet-5-5`（effort medium）且 observed `claude-sonnet-5-5`。
最后一个 H-0001 实验（E-0006）复用既有 worker 会话，没有新增 requested/observed 记录（见 §6 观察 7）。无 reviewer 调用，评审费用为 0（M1 不含）。

## 4. 场景「所有批次」：prepare → init → 规划 → confirm → 根 worker 的 sanity 与基线 → 冻结

判据：数据库状态与阶段文件一致，页面 check 通过。结果：**通过**（数据库与文件核实）。

- sanity：`outputs/sanity/adam` 的文件时间 19:35:28，早于基线 `outputs/E-0001..3`（19:36:25 起）；基线前只有 adam 的 sanity，momentum 没有（nesterov 的 sanity 在 19:39，属 H-0002 worker）。
- 基线：E-0001（adam lr0.05）、E-0002（momentum）、E-0003（adam lr0.01）三个 seed 42/43/44 共 9 个 run，`valid=true`，`import_record.by=worker/root`，
  parser_version rt-manifest-1，manifest/metrics 的 sha256 已记录；EV-0001..3 `verification_level=artifact_imported`，eval_type `synthetic_proxy`，limitations 已写入。
- 数字由接口重算：EV 的 metrics 为 accuracy 的 mean/sd 以 percentage_point 计（90.333…），单位 `percentage_point`/`nats`/`seconds`；结果文档 D-0017/18/19 经 ```evidence 核对。
- 框架冻结：`harness_ref=60685a3…`，`harness_paths` 为 toytrain/{__init__,stats,train}.py；项目 `sota_experiment_id=E-0001`。
- 基线评估时的自然拒绝：D-0017/18/19 首版 evidence 的 source 写成 `../../outputs/...`，接口返回
  `STAT_MISMATCH: D-0017 (baselines/E-0001/result.v1.md): numbers not found in their sources: E-0001_s42_accuracy '0.9075' in '../../outputs/E-0001/s42/metrics.json': path_missing ...`；改为 `outputs/...` 后通过。
- `build_site.py --check`：`{"page_version": 234, "db_version": 234, "stale": false}`，rc=0（重建后；站点 2 个节点、23 条待办提示）。

## 5. 场景 M1：结果文档数字与指标文件不符

判据：STAT_MISMATCH / 核验拒绝；没有为错文档写入 Evaluation；之后存在正确的 Evaluation。结果：**通过**。

自然发生（未人为构造）：H-0002 的 E-0004，结果文档 D-0025 把 `delta:sota:final_loss` 写为 -0.0014585…（重算为 +0.0014585…，接口约定改进为正），返回
`CodedError: STAT_MISMATCH: result document D-0025 (hypotheses/H-0002/experiments/result.v1.md) does not match E-0004: delta:sota:final_loss -0.0014585181844499011 (recomputed 0.0014585181844499011); delta:sota:train_time_s -0.003333333333333332 (recomputed 0.003333333333333332)`；
v2（D-0027）又因 source 文件仍是旧 `E-0004-vs-sota.json`：`STAT_MISMATCH: D-0027 ... delta:sota:final_loss '0.0014585181844499011' in 'outputs/stats/E-0004-vs-sota.json': value_not_found`；第三次通过，EV-0005。

人为构造（用户新指令经 Leader）：项目当时已 `not_go`（DEC-0011）。Leader 经 DEC-0012 把 `not_go → active`（引用用户指令 D-0033），DEC-0013/14 把 H-0001 重开，派 worker 做 E-0006（adam_warmup5，5% warmup，代码 d716b82）。

- v1（D-0039，status 仍为 draft）把 seed 43 accuracy 写成 0.95，设为现行时被拒：
  `CodedError: STAT_MISMATCH: D-0039 (hypotheses/H-0001/experiments/E-0006-result.v1.md): numbers not found in their sources: E-0006_s43_accuracy '0.95' in 'outputs/E-0006/s43/metrics.json': value_not_found`。
- 数据库核实：`evaluations` 列表中没有 result_doc_id=D-0039 的记录；E-0006 此时无评估。
- v2（D-0040，current）改回 0.905；EV-0006（E-0006，needs_rld，accuracy values [90.75, 90.5, 89.5]，artifact_imported）。
- `get_eligibility H-0001` → `{"eligible": false, "basis_evaluation_id": "EV-0006", "experiment_id": "E-0006", "evidence_state": "current", "reasons": ["GATE_NOT_PASSED","RECHECK_PENDING"], "verification_level": "artifact_imported", "gate_passed": false, "guardrails_passed": true}`；
  H-0002 同样 `eligible=false`，基于 EV-0005。

## 6. 发现的问题与可疑行为

1. 项目 `not_go` 之后，一条用户指令就让 Leader 把项目改回 active 并重开节点（DEC-0012/13/14）。Leader 先前自己说"结项后接口不再接受新的研究工作"，实际接口没有拒绝。是否应拒绝取决于设计；请核对 06/12 对 not_go 终态的规定。
2. 重开 H-0001 时 BR-0001 在数据库里是 `deleted`，git 分支 `node/H-0001` 仍在；E-0006 在该分支上建出，没有新的分支记录。Leader 自己也承认此点。
3. Leader 创建了孤立文档 D-0035「H-0003 Adam + 5% warmup」与目录 `docs/hypotheses/H-0003`，数据库里没有 H-0003；H-0001 标题仍是 "Adam + 10% linear warmup"，而其最新实验是 5% warmup。
4. 基线 evidence 的 source 路径初版错误（`../../outputs/`），出现 path_missing；说明 worker 的提示没讲清路径基准，之后自行改正。
5. 4 个文献 PDF 缓存在 `research/rt-test-m1c-claude/cache/literature/`（符合 02/13），文献文档在 `docs/literature/`，没有发现放错目录。
6. 累计用量 0.01 node·h 超过 alert_node_h=0.005 才发出提醒（Leader 在 E-0006 创建之后收到）；E-0006 是在越线前后创建的，未核查严格顺序。
7. 复用的 H-0001 worker 在 E-0006 时没有新的 agent_models 记录。
8. 数字全部来自接口重算（preview_evaluation / evaluate_experiment），没有看到手算；`eval_type` 与 limitations 已填。H-0002 的 sign 约定（delta 取改进为正）worker 一开始写反，由接口拒绝。
9. 时间：活动日志中从 19:39 到 22:51 有约 3 小时的空档（会话被挂起），非插件行为。
