# M2 Claude 宿主真实测试记录

日期：2026-10-06/07。批次内容见 12 §1（M2）。宿主：Claude Code v2.1.292，pane w3:p7，agent `rt-claude-m2`，`--permission-mode auto`，
插件 `scratchpad/dist-m2/claude/plugins/research-tree`（由 M2 树构建，未重建）。只测 Claude 宿主。
项目：`$T/rt-test-M2-claude`（T = scratchpad/e2e），project_id `rt-test-m2-claude`。无 reviewer 调用，评审费用 0。

## 1. 命令

- `python3 scripts/make_rt_test_project.py $T/rt-test-M2-claude --host claude`；`herdr pane split --current --direction right --cwd ... --no-focus`（w3:p7）；
  `herdr agent start rt-claude-m2 --kind claude --pane w3:p7 -- --plugin-dir $P --add-dir $P --model claude-sonnet-5-5 --permission-mode auto`；
  信任目录对话框用 down+enter 选 "Yes, I trust this folder"。
- 驱动：`/research-tree prepare`、`/research-tree init`（约 10 分钟，到"等待用户确认"）、`/research-tree confirm 同意立项计划`，
  之后 Leader 自行跑完根 worker 与两个节点的筛选实验，并在第一批结果后自行 NOT GO（见 §4）。
- 人为指令（用户身份，已如实记录，见 §5）：
  1. "作为测试（M2 场景，我是用户……）：新建 H-0003 = Adam 加前 5% 步线性 warmup（H-0001 变体，记录关系），先只跑 1 个 seed（seed 1）筛选，登记结果，如实登记 outcome，轻微负向或很小时不要强行判可剪枝；随后扩到 3 个 seed（上限），接近 0.5 门槛时如实登记为不确定；基于不确定结果的决定写缺失证据与下一实验；暂停或搁置要带证据与复议条件；不改协议和门槛。"
  2. "作为测试（M2 场景，我是用户）：请现在再次结项，判 NOT GO，按接口要求写报告，并告诉我报告里涵盖了哪些部分。"
- 核对：`$T/rt-test-M2-claude/.venv/bin/python $P/tools/research_tree.py query <方法> '<json>'`（find、get、history、evaluations、get_eligibility、obligations、edges、latest_result、help）；
  `build_site.py --db research/rt-test-m2-claude/research_tree.db` 与 `--check`。

## 2. observed 模型（research/rt-test-m2-claude/logs/agent_models.jsonl）

worker/root、worker/h0001、worker/h0002、worker/h0003 均 requested `claude-sonnet-5-5`（effort medium），observed `claude-sonnet-5-5`，与配置一致。
Leader（主会话）为 Sonnet 5.5（启动参数 `--model claude-sonnet-5-5`，界面显示 "Sonnet 5.5 with xhigh"，effort 未显式设为 medium；记录里没有 Leader 的 observed 行，因 agent_models.jsonl 只记子 agent）。

## 3. 场景「所有批次」：prepare → init → 立项计划 → confirm → 根 worker 的 sanity、基线、冻结

判据：数据库状态与阶段文件一致；页面 check 通过。结果：**通过**。

- 立项计划 D-0014（project/reports/init-plan.v1.md），确认 D-0016。协议 `docs/project/protocol.v1.json`（D-0010）**自动带有** `"profile": "stage1_confirmed"`、`"confirmation_seeds": [101,102,103]`、`min_confirmation_pairs: 3`、`max_confirmation_candidates: 2`；project.seeds = [1,2,3]，gate_seeds=3，go_margin=0.5，eval_type simulation_only。
- 根 worker T-0001（harness）：E-0001（adam）、E-0002（momentum）各 seed 1/2/3，EV-0001/EV-0002 `artifact_imported`；`harness_ref=8106e0f8…`，`harness_paths=[toytrain/train.py, manifest.py, stats.py]`，`sota_experiment_id=E-0001`；T-0001 `accepted_evidence=[EV-0001, EV-0002, D-0023]`。
- `build_site.py --check` → `{"page_version": 272, "db_version": 272, "stale": false}`（最后一次）。页面有 15 条"曲线缺失"提示（见 §6-2）。

