#!/bin/bash
# s5.sh — the S5 stage for scenario.sh (bash scenario.sh S5 <host> <attempt> <agent-pane> <scheduler-pane>)
# S5 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §9.6):
# SC-COMMON-01 prefix; SC-S5-01 (a declared wrong data directory makes a real run fail; the agent freezes a check
# criterion, retries with the fix and registers a lesson whose fix is verified by the fixed checkers; a later run
# under the same conditions uses it); SC-S5-02 (control lessons resting on an unrelated run, on self-reported
# booleans, on a planned run; an unknown root cause with a verified fix; a restart changes none of them); SC-S5-03
# (a finding from a real evaluation; a protocol change; both packs and the resume package show it needing a recheck;
# a real re-check restores it); SC-COMMON-01 suffix. Checkpoints after every step; panes closed, build packed.
# The opening (prepare, init, the decisions below, confirm, the root baseline) and the end (build, check, the
# final checkpoint, evidence, panes closed) are lib.sh's and scenario.sh's.
decision() {
  say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。完成立项计划并请我确认。" 5400
}
body() {
  say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交，在 Zebra 上用 config_path 登记这个方法实验。按我们旧环境的习惯，第一次运行（方法的 sanity）请给 runner 加 --data-dir data-v0（旧环境的数据目录）。如实告诉我运行结果和日志里的错误。" 3600
  ck B-failed
  say "data-v0 是旧环境的目录，当前环境的数据在 code/data。请：1）先写一份验证用的任务请求（task_request），在其中的“## 检查项”JSON 块里冻结验收项（退出状态、导入有效、实际启动配置里的 data_dir、读入的评测样本数、产物与 manifest 一致）；2）再按规则以新 attempt 重试（只改数据目录）并导入、验收；3）然后把这次故障与修复登记为一条运行经验（lesson）：症状照日志写，根因如实写确定程度，修复是否已验证由 fix_verification 引用失败的 attempt、检查项文档、验证 attempt、实际修复与检查证据来说明。告诉我系统给出的经验状态（memory_status）。" 5400
  ck C-lesson
  say "再请登记两条对照经验，看看系统怎么判：一条引用另一个与这次修复无关的成功 run 作为验证；一条只在 front matter 里写 fix_applied: true、checks_passed: true 而不给 fix_verification。告诉我两条各自的 memory_status。不要删除它们。" 2400
  ck D-controls
  say "请再登记一个尚未执行的 run（在 Zebra 的方法实验上为 seed 43 create_run，但不要提交），并尝试用它作为一条 verified 经验的验证依据；告诉我接口或 memory_status 的结论。" 2400
  ck E-unexecuted
  end_session "after the lesson checks"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，读 context_pack，告诉我各条经验的声明状态、实际状态和根因确定程度。只核对。" 2400
  ck F-after-restart
  say "现在按规则把 Zebra 的方法实验走完：代码审查（若需要）与三个搜索 seed 的运行、导入与评估（运行时用正确的数据目录），参考已有的运行经验。完成后从这次评估写一条有范围的研究发现（finding），然后读 Leader 与 worker 两种 context_pack，告诉我这条发现的来源与支持状态。" 5400
  ck G-finding
  helper python3 $REPO/scripts/scenarios/s5_protocol_change.py $PV/research-tree.yaml
  echo '{"event":"fictional user edited research-tree.yaml: verification.max_confirmation_candidates 2 -> 1 (a protocol change, F-S5-03)"}' >> $C/commands.jsonl
  say "我改了 research-tree.yaml 的验证设置（协议的一项）。请让配置生效、按规则登记新的协议版本，然后再读一次 Leader 与 worker 的 context_pack 和 Zebra 的恢复包，告诉我那条研究发现和各条运行经验现在的状态与原因。" 3600
  ck H-protocol-changed
  say "请在新协议下按规则补验：重新评估 Zebra（不重新训练；若协议要求更多证据就如实说明），必要时写新的研究发现，然后告诉我发现的当前状态。不要直接改任何文档的标签。" 3600
  ck I-reverified
  end_session "at the end"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，告诉我各条经验与研究发现的当前状态。只核对。" 2400
  ck J-after-restart
}
