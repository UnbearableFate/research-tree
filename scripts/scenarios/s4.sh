#!/bin/bash
# s4.sh — the S4 stage for scenario.sh (bash scenario.sh S4 <host> <attempt> <agent-pane> <scheduler-pane>)
# S4 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §8.7):
# SC-COMMON-01 prefix; SC-S4-01 (a real reviewer checks a summary whose numbers contradict the metrics; the finding is
# recorded once, survives a restart, and closes only by an explicit resolution with a new passing review); SC-S4-02
# (novelty without the foundational paper: one literature follow-up in the same session, nothing re-run after a
# restart); SC-S4-03 (a same-family reviewer refused before any call; the backend unavailable for one session — no
# fallback, no self-review; then a real cross-family review); SC-S4-04 (an altered code snapshot gives no method_code
# pass; the real one does); SC-COMMON-01 suffix. Checkpoints after every step; panes closed, build packed at the end.
# The opening (prepare, init, the decisions below, confirm, the root baseline) and the end (build, check, the
# final checkpoint, evidence, panes closed) are lib.sh's and scenario.sh's.
decision() {
  say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。完成立项计划并请我确认。" 5400
}
body() {
  say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交；在 Zebra 上用 config_path 登记这个方法实验，按规则做 sanity、代码审查、三个搜索 seed 的运行、导入与评估，并写好结果文档。告诉我评估结果与 get_eligibility。" 5400
  ck B-zebra
  helper $REPO/.venv/bin/python $REPO/scripts/scenarios/s4_wrong_report.py $C $PV $TOOLS >/dev/null
  python3 -c 'import json,sys; print(json.dumps({"event": "controller wrote a report copy that contradicts the metrics (F-S4-01)", "record": json.load(open(sys.argv[1]))}))' $C/fault-applied.json >> $C/commands.jsonl
  say "我在研究目录 docs/reports/zebra-summary-draft.md 写了一份 Zebra 的结果摘要（数字是我手抄的）。请把它作为 numbers 维度要复核的结果文档，为 Zebra 当前评估做一次真实的跨模型复核 research_review(kind=candidate_recheck, dimension=numbers)，brief 只列文件与元数据。如实告诉我回执的结论、各清单项和是否产生了未决问题。" 3600
  ck C-numbers-reviewed
  end_session "after the numbers review"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手。告诉我未决问题（obligations）列表；然后把刚才那份 numbers 回执再登记一次是否会增加问题——不要重新调用 reviewer，只查看接口与记录。" 2400
  ck D-after-restart
  say "那份摘要是我抄错了。请写一份数字取自指标文件与统计文件的正确结果文档（新版本），再为 numbers 维度做一次新的真实复核；若这次通过，就用这份新回执按规则 resolve 对应的未决问题，然后告诉我 get_eligibility 和其余仍未关闭的问题。" 3600
  ck E-resolved
  say "请为 Zebra 做 novelty 维度的真实复核。我注意到假说的相关文献里没有动量法的基础论文（Polyak 1964, Some methods of speeding up the convergence of iteration methods），brief 里不要替 reviewer 补上。若 reviewer 返回 uncertain 并列出 requested_queries，就用 literature_followup 执行一次补查，再在原会话里带上补查结果重新复核；若 reviewer 已能判定，就如实记录，不要强迫它要求补查。告诉我每一轮的结论与补查记录。" 5400
  ck F-novelty
  end_session "after the novelty follow-up"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，告诉我 novelty 复核与补查的当前状态（已完成的查询不要重跑）。" 2400
  ck G-after-restart
  helper python3 $REPO/scripts/scenarios/s4_edit_reviewer.py $PV/research-tree.yaml same-family $host
  echo '{"event":"fictional user edited research-tree.yaml: models.reviewer to the Leader'"'"'s own family (F-S4-03a)"}' >> $C/commands.jsonl
  say "我把 research-tree.yaml 的 reviewer 改成了和你同一家族的模型。请让配置生效（$CMD config apply），然后为 Zebra 做一次 theory 维度的复核，如实告诉我结果；不要用自评代替。" 2400
  ck H-same-family
  helper python3 $REPO/scripts/scenarios/s4_edit_reviewer.py $PV/research-tree.yaml restore $host
  echo '{"event":"fictional user restored models.reviewer in research-tree.yaml"}' >> $C/commands.jsonl
  say "我把 reviewer 改回原来的设置了，请让配置生效，暂时不要评审。" 1200
  # the next session starts with the reviewer backend unavailable on its PATH (F-S4-03b)
  echo '{"event":"end session (before the unavailable-backend check)"}' >> $C/commands.jsonl
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; shimmed=pi; else herdr agent prompt $A "/quit" >/dev/null 2>&1; shimmed=claude; fi
  sleep 6
  mkdir -p $C/shim-$shimmed
  printf '#!/bin/sh\necho "%s: not logged in (S4 controller shim)" >&2\nexit 1\n' "$shimmed" > $C/shim-$shimmed/$shimmed; chmod +x $C/shim-$shimmed/$shimmed
  herdr pane run $pane "export PATH=$C/shim-$shimmed:\$PATH"; sleep 1
  echo "{\"event\":\"controller started the next session with the reviewer backend ($shimmed) answering not-logged-in on its PATH (F-S4-03b)\"}" >> $C/commands.jsonl
  A=${A}u; start_agent
  say "$CMD status" 900
  say "请为 Zebra 做一次 theory 维度的跨模型复核，如实告诉我结果；后端不可用时不要换后端，也不要自评。" 2400
  ck I-unavailable
  echo '{"event":"end session (after the unavailable-backend check)"}' >> $C/commands.jsonl
  if [ $host = claude ]; then herdr agent prompt $A "/exit" >/dev/null 2>&1; confirm_exit; else herdr agent prompt $A "/quit" >/dev/null 2>&1; fi
  sleep 6
  herdr pane run $pane "export PATH=\$(echo \$PATH | sed 's#$C/shim-$shimmed:##')"; sleep 1
  echo '{"event":"controller restored the PATH for the next session"}' >> $C/commands.jsonl
  A=${A}v; start_agent
  say "$CMD status" 900
  say "后端恢复了。请为 Zebra 做 theory 维度的真实跨模型复核，告诉我回执的观测模型、后端与结论；已完成的复核不要重做。" 3600
  ck J-theory
  helper $REPO/.venv/bin/python $REPO/scripts/scenarios/s4_hide_snapshot.py hide $C $PV $TOOLS >/dev/null
  python3 -c 'import json,sys; print(json.dumps({"event": "controller moved the review code snapshot away and pointed the brief directory at another version (F-S4-04)", "record": json.load(open(sys.argv[1]))}))' $C/snapshot-fault.json >> $C/commands.jsonl
  say "请为 Zebra 做 method_code 维度的真实复核（读取所审提交的代码），如实告诉我回执结论、证据核验结果与资格状态。" 3600
  ck K-method-code-missing
  helper $REPO/.venv/bin/python $REPO/scripts/scenarios/s4_hide_snapshot.py restore $C $PV >/dev/null
  echo '{"event":"controller restored the code snapshot (F-S4-04)"}' >> $C/commands.jsonl
  say "代码快照恢复了。请再做一次 method_code 维度的真实复核，告诉我结论、证据核验与资格状态。" 3600
  ck L-method-code
  end_session "at the end"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再告诉我各复核维度的状态、未决问题与 get_eligibility。只核对，不重做评审。" 2400
  ck M-after-restart
}