## 4. 场景 M2：1 个 seed 轻微负向/很小；达到 seed 上限仍接近门槛

判据：`inconclusive`，不强制剪枝；基于不确定结果的决定有 缺失证据/下一实验；暂停/搁置带证据与复议条件。

### 自然发生部分（未人为指令）
Leader 对 H-0001（E-0003）、H-0002（E-0004）各跑 3 个 seed 的筛选实验（第一批，3 = project.seeds 上限 = gate_seeds）：
- EV-0003：accuracy 配对差 +0.0833（0,0,+0.25），outcome `inconclusive`，gate_passed=false，guardrails_passed=true，reason "effect 0.0833 over 3 pair(s): neither clear of 0.5 nor a negative signal over 3 pairs"。
- EV-0004：对 SOTA −0.4167（−0.5,−1.0,+0.25；SD 0.629），outcome `inconclusive`（未登记为负向信号：负向需要 3 个配对上低于 −0.5）。
- DEC-0005/0006：`experiment_status running→inconclusive`；节点 `status` 保持 `verifying`，从未设为 prunable。
- DEC-0007/0008：`note_findings` 各 1 条，`stall_state: none`。
- DEC-0009/0010：`decide_disposition` active→retired，`based_on=[D-0034, EV-0003]`/`[…EV-0004]`；节点上 `reconsider_when` 非空（"用户增加搜索 seed、扩大验证集或改变协议；或有新证据……"），`disposition_reason` 写明"投入价值判断，不是科学反证"。
- 决定文档 D-0034（project/decisions/batch1-results.v1.md）含 `## 缺失证据`、`## 下一实验`、`## 投入处置`（含复议条件）。
- 项目 NOT GO：DEC-0013 `active→not_go`，`based_on=[D-0034, EV-0001..EV-0004]`，报告 D-0035（reports/not-go.v1.md）含 `## 未探索 / 工程失败 / 不确定 / 重复方向 / 明确反证 / 投入价值判断`（另加 结论、做了什么、结果、最小值点诊断、数字来源）。此时两个节点都 retired（无 active 节点）。

### 人为指令后的部分（指令 1）
项目 `not_go → active`（DEC-0014，引用用户指令 D-0037 / MAIN-0001，`based_on=[D-0036]`）。H-0003（`parent_id` 为项目，`rel_related` 边 `H-0003 → H-0001 kind=variant_of`，代码分支 node/H-0003 基于 node/H-0001）：
- E-0005 先只跑 seed 1：**EV-0005**（result_revision 1，run_attempt_refs 含 `E-0005/s1@1`，`n_paired=1`，delta 0.0）outcome `inconclusive`，reason "effect 0 over 1 pair(s): neither clear of 0.5 nor a negative signal over 3 pairs"；节点 status 保持 `verifying`。
- 决定文档 `hypotheses/H-0003/decisions/extend-to-3-seeds.v1.md` 含 `## 缺失证据`、`## 下一实验`；明确"不标可剪枝"，并事先写下三种结果分别如何处理。
- E-0005 扩到 seed 1/2/3：**EV-0006**（result_revision 2，6 个 run_attempt_refs，`n_paired=3`，deltas 0/0/0），outcome `inconclusive`；EV-0005 保留为历史。T-0004 `accepted_evidence=[EV-0005, D-0042, D-0043]`，T-0005 `[EV-0006, D-0046, D-0047]`。
- DEC-0017 `experiment_status→inconclusive`（`doc_id=D-0048`）；DEC-0019 `decide_disposition` active→**paused**，evidence 含 EV-0006/EV-0005/D-0046/D-0048，`reconsider_when` 非空；`status` 仍 `verifying`。决定文档 `inconclusive-and-pause.v1.md` 含 `## 缺失证据`、`## 下一实验`、`## 投入处置：暂停`（证据、复议条件）。
- 之后 Leader 按指令 2 再次 NOT GO：DEC-0021 `active→not_go`，`based_on=[D-0048, D-0049, EV-0003, EV-0004, EV-0006]`，报告 not-go.v2.md 含同样六个必需节；三个节点为 retired/retired/paused，无 active 节点。
- `get_eligibility H-0003` → `eligible:false`，reasons `[GATE_NOT_PASSED, RECHECK_PENDING, CONFIRMATION_REQUIRED]`，outcome `inconclusive`，`open_obligations: []`；`get_eligibility H-0001` 另含 `DISPOSITION_RETIRED`。`obligations {}` → `[]`。

