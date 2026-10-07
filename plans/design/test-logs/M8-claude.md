# M8 Claude 宿主真实测试记录

日期：2026-10-07。批次内容见 06 §4（类型化关系 combines/repairs/tests_assumption 与派生的 tested_by/supports/invalidates、REPEATED_DIRECTION、探索份额）、11 §2（整体工作流对照与 benchmark 工具）。宿主：Claude Code v2.1.292，auto 权限模式，主模型 claude-sonnet-5-5（effort medium）。
插件：`scratchpad/dist-m8/claude/plugins/research-tree`（M8 构建，未修补）。reviewer `openai/gpt-6-luna` via pi。
任务：benchmark 场景 "combination"（scale 与 warmup 单独无效，一起 +1.5 pp；真值不告诉 Leader），玩具训练器仅在环境变量 RT_BENCH_TRUTH 设置时施加隐藏效应。

两次尝试：
- 第一次（`rt-test-M8-claude`，pane w3:pD，agent rt-m8，会话 57608595…）：**中止**，见 §8。
- 正式一次（`rt-test-M8b-claude`，pane w3:pE，agent rt-m8b；version 2，discovery off，alert_node_h 0.1，search/total_limit null）。下文除 §8 外都指正式一次。

## 1. 命令

- `herdr pane split --current --direction right --cwd $T --no-focus` → w3:pE；`herdr pane run w3:pE "export RT_BENCH_TRUTH=$B/truth.json"`；`herdr agent start rt-m8b --kind claude --pane w3:pE -- --plugin-dir $P --add-dir $P --model claude-sonnet-5-5 --permission-mode auto`（返回 agent_not_ready，信任对话框；`send-keys down enter` 后正常）。
- `/research-tree prepare`、`/research-tree init`、一条说明（只用 accuracy；自提假说可接受；plan 里的开关就是要研究的机制，运行必须用 `--knobs`，不要重新实现成 --method；train.py 里注入的 accuracy 项是任务设计的一部分；先只做根节点）、`/research-tree confirm`，之后用 `herdr agent prompt --wait` 以用户身份指挥；`/exit` 后 `herdr pane close w3:pE`。
- 核对用 `cd $T && $T/.venv/bin/python $P/tools/research_tree.py query ...`（必须在项目目录里执行，否则 "no research project here"）与 `build_site.py --db ... [--check]`、`score.py`。

## 2. observed 模型与评审费用

agent_models.jsonl：main（rld/main）observed claude-sonnet-5-5（06:27:55，早于任何评审）；worker/root、h0003、h0004、h0005 各有 requested（claude-sonnet-5-5 medium）与 observed 记录，模型一致。
评审（review_calls.jsonl）：全部 backend pi。根框架 code_review 三次全部 `REVIEW_INVALID`（见 §7-1），之后节点评审 RV-0004（H-0003）、RV-0005（H-0004）各两轮、RV-0006（H-0005）一轮，均 ok。合计 0.00678 USD，与 score 的 review_cost_usd 一致，Claude Code 后端 0。

## 3. 场景 A：prepare → init → planning → confirm → 根 sanity + 基线 + 冻结

结果：**通过（有保留）**。

- init 一个回合完成：目标 D-0003、协议 D-0005、三个初始节点（lookahead、ema、warmup；discovery off，plan 写“由发现流程产生”，Leader 自提并如实披露）、T-0001、立项计划 v2 D-0014。v1（D-0013）因“优于 SOTA”字样被评测类型限制拒绝，v2 通过。confirm 后启动 root worker。
- 根 worker：sanity E-0001、SOTA E-0002（adam lr 0.05，seed 0/1/2，均值 90.5213、SD 0.7965，EV-0001）、momentum E-0003、确认 seed 100–102 的 E-0004/E-0005；冻结 harness_ref c5d5c9d（harness_paths 为 harness.py、stats.py）。由于 worker 无权 `update_project`，冻结由 Leader 完成；worker 在导入前补了 manifest 的 counts.seeds（PAIRING_MISMATCH，见 §7-2）。
- `build_site.py` 构建 “data_version 412, 6 nodes, 1 attention items”；`--check`：`{"page_version": 412, "db_version": 412, "stale": false}`。

## 4. 场景 B（M8 判据）：从两个无增益的节点派生组合节点

结果：**通过（关系记录与预算都符合；组合没有在 3 个 seed 上显示出增益，见下）**。

