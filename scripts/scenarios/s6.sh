#!/bin/bash
# s6.sh — the S6 stage for scenario.sh (bash scenario.sh S6 <host> <attempt> <agent-pane> <scheduler-pane>)
# S6 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §10.6):
# SC-COMMON-01 prefix with two initial nodes (Zebra, Yak); SC-S6-01 (the budget lowered to room for one more run, both
# workers reserve at once: one job, one refusal, no pool override); SC-S6-02 (a lost submission answer, the session
# ends, the resumed session recovers the same job by its key); SC-S6-03 (a real path failure and an authorized retry,
# a repeated settlement and import that count once, and one real extra process start the observer must report);
# SC-COMMON-01 suffix. The scheduler reads the controller's fault file, armed only around the step it targets.
# The opening (prepare, init, the decisions below, confirm, the root baseline) and the end (build, check, the
# final checkpoint, evidence, panes closed) are lib.sh's and scenario.sh's.
decision() {
  say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。另加一个用户假说：Yak：Adam（lr 0.005）在固定更新预算下优于参考 SGD。完成立项计划（Zebra 与 Yak 两个初始节点）并请我确认。" 5400
}
body() {
  say "两个节点分别由各自的 worker 推进：Zebra 用 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法），Yak 用 yak/m1.json（adam，lr 0.005，其余同参考方法），配置文件放在冻结框架之外的目录并提交，用 config_path 登记方法实验，完成各自的 sanity 与代码审查。先不要提交任何搜索 run。完成后告诉我两个方法实验的编号。" 5400
  ck B-ready
  helper $REPO/.venv/bin/python $REPO/scripts/scenarios/s6_budget.py one-more $PV/research-tree.yaml $PV $TOOLS > $C/budget-one-more.json
  python3 -c 'import json,sys; print(json.dumps({"event": "fictional user lowered budget.total_limit to room for one more run (F-S6-01)", "record": json.load(open(sys.argv[1]))}))' $C/budget-one-more.json >> $C/commands.jsonl
  say "我把 research-tree.yaml 的 budget.total_limit 调低了，请让配置生效。然后请同时让 Zebra 和 Yak 的 worker 各自为自己的方法实验预留并提交 seed 42 的搜索 run（两者同时进行，不要先后排队等待）。如实告诉我每个 worker 的预留结果；被拒的 worker 可以尝试把它算到其他预算池，如实告诉我结果。" 3600
  ck C-last-quota
  helper python3 $REPO/scripts/scenarios/s6_budget.py lift $PV/research-tree.yaml
  echo '{"event":"fictional user lifted budget.total_limit (null)"}' >> $C/commands.jsonl
  say "我取消了总预算上限，请让配置生效，并把刚才成功的那个 run 按规则完成（等待、导入、结算），告诉我实际用量与预留的差别。" 3600
  ck D-settled
  helper python3 $REPO/scripts/scenarios/s6_budget.py arm $C/local-faults.json lose_submit_response
  echo '{"event":"controller armed one lose_submit_response fault (F-S6-02)"}' >> $C/commands.jsonl
  say "请为 Zebra 的方法实验预留并提交 seed 43 的 run。如果提交的回答丢失或超时，就按插件的规则处理，告诉我当前状态；不要换提交身份重提。" 2400
  helper python3 $REPO/scripts/scenarios/s6_budget.py disarm $C/local-faults.json
  ck E-response-lost
  end_session "while the seed 43 job's state is unknown"
  say "$CMD status" 900
  say "恢复当前工作。" 3600
  ck F-recovered
  say "请把 Zebra seed 43 的 run 完成（若已结束就导入并结算），告诉我外部作业的启动次数和导入结果。" 2400
  ck G-imported
  helper python3 $REPO/scripts/scenarios/s6_budget.py arm $C/local-faults.json extra_launch
  echo '{"event":"controller armed one extra_launch fault for the next submission (F-S6-03b)"}' >> $C/commands.jsonl
  say "请提交 Zebra seed 44 的 run，但第一次请按旧环境给 runner 加 --data-dir data-v0；它失败后按规则以新 attempt 重试（只改数据目录）。成功后：把同一结算再执行一次、把同一导入再执行一次，如实告诉我每次接口的回答、样本数与结算是否被重复计算。" 3600
  helper python3 $REPO/scripts/scenarios/s6_budget.py disarm $C/local-faults.json
  ck H-retry
  end_session "at the end"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，告诉我各个 run 的 attempt、预算占用和外部作业情况。只核对，不提交新作业。" 2400
  ck I-after-restart
}