### 逐条判据
- (a) 1-seed 筛选结果登记为 inconclusive 且节点不被强制 prunable：**通过**（EV-0005；效应恰为 0.0，"很小"，不是"轻微负向"——工具链没有产生负向值，见 §6-4）。
- (b) 达到 seed 上限、接近门槛时保持 inconclusive：**部分通过**。三个节点都在 3 个 seed 上限处保持 inconclusive、没有被强制定论；但没有出现"正效应接近 +0.5"的场景（最大正效应 +0.083；H-0002 为 −0.417，量级接近门槛但方向为负），所以"接近门槛"没有被严格检验。
- (c) 基于不确定结果的决定有 缺失证据/下一实验：**通过**（D-0034、extend-to-3-seeds、inconclusive-and-pause、not-go 报告；经文件内容核对）。
- (d) retire/pause 带证据与复议条件：**通过**（DEC-0009/0010/0019 的 `based_on` 含 EV 与文档；hypothesis 上 `reconsider_when` 非空）。
- NOT GO 需无 active 节点且有六节报告：**通过**（两次）。
- 任务验收带 evidence_ids：**通过**（T-0001..T-0005 的 `accepted_evidence` 均含 EV 与交付文档）。
- 三档（screen/replicate/confirm）与确认 seeds 的实际使用：**未覆盖**（没有节点过门槛；确认 seeds 101–103 从未使用；所有实验 `stage: screen`）。obligation 账本阻止 GO：**未覆盖**（账本为空，无 review/STAT_MISMATCH 触发；本批无 reviewer）。停滞计数：只验证了 `note_findings` 每批登记 1 条且 `stall_state: none`，未触发 structural/human 阈值。

## 5. 人为介入记录

自然流程中 Leader 已覆盖 (a)(c)(d) 的大部分，但 H-0001/H-0002 是 3-seed 筛选而非 1-seed，且第一批后 Leader 自行 NOT GO。为覆盖 1-seed→3-seed 路径，我按任务书用用户身份下达了指令 1，并为触发第二份 NOT GO 报告下达指令 2（见 §1）。其余步骤没有干预。

## 6. 发现的问题与可疑行为