- 单开关：H-0003（warmup，用 `--knobs warmup`，E-0009，EV-0006）配对差值均值 +0.0206 pp（SD 0.2993）→ inconclusive；H-0004（scale，`--knobs scale`，E-0008，EV-0005）配对差值均值 −0.950 pp（SD 1.616）→ negative_signal。两者均 gate_passed=false，符合“无增益”。
- 组合：用户只说“提出一个组合两种机制的新节点，如实登记与 H-0003、H-0004 的关系”。Leader 创建 H-0005，create_hypothesis 带 combines→H-0003、combines→H-0004 被接受（H-0004 此时已是 negative_signal，H-0003 inconclusive），没有被拒。
- `query relations {"node_id":"H-0005"}`：`combines H-0005→H-0003`、`combines H-0005→H-0004`、`tested_by H-0005→E-0010`、`tested_by H-0005→E-0011`。H-0004：`tested_by`（E-0007、E-0008）与 `{"kind":"invalidates","from":"EV-0005","to":"H-0004","applies":true}`；H-0003 只有 tested_by（评估为 inconclusive，不派生 supports/invalidates，符合 06 §4）。H-0005 本身也没有 supports/invalidates（EV-0007 inconclusive）。
- 组合运行在预算内：E-0010 sanity + E-0011（seed 0/1/2，`--knobs scale,warmup`）共 4 node·s，项目累计 25 node·s，alert_node_h 0.1 没有触发。
- 组合结果：EV-0007 配对差值 [+1.876, +0.738, −1.133]，均值 **+0.494 pp**（SD 1.519），门槛 0.5 pp，gate_passed=false，outcome inconclusive。真值是 +1.5 pp：**没有显示出增益**。原因看来是基线与方法 seed 噪声很大（三个 seed 的配对 SD 约 1.5 pp，3 个 seed 的均值标准误约 0.9 pp），不是插件缺陷；但它说明本 benchmark 配置下 3 seed 筛选无法可靠识别 1.5 pp 的组合效应（见 §7-6）。
- Leader 请求升级到确认阶段被接口拒绝：只有搜索结果过了门槛才能确认；复验没有可用的新 seed（搜索 seed 只有 0、1、2，比较设定第一个实验创建后不可改）。Leader 没有改门槛，列出四个选项让用户决定。

## 5. 场景 C：重复方向

结果：**通过**。

- 先以决定文档把 H-0004 退役（disposition retired）。
- 用户让 Leader 新建「步长倍率调整」、机制仍是 `--knobs scale`、不登记 repairs。创建被拒，原文：`CodedError: REPEATED_DIRECTION: H-0004 already tested this direction and is no longer pursued: a new node repairs it (relation repairs with the specific defect it fixes) or takes another direction`。库未变化；Leader 没有换措辞绕过。
- 用户让 Leader 以 repairs→H-0004、缺陷“系数 2.0 等价于 lr 0.1、此前没有 lr 0.1 的 Adam 对照”再建：创建成功（H-0006），`query relations {"node_id":"H-0006"}` 返回 `repairs H-0006→H-0004`。Leader 同时指出规则是“每个根因最多修复 2 次”。H-0006 只建了节点与设计文档，没有跑实验。

## 6. 场景 D：探索份额

`budget_status`（结束时）：`limits` 全 null（total/search/confirmation/repair），`committed` total 25（search 19、confirmation 6、repair 0），`exploration: {"fraction": 0.15, "committed": 12, "other_search_committed": 7}`，open_reservations 空，admission_paused null。**search_limit 为 null，所以探索份额没有被强制执行**，未强制测试（按要求）。可见字段正确出现：H-0003、H-0004、H-0005 标 exploration=true，其搜索用量 12 node·s，其余搜索 7 node·s；exploration 占搜索的 12/19，远超 15%，因没有上限不拦截。

## 7. 发现的问题与可疑行为

