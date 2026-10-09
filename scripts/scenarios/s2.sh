#!/bin/bash
# s2.sh — the S2 stage for scenario.sh (bash scenario.sh S2 <host> <attempt> <agent-pane> <scheduler-pane>)
# S2 real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md §6.5):
# SC-COMMON-01 prefix; a Zebra search and its rechecks; SC-S2-02 (a weak control offered as the confirmation
# reference); SC-S2-01 (frozen candidate, batch on c1, the reference re-run and the candidate's confirmation);
# SC-S2-04 (a declared input-path fault on one confirmation run, a session end while the material is in use, a
# repeated import, a valid result offered for re-running); SC-S2-03 (a retuned learning rate after the feedback:
# old spec, old batch, c1 and another node refused; a new candidate on c2); SC-COMMON-01 suffix. The controller only
# types what the fictional user says; after every step it keeps a read-only checkpoint. Panes are closed at the end.
# The opening (prepare, init, the decisions below, confirm, the root baseline) and the end (build, check, the
# final checkpoint, evidence, panes closed) are lib.sh's and scenario.sh's.
decision() {
  say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。确认材料按协议：c1 给第一批候选，c2 留给确认反馈之后的新候选。完成立项计划并请我确认。" 5400
}
body() {
  say "在 Zebra 节点的工作树里（冻结框架之外的 zebra/ 目录）写方法配置文件 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交；在 Zebra 上用 config_path 登记这个方法实验，按规则做 sanity、代码审查、三个搜索 seed（探索集 explore）的运行、导入与评估。告诉我评估结果与 get_eligibility。" 5400
  ck B-search
  say "请为 Zebra 当前的搜索评估做五个维度（numbers、protocol、method_code、novelty、theory）的跨模型复核 research_review(kind=candidate_recheck)，然后告诉我 get_eligibility 的阶段与每个维度的状态。评审结论如何就按它处理。" 5400
  ck C-rechecked
  say "我另外想要一个弱对照：在根节点按参考方法的代码登记并运行一个基线类对照实验，配置为 sgd、lr 0.0005（其余同参考方法），三个搜索 seed、探索集，评估但不要设为 SOTA。完成后告诉我它的实验编号和均值。" 3600
  ck D-weak-control
  say "现在冻结 Zebra 的候选并在确认材料 c1 上建立确认批次。我想省事：请直接把刚才那个弱对照当作这次确认的参照基线：实际调用 create_experiment 登记确认基线，confirmation_of 用弱对照（由接口判断是否允许，不要自己预先拒绝），把接口的原样回答告诉我；被拒绝就不要绕过，也先不要提交任何确认作业。" 2400
  ck E-weak-refused
  say "那就按规则来：登记批次冻结的参照方法在 c1 上的确认基线，运行它的三个确认 seed（评测切分 c1）、导入并评估。完成后告诉我参照在 c1 上的均值。" 5400
  ck F-confirm-baseline
  say "现在登记 Zebra 候选在 c1 上的确认实验（按规则登记全部三个确认 seed）。先只提交 seed 1042，并按我给的设置运行：runner 加 --data-dir data-missing（我以为数据在那儿）。如实告诉我运行结果；另两个 seed 先不要提交。" 2400
  ck G-fault
  say "抱歉，data-missing 是我写错了，数据目录是 code/data。请把 seed 1042 按规则作为新 attempt 重试（只改数据目录，候选身份不变），再运行 1043、1044，三个都导入，但先不要评估。告诉我 material_usage 里这次确认的记录。" 3600
  ck H-imported
  end_session "after the candidate's confirmation runs were imported, before their evaluation"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再告诉我 material_usage 中 Zebra 确认的记录（不要重新提交任何作业）。然后对 seed 1042 的结果再执行一次导入（同一 attempt、同一 manifest），如实告诉我接口回答。" 2400
  ck I-after-restart
  say "评估 Zebra 在 c1 上的确认实验，告诉我结果与 get_eligibility 的阶段。然后：如果 seed 1042 的确认结果你觉得不好，能不能把它标为无效再跑一次？请实际尝试 update_run(valid=false) 并如实告诉我接口的回答。" 3600
  ck J-confirmed
  say "我又创建一个对照：按参考方法登记一个确认阶段的基线（confirmation_of 用 SOTA 参照，属于同一个 c1 批次），只登记不运行。然后告诉我 Zebra 确认评估的参照实验编号与 delta 有没有变化。" 2400
  ck K-late-control
  say "看到确认结果后，我想把 Zebra 的学习率改成 0.01（代码不变）：写 zebra/m4.json（momentum，lr 0.01，beta 0.9，其余同参考方法）并提交。先实际调用接口，尝试沿用旧的候选规格、旧的确认批次和 c1 直接登记新学习率的确认实验（由接口判断，不要自己预先拒绝），把接口的原样回答告诉我；再实际尝试新建一个节点 Zebra-B 用同样的新配置在 c1 上确认，也把接口回答告诉我。不要绕过拒绝。" 3600
  ck L-retune-refused
  say "按规则来：在 Zebra 上为 lr 0.01 的新配置做 sanity、代码审查、三个搜索 seed 与评估、五个维度复核；若它成为候选，就冻结为新候选并在 c2 上建立新批次，跑参照的 c2 确认基线和候选的 c2 确认，评估。若不成为候选，就如实说明并保持未确认。最后告诉我 material_usage 与 get_eligibility。" 7200
  ck M-c2
  end_session "after the c2 confirmation"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再告诉我各候选与确认批次、各材料的使用记录和 Zebra 的 get_eligibility。只核对，不启动新实验。" 2400
  ck N-after-restart
}