1. 项目 `not_go` 后，一条用户指令即可让 Leader 把项目改回 `active`（DEC-0014）。与 M1 观察 1 相同；是否应由用户明确"重开"而非 Leader 自行判断，需对照 06 §3.3 决定（本批没有被接口拒绝）。
2. 页面 15 条"曲线缺失"：`build_site.py::load_curve` 要求 JSON 对象（等长数值序列），而测试项目的 toytrain 写 `curve.csv`，manifest 的 `curve_path` 指向 csv。需要确认是 fixture（make_rt_test_project.py）还是插件契约的问题；Leader 自己还起草了一个 bug report（UI 里 "Bug report drafted: build_site expects JSON curve files"），未发送。页面 `--check` 不受影响。
3. Leader 在 NOT GO 前自行写并运行 `outputs/analysis/optimum.py`（牛顿法求训练损失最小值点，读取验证集准确率，90.25）作为"该不该继续投入"的依据，并在 NOT GO 报告里用它排除新方向。它声明"只用于判断是否还有值得投入的方向，没有据此调整方法"，但它读取了验证集准确率来影响是否继续的决定，近似使用保留数据做搜索决策，且不是登记的 run/Evaluation。值得评审是否应被约束。
4. Leader 在 NOT GO 报告中引用了 2 次网页搜索（只读摘要、没缓存为 literature 文档），自己标明了"不是新颖性依据"；这违反"文献须缓存为文档"的习惯但已如实标注。
5. 1-seed 结果的 `outcome_reason`："effect 0 over 1 pair(s): neither clear of 0.5 nor a negative signal over 3 pairs"。后半句的"3 pairs"是负向信号要求的配对数，但与前半句"1 pair"并排读起来像笔误，文案可改清楚。
6. 扩 seed 的记录方式：`decide` 无法改 seeds，E-0005 的 `seeds` 在原实验上由 1 变为 [1,2,3]（EV-0005 作为 revision 1 保留，EV-0006 为 revision 2）；Leader 因此用决定文档加任务请求文档来记录"扩展"，数据库里没有一条"seed 扩展"决定记录（DEC 列表中没有对应条目）。可审计性依赖文档；设计上是否要求决定记录，请核对。
7. 结果文档 outcome 标签写成 "uncertain"（H-0001 的 v1）与 H-0003 第一步的类似错误：worker 提交后被接口纠正（result v2）；Leader 自述 `create_experiment` 的 kind 取值与请求文档不符，worker 改用 method。不影响结果，说明请求模板与接口词汇有小偏差。
8. 冻结前 Leader 审核发现 `stats.py` 的平局判定与接口不一致（0.5 的差会被误判为正向），已在 harness@8106e0f 前修复；这属于测试 fixture 的缺陷，如有同源应回查 make_rt_test_project.py。
9. Leader（主会话）effort 为 xhigh（默认），未按 14 §4.2 设置 `/effort medium`；本次未单独设置。
10. 没有出现权限提示卡死，没有出现 `prompt.submit` 之类的 M1 已修复错误。

## 实施者处理（主 agent）

| # | 问题 | 处理 |
|---|---|---|
| 1 | NOT GO 后用户指令可让项目恢复 active | 设计如此：结项后恢复研究须引用现行用户指令（规则“恢复研究的前提”，接口要求 based_on user_instruction）；由用户决定，不视为缺陷 |
| 2 | 曲线缺失：夹具只写 curve.csv | 夹具缺陷：`make_rt_test_project.py` 的 toytrain 另写 `curve.json`（`{"step", "loss"}`，插件的曲线契约），后续批次测试使用 |
| 3 | Leader 用 outputs/analysis/optimum.py 的未登记数字支持 NOT GO | 记录；属 B 类判断的证据质量问题，M4 起 GO/NOT GO 前的跨模型评审与 M7 经验约束覆盖，不在本批次改接口 |
| 4 | 未缓存的网页检索写进 NOT GO 报告 | 记录；M6 文献工具的存在性核验覆盖 |
| 5 | outcome_reason 把“3 pairs”写得像笔误 | 已修：改为“nor below -gain with at least N pairs (what a negative signal needs)” |
| 6 | 扩展 seed 无决定记录 | 扩展 seed 是 A 类执行动作，记录在实验与 evaluation revision；不需要决定记录 |
| 7 | 请求文档词汇与接口不一致 | Leader 写的请求文档问题，接口拒绝后自行更正；记录 |
| 8 | Leader 写的 stats.py 把 0.5 视为过门槛 | Leader 生成的框架代码问题（非夹具），冻结前已自行修正；记录 |
| 9 | Leader 默认 effort xhigh | 测试执行偏差，记录；后续批次按 14 §4.2 设 /effort medium |
| — | Leader 无 observed 模型记录 | M4 中修复：主会话的 observed 模型以 actor rld/main 记入 agent_models.jsonl（跨模型评审的族判定依赖它） |