1. **MINOR/MEDIUM：reviewer 输出格式在根框架评审上连续三次 `REVIEW_INVALID`。** 错误分别是 `no ```json block with an object`（两次）与 `<root>: 'issues' is a required property; <root>: 'method_implemented' is a required property`，每次费用约 0.001 USD。Leader 申请 `waive_code_review` 被接口拒绝（只在 REVIEW_UNAVAILABLE 时允许），基线实验因没有所属节点最终未被这道关拦住，根框架始终没有过跨模型评审。之后的节点评审都正常。没有自动重试/降级路径；评审为 INVALID 时项目只能靠“基线不受此关限制”继续。建议确认基线是否应受代码评审约束，以及 INVALID 是否应计入“不可用”以便放行。
2. **MINOR：冻结的 harness.py 没有写 counts.seeds，导入时 PAIRING_MISMATCH**，worker 在冻结路径之外的脚本里导入前补了 seeds=3。修复需要改 harness.py 并重新冻结（会清掉 SOTA 基线）。属于根 worker 实现框架的问题，不是插件缺陷，但根任务说明没有提示 manifest 必须含 counts.seeds。
3. **MINOR：create_experiment 的 seed 数提示与流程不一致。** Leader 报告筛选时被拒 `this experiment may start with 1..1 seeds, got 3`，处理为扩到 3 个 seed（项目协议里 screening_seeds=[0]，而基线用了 3 个 seed）。最终所有节点筛选都用 3 个 seed。
4. **观察（盲测完整性）：** worker 在导入前看到了未登记的 accuracy 差值（h0003 约 +0.36 pp；h0005 看了日志末行；H-0004 前一次尝试中类似），均在交付文档里披露，没有影响选择。
5. **MINOR（评分口径）：score 的 user_burden 为 1，低估。** 库里只有两条 `user_instruction` 文档（UI-0001 init、UI-0002 confirm）；我在这些之后直接向 Leader 发了约 8 条指令（steering、H-0003/scale、组合、升级、退役、重复方向、repairs 等），都没有登记成 user_instruction，所以 `user_burden = max(0, 2-1) = 1`。直接发给 Leader 的消息不会被登记，benchmark 的用户负担指标因此不可信（对 System C 在 Claude 宿主）。
6. **观察（benchmark 设计）：** 3 个 seed 的筛选对 1.5 pp 效应功效不足（基线 SD 0.80，组合配对 SD 1.52），组合得到 +0.494 pp 差 0.006 pp 过门槛；搜索 seed 在第一个实验后不可改，Leader 无法追加 seed。真值任务应让搜索 seed 更多或噪声更小，否则“found”几乎总是 false。
7. **观察：** 结果文档不能含“优于 SOTA”字样（包括否定写法），v1 立项计划就因此被拒；Leader 与 worker 记下后避开。
8. **未覆盖：** tests_assumption 关系；repairs 的“每根因最多修复 2 次”上限；探索份额在有 search_limit 时的强制；H-0001/H-0002 未开工；H-0006 没有运行；supports（positive_signal）的派生没有出现，因为没有节点获得正向信号。

## 8. 第一次尝试（中止）

任务 `rt-test-M8-claude`（alert_node_h 0.005），agent rt-m8。观察到的内容：
- init 之后 Leader 自提三个节点（EMA、lookahead、warmup+clip）；我只说“--knobs 是机制菜单、不要改 train.py”，Leader 把它理解成可选，worker 把 EMA、lookahead 实现成新的 --method，代码评审（RV-0001）指出 train.py 注入的 accuracy 项“无法核实”并升级为用户决定（main-0002、main-0003）。这促成了正式一次的前置说明。
- worker 无权 `create_branch`、`update_project`，自行用 git 建 worktree，由 Leader 登记。
- E-0007（lookahead，seed 0）+0.5 pp，恰在门槛上，inconclusive（用的是自己实现的方法而不是开关）。
- 单次 3 个节点的预算很快用到 18 node·s（0.005 node·h），触到 alert_node_h 0.005，Leader 要求用户把阈值调到 0.05 并 `/research-tree config apply`；我改该项目 research-tree.yaml 的操作被 Claude Code 的 auto 模式分类器拒绝，未绕过；主 agent 决定放弃该任务，我 `/exit` 并关闭 w3:pD。
- 该尝试没有产生评分数据。

## 9. 评分（System C，正式一次）

`score.py "$T" --truth "$B/truth.json" --system C`：

```json
{"system": "C", "scenario": "combination", "outcome": "active", "false_go": false, "found": false, "premature_elimination": false, "efficiency": 3600.0, "duplicate_attempts": 0, "user_burden": 1, "review_cost_usd": 0.00678, "coverage": 3, "repeated_failures": 0, "wall_clock_h": 0.633}
```

与库核对：outcome active（没有 GO/NOT GO 决定）合理；coverage 3 = {warmup, scale, scale+warmup}（H-0001/2/6 没有测试运行）；premature_elimination false：真正最优集 {scale,warmup} 未被退役；efficiency 3600 = 25 次有效运行 / (25 node·s = 0.00694 h)，与 budget_status 的 25 node·s 一致；review_cost 0.00678 与评审日志之和一致；wall_clock 0.633 h（创建 06:24 → 最近决定约 07:02）合理；user_burden 见 §7-5，偏低。

## 实施者处理（主 agent）

| # | 问题 | 处理 |
|---|---|---|
| 1 | 根节点框架的代码审查连续 REVIEW_INVALID，且不能放行 | 已修：reviewer 不可用或只给出无效输出（REVIEW_UNAVAILABLE / REVIEW_INVALID）时，Leader 都可凭决定文档放行（waive_code_review）；有阻塞审查时仍不可放行 |
| 2 | 冻结的 harness.py 缺 counts.seeds | Leader 生成的框架缺陷，非插件问题；接口按协议拒绝导入是预期行为，记录 |
| 3 | 起始 seed 只允许 1 个 | 预期：版本 2 的 screening_seeds 为 1 个（M3 修复），之后按规则扩展 seed |
| 4 | worker 在登记前看到精度 | 已在交付文档中披露、未影响选择；记录（盲测纪律属提示与规则） |
| 5 | score 的 user_burden 偏低 | score.py docstring 写明只计登记的用户指令，直接输入主会话的引导须从宿主日志计数 |
| 6 | 组合收益 1.5 pp 在 3 个配对 seed 下检测不出 | 已修：gain、combination、faults 场景的真实效应改为 +3 pp（玩具的 seed 噪声下 3 个配对 seed 可检出）；noisy 场景仍检验低功效情形 |
| 7 | 否定式“未优于 SOTA”也被拒 | 已修：否定词（不/未/没有/并非/not/no）紧跟其前的措辞不算超出结论上限；测试 |
| — | 未覆盖：tests_assumption、修复次数上限、设了 search_limit 时的探索份额、supports 派生 | 单元测试覆盖（SearchRelationTest） |
| — | 工作流对照（A/B/C）的完整比较 | 工具已就绪（make_task、score），本次只对 C 打分一次；完整比较需在多个任务与种子上运行三个系统，规模与费用待用户决定 |
