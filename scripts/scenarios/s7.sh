#!/bin/bash
# s7.sh — the S7 stage for scenario.sh (bash scenario.sh S7 <host> <attempt> <agent-pane> <scheduler-pane>)
# S7 functional real scenarios on one fresh ToyOpt Lab project (plans/research-tree-implementation-and-real-scenarios.md
# §11.7): SC-COMMON-01 prefix with two nodes (Zebra, Yak); SC-S7-01 (real paired noise and the protocol's bounded
# repetition advice followed until it stops or its seed pool is used up; never the confirmation pool; a restart agrees
# with the completed runs); SC-S7-02 (a combination node over parents with limited or unclear gains, its choice tied
# to named findings; no gain is kept as it is); SC-COMMON-01 suffix. SC-S7-03 (the matched pilot) is separate.
# The opening (prepare, init, the decisions below, confirm, the root baseline) and the end (build, check, the
# final checkpoint, evidence, panes closed) are lib.sh's and scenario.sh's.
decision() {
  say "我的决定：评测类型用 synthetic_proxy（合成数据上的真实计算，结论只限于本合成任务）；只比较 accuracy；代码仓库是 code/（它自己的 git 仓库，已有提交），不要在项目根目录另建提交。另加一个用户假说：Yak：学习率在一轮内余弦衰减（其余同参考方法）在固定更新预算下优于参考 SGD。完成立项计划（Zebra 与 Yak 两个初始节点）并请我确认。" 5400
}
body() {
  say "请推进 Zebra：在冻结框架之外的 zebra/ 目录写 zebra/m1.json（momentum，lr 0.005，beta 0.9，其余同参考方法）并提交，用 config_path 登记方法实验，完成 sanity、代码审查、三个搜索 seed 的运行、导入与评估。然后调用 repetition_advice，告诉我它的输入（配对差值、独立单元）、建议与理由。" 5400
  ck B-zebra-advice
  say "请按 repetition_advice 的建议行事：若建议追加重复，就在协议声明的 seed 池里按建议追加并通过正常预算预留运行、导入、重新评估，再问一次建议；一直到建议不再追加或 seed 池用完为止。不要使用确认材料或确认 seed。告诉我每一轮的建议与最终结论。" 7200
  ck C-repeats
  end_session "after the repetition rounds"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，再问一次 Zebra 的 repetition_advice，告诉我它与已完成的 run 是否一致。只核对，不启动新实验。" 2400
  ck D-after-restart
  say "请推进 Yak：在 yak/ 目录写 yak/m1.json（实现一轮内的余弦学习率衰减；如 runner 不支持就在 Yak 的工作树里实现这个选项并提交，其余同参考方法），完成 sanity、代码审查、三个搜索 seed 的运行、导入与评估。然后分别为 Zebra 与 Yak 写研究发现（finding），并在本批次的决定文档里用 note_findings 登记这批新发现（列出 finding 文档）。告诉我两者的结论。" 7200
  ck E-yak
  say "两个机制单独的收益有限或不确定。请按规则建立一个组合节点：用 relations 的 combines 关系引用 Zebra 与 Yak，说明它要区分的解释、所依据的 finding、什么结果会改变下一步与成本；实现同时启用动量与余弦衰减的配置并做最小对照（与两个父节点同 seed），按规则运行、导入、评估。结果没有收益就如实保留，不要改指标或父节点状态。告诉我组合节点的结论与它和父节点的关系。" 7200
  ck F-combination
  end_session "at the end"
  say "$CMD status" 900
  say "恢复当前工作：先按插件的恢复方式接手，告诉我三个节点的状态、关系与停滞计数。只核对。" 2400
  ck G-after-restart
}
