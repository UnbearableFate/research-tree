#!/bin/bash
# s3.sh — the S3 stage for scenario.sh (bash scenario.sh S3 <host> <attempt> <agent-pane> <scheduler-pane>)
# S3 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §7.5):
# SC-COMMON-01 prefix; SC-S3-01 (the saved model's size as an auxiliary metric: the fictional user changes its input
# unit in research-tree.yaml — re-evaluating the imported runs is refused — restores it and changes only its canonical
# unit with an equivalent bound, then tries to change the frozen primary metric's canonical unit); SC-S3-02 (incomplete
# copies of a real run's manifest in fault-injection/ are refused with nothing written, the original imports, a
# restart keeps the units and the reasons); SC-COMMON-01 suffix. SC-S3-03 (an old project upgraded) is
# run_s3_upgrade.sh. Checkpoints after every step; panes closed and the build packed at the end.
# The opening (prepare, init, the decisions below, confirm, the root baseline) and the end (build, check, the
# final checkpoint, evidence, panes closed) are lib.sh's and scenario.sh's.
decision() {
  say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；主指标 accuracy，辅助指标 model_bytes（保存的模型文件大小，按配置里的指标规范）；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。完成立项计划并请我确认。" 5400
}
body() {
  say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交；在 Zebra 上用 config_path 登记这个方法实验，按规则做 sanity、代码审查、三个搜索 seed 的运行、导入与评估。告诉我 accuracy 与 model_bytes 的评估结果（含保护指标是否通过）。" 5400
  ck B-zebra
  helper python3 $REPO/scripts/scenarios/s3_edit_config.py $PV/research-tree.yaml input-mib
  echo '{"event":"fictional user edited research-tree.yaml: model_bytes input_unit bytes -> mib (F-S3-01)"}' >> $C/commands.jsonl
  say "我把 research-tree.yaml 里 model_bytes 的 input_unit 改成了 mib。请按流程让这个配置生效（需要的话用 $CMD config apply，指标规范变化按规则登记），然后重新评估 SOTA 与 Zebra 的实验；不要重新训练，如实告诉我接口的回答。" 3600
  ck C-input-unit-changed
  helper python3 $REPO/scripts/scenarios/s3_edit_config.py $PV/research-tree.yaml canonical-mib
  echo '{"event":"fictional user edited research-tree.yaml: model_bytes input_unit back to bytes, canonical_unit bytes -> mib, allowed_regression 1024 bytes -> 0.0009765625 MiB (the same bound)"}' >> $C/commands.jsonl
  say "我把 model_bytes 的 input_unit 恢复成 bytes，只把比较单位 canonical_unit 改成 mib，并把允许的退化换算成等价的 0.0009765625 MiB（= 1024 字节）。请让配置生效、按规则登记，然后重新评估 SOTA 与 Zebra；告诉我 model_bytes 的效应与保护判定和之前是否一致。不要重新训练。" 3600
  ck D-canonical-changed
  helper python3 $REPO/scripts/scenarios/s3_edit_config.py $PV/research-tree.yaml primary-fraction
  echo '{"event":"fictional user edited research-tree.yaml: accuracy canonical_unit percentage_point -> fraction (the frozen primary metric)"}' >> $C/commands.jsonl
  say "我又把主指标 accuracy 的 canonical_unit 改成了 fraction。请尝试让它生效并如实告诉我结果；如果被拒，就把 research-tree.yaml 里的这一项改回 percentage_point（这一处你可以替我改回），保持原来的规范。" 2400
  ck E-primary-refused
  say "请在 Zebra 上登记一个新的方法实验：在 zebra/ 目录写 zebra/m3.json（momentum，lr 0.01，beta 0.9，其余同参考方法）并提交，用 config_path 登记，按规则做 sanity 与代码审查，然后只运行 seed 42 到训练完成（succeeded），先不要导入。告诉我这个 run 的 manifest 路径。" 5400
  ck F-run-not-imported
  helper $REPO/.venv/bin/python $REPO/scripts/scenarios/s3_fault_copies.py $C $PV $TOOLS >/dev/null
  python3 -c 'import json,sys; print(json.dumps({"event": "controller made fault-injection copies (F-S3-02)", "record": json.load(open(sys.argv[1]))}))' $C/fault-applied.json >> $C/commands.jsonl
  say "研究目录 fault-injection/ 里有两份那个 run 的 manifest 副本（一份缺 train_seed，一份缺 units）。请先分别用这两份副本尝试 import_run_result，如实告诉我接口的回答和数据库里这个 run 是否有任何导入记录；然后再用原始 manifest 导入。" 2400
  ck G-copies-refused
  end_session "after the fault-injection imports"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再告诉我 Zebra 那个 lr 0.01 run 的导入记录里的原始单位，以及刚才两份副本为什么被拒（从你能查到的记录核对）。只核对，不启动新实验。" 2400
  ck H-after-restart
}
