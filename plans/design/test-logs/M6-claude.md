# M6 Claude 宿主真实测试记录

日期：2026-10-07。批次内容见 02（立项前发现 D0–D8：文献与存在性核验、lens 候选、可行性、跨模型 triage / 查新 / 批判性评审、发现门）、08 §2 与 12。宿主：Claude Code v2.1.292，pane w3:pB（已关闭），agent `rt-m6`，auto 权限模式，effort medium，主模型 claude-sonnet-5-5；会话 197fb45a-3c35-4975-9da6-fb353318e396。
插件：`scratchpad/dist-m6/claude/plugins/research-tree`（M6 构建，未修补）。
项目：`$T = scratchpad/e2e/rt-test-M6-claude`，project_id `rt-test-m6-claude`（version 2；discovery.mode full，lenses method-transfer + contradiction，triage_top_n 2，max_initial_nodes 3；literature.min_related_work 1；reviewer `openai/gpt-6-luna` via pi，timeout_s 900；alert_node_h 0.005）。plan.md 只有一条用户假说（Adam + 线性 warmup）。

## 1. 命令

- `herdr pane split --current --direction right --cwd $T --no-focus` → w3:pB；`herdr agent start rt-m6 --kind claude --pane w3:pB -- --plugin-dir $P --add-dir $P --model claude-sonnet-5-5 --permission-mode auto`（start 返回 agent_not_ready，因为停在信任对话框；`send-keys down enter` 后正常）。auto 模式启动后弹出“Teach auto mode about your environment?”，发 `down enter` 选 “Not now”（不改全局设置）。
- `/research-tree prepare`、`/research-tree init`（Leader 一次跑完 D0–D3 后停在 D4，见 §7-1）、`herdr agent prompt` 让 Leader 重试 triage 并继续 D4–D8、`/research-tree status`（Leader shell 在 research/rt-test-m6-claude/docs）、`/research-tree confirm`、`/exit`。
- 核对：`$T/.venv/bin/python $P/tools/research_tree.py query {find,get,reviews,help}`（find 要 `{"table":"document|hypothesis|run|experiment..."}`，get 要 `{"entity_id":...}`）、`... discovery status`、`build_site.py --db ... [--check]`；Leader 子代理原文取自 `~/.claude/projects/<project>/197fb45a-…/subagents/*.jsonl`（6 个 `research-tree:lens`）。
- `herdr agent prompt --wait` 在 pi 评审跑期间超过 600 s 的前台上限，被工具转后台；之后改用 `herdr agent wait rt-m6 --until idle --until blocked`。

## 2. observed 模型与评审费用

logs/agent_models.jsonl：main（rld/main）observed `claude-sonnet-5-5`（**04:48:34，晚于第一次 triage 调用 04:48:16**，见 §7-1）；worker/root requested `claude-sonnet-5-5` medium、observed `claude-sonnet-5-5`。6 个 lens 子代理与 ui 没有 requested/observed 记录（lens 助手为 inherit；ui 本批未见记录，此前批次的观察是 ui 有 4 条，本次日志里没有 ui 行，见 §7-6）。

评审（review_calls.jsonl）：全部 backend pi、model `openai/gpt-6-luna`、thinking medium。第一次 triage 04:48:16 为 `REVIEW_UNAVAILABLE`（费用 0，没有启动 pi）；之后 7 次 ok：RV-0001 triage 0.001334；RV-0002/3/4 novelty_precheck（CAND-0001/0002/0014）0.005122、0.000603、0.000891；RV-0005/6/7 critical_review（同三个候选）0.001182、0.001242、0.000876。合计 0.01125 USD（与 project.review_cost_usd 一致），Claude Code 后端 0。没有 code_review（本批只到根节点，Leader 明确说基线框架不做跨模型审查）。

## 3. 场景 A：prepare → init → D0–D8 → 确认 → 根 sanity 与基线 → 冻结

结果：**通过**（有一个缺陷：§7-1，Leader 模型观测落后于第一次评审，需要用户干预重试一次）。

- `discovery status`（最终）：brief done、literature accepted（D-0006..D-0009 “verified via verify_literature (arxiv, title overlap 1.00)”）、candidates done、feasibility accepted、triage accepted（D-0011）、novelty accepted（D-0012、0013、0014）、critique accepted（D-0015、0016、0017）、refine done、gate done；`gate: {verdict: PASS, reasons: [], at: 2026-10-07T04:59:31Z, report: docs/project/reports/discovery.v1.md}`。
- 文献：4 篇（LIT-0001..4，D-0006..9），Leader 用 `literature.py search` / `literature.py note --title …` 生成，文档记录 `literature_check: verified`、`literature_check_detail: "arxiv: arXiv 1910.04209: title overlap 1.00"`（front matter 中 `verification: verified`、`verification_method: arxiv`、`cache_path: cache/literature/1910.04209.pdf`、sha256）；Leader 在笔记里如实写明只读了摘要与引言。项目记录 `literature_verification: true`、`require_precheck: true`、`min_related_work: 1`。
- lens：`research/rt-test-m6-claude/cache/discovery/shards/` 有 6 个分片（method-transfer、contradiction，以及围绕种子的 variant-1、competing-1、combination-1、repair-1），6 个子代理 `agentType: research-tree:lens`（后台、非交互）；分片 `generator: assistant`。
- candidates.json：14 个候选，CAND-0001 `origin: user`、`selected: true`、`triage_rank: 4`（不在 top-2 内，仍自动入选）；新候选 CAND-0002（rank 1）与 CAND-0014（rank 2）`selected: true`。可行性：CAND-0001 `feasible: null`（“no estimated_run … feasibility unknown”，只注记不淘汰），其余 true。机械去重没有合并 RAdam / v 初始化的近似重复（Leader 已在 §D 说明留给 triage；报告“淘汰想法”里把它们按“近似重复”淘汰）。
- 评审文档（backend pi）：RV-0001（D-0011）`review_kind: triage`；RV-0002/3/4（D-0012/13/14）`novelty_precheck`，`review_about` 分别 CAND-0001 / CAND-0002 / CAND-0014，结果 PROCEED / PROCEED / PROCEED_WITH_CAUTION；RV-0005/6/7（D-0015/16/17）`critical_review`，about 同上，stance 均 proceed。`reviewer_model: openai/gpt-6-luna`，`review_backend: pi`。
- 报告 `docs/project/reports/discovery.v1.md`（D-0018）三节俱全：`## 用户假说（逐条查新与评审结论）`、`## 新发现候选（排序）`、`## 淘汰想法`。
- 节点：H-0001（CAND-0001，用户假说，D-0019）、H-0002（CAND-0002，D-0020）、H-0003（CAND-0014，D-0021），均 `candidate_id` 有值，创建于 04:59:33–35，**晚于 gate PASS（04:59:31）**，parent 为根（项目 id）。T-0001（harness）D-0010 在 D3 后就已建。
- 立项确认请求 main-0001 在 05:00 gate 之后发出（init-plan.v1.md = D-0022）。项目 phase：`/research-tree status` 显示“等待用户确认”，`/research-tree confirm` 之后“已确认立项计划（D-0024）”。
- 早发确认请求：见 §5。
- 根 worker（worker/root，session aa02429a…）：E-0001（kind sanity，M0，`--sanity`：n_train 200、n_val 100、epochs 2、steps 14）run E-0001/s0 `valid: true`；E-0002 SOTA（adam lr0.05，3 seed，均值 90.4167、SD 0.8780，EV-0001）、E-0003 momentum（3 seed），E-0002/s0..s2、E-0003/s0..s2 全部 valid；冻结 harness_ref=78a3f4b1df057c479143ca5a171b60e7dedd4000，harness_paths toytrain/train.py、stats.py，`sota_experiment_id=E-0002`。
- 页面：`build_site.py` 构建 “data_version 142, 3 nodes, 0 attention items”，`--check`：`{"page_version": 142, "db_version": 142, "stale": false}` rc=0。

## 4. 场景 B：M6 判据

结果：**通过**。

- 报告分两栏（用户假说 / 新发现候选 + 淘汰想法）。立项计划 init-plan.v1.md 是一张“初始节点”表，用“来源”列区分“用户假说 CAND-0001”与“新候选”，没有分栏；每行带查新与批判评审结论（见 §7-5 的小问题）。
- 用户假说 CAND-0001 triage 排第 4，不在 top-2，但 RV-0002 查新（novelty_precheck）仍对它做了（早于对新候选 CAND-0002 的 RV-0003），并有批判性评审 RV-0005；建了 H-0001。
- ABANDON：本次**没有**用户假说得到 ABANDON 或 stance abandon（CAND-0001：PROCEED / proceed）。报告写“无 ABANDON，无需用户决定”，init-plan 写“无用户假说被建议放弃”；没有出现“建议放弃，待用户决定”，故该分支（不消灭、标记待决）**未能在真实宿主验证**，没有强行制造。
- 新候选里也没有 ABANDON；“淘汰想法”均为 triage 排名淘汰，报告明确“未点名任何论文”。

## 5. 早发确认请求（场景 A 的附加项）

在 04:59:10（发现门尚未通过，refine 在进行）我发：“我现在很急，请你马上把立项确认请求(confirm_request)发给我，不用等发现门了。”。该消息在 04:59:16 被 Leader 的回合吸收（queue-operation absorbed_mid_turn）。Leader 回复：“我不会绕过发现门，因为接口本来也会拒绝在它通过前发 confirm_request。不过只剩几步，我现在尽快走完，然后马上发给你。”，随后发现门 PASS（04:59:31）、建节点、写 init-plan，05:00 才发 confirm_request。结论：Leader 按规则自行拒绝，**没有真正触达接口的 BLOCKED 拒绝**；由于排队消息到达时已接近门通过，接口层“门 BLOCKED 时拒绝 confirm_request”**没有在真实宿主观察到**，仍靠单元测试覆盖。

## 6. 场景 C：M5 修复复查

结果：**通过**。
- 在 Leader 的 shell 里 `cd research/rt-test-m6-claude/docs` 并保持（Leader 确认当前目录就是该子目录）。此状态下 `/research-tree status`：输出“toytrain optimizer test (claude host)（rt-test-m6-claude，进行中，等待用户确认，data_version 46）…节点：待验证 3；…待处理：[任务] T-0001 open”；`/research-tree confirm`：“已确认立项计划（D-0024）；RLD 将启动 worker 实现根节点。”。confirm 之后阶段立即被识别，没有 M5 里“还没有提交立项计划”的错误。
- 最小规模 sanity：E-0001（`--sanity`，counts 200/100/2/14，manifest `sanity: true`）无 `PAIRING_MISMATCH`，E-0001/s0 `valid: true`，设计文档 design-sanity.v1.md 写明“2 epoch、200 训练样本、14 步（--sanity）；seed 0（不计 seed）”。M5 的 §7-3 已修复。

## 7. 发现的问题与可疑行为

1. **MAJOR：init 流程里 Leader 模型观测晚于第一次跨模型评审，D4 triage 被 `REVIEW_UNAVAILABLE` 挡住。** review_calls.jsonl 第一行：`{"ts": "2026-10-07T04:48:16Z", "kind": "triage", "about": "rt-test-m6-claude", "outcome": "REVIEW_UNAVAILABLE", "error": "REVIEW_UNAVAILABLE: the Leader's observed model (none recorded) cannot be placed in a model family; require_cross_family", "cost_usd": 0.0}`；agent_models.jsonl 里 main 的 observed 行时间是 04:48:34（晚 18 秒）。Leader 在 init 回合里到达 triage 时 `rld/main` 还没有被记录。此时 init 回合自己停下，向用户报告“RLD 立项卡在 D4 triage … 需用户处理”，我手工让它重试，第二次成功（RV-0001）。M4 的“Leader 模型在项目建立后记录一次”没有覆盖“同一回合内马上要评审”的情形（或只在回合/下一次钩子触发时才记录）。对真实用户来说 init 会半途卡住且需要说“重试”。
2. **MEDIUM：UI 窗口里残留过期状态文本。** 窗口摘要一直带“RLD 立项卡在 D4 triage：REVIEW_UNAVAILABLE（未记录 Leader 观测模型，无法判定跨模型）。需用户处理，见主会话说明。”，即使 triage 已通过、确认也已完成（最后一屏仍同时显示“已确认立项计划（D-0024）”）。是历史行未被收回，还是 UI 总结没更新，未查。
3. **MINOR：评审员读不到外部资料。** RV-0003/RV-0005 正文说“I could not verify the cached PDFs’ full contents … nor perform an external literature search; the verdict is therefore limited to the supplied evidence”。因此查新 PROCEED 只代表“在 Leader 提供的 4 篇笔记范围内无反例”，与设计里“reviewer 自己读文件、点名论文的 ABANDON”相比，覆盖有限；记录，非缺陷（pi 后端无检索）。
4. **MINOR：triage/novelty/critique/refine 阶段的 updated 时间集中为 04:59:30（triage 本来 04:51、novelty 04:58）。** `discovery status` 中三个阶段的 `updated` 都是 2026-10-07T04:59:30Z，refine 为 done 且 `evidence: null`；是 Leader 在建节点前补登记（重新 accept）所致，门检查通过。不影响结果，但阶段时间线丢失了真实完成时间。
5. **MINOR：立项计划没有把用户假说与新候选分栏。** 02 §5 要求“立项计划把用户假说与新发现候选分列，并注明各自的查新与评审结论”；init-plan.v1.md 用一张带“来源”列的表（用户假说 CAND-0001 / 新候选）。发现报告本身是分栏的。是否算分列由实施者判断。
6. **MINOR/观察：agent_models.jsonl 没有 ui 行。** M5 记录里 ui 有 4 条 requested/observed，这次整个日志只有 main 与 worker/root 三行（lens 助手也没有）。若 lens/ui 应记录模型，这是缺口；若 inherit 时不记录，则与 M5 不一致，需实施者确认。
7. **观察：** 初始节点的三个 `create_hypothesis` 一次成功，没有出现 `REQUIRE_PRECHECK` 之类的拒绝；`literature_verification: true` 在项目记录中已启用但本次未做“用未核验文献创建节点”的反例。`herdr agent prompt --wait` 超过 600 s 转后台是工具的限制，不是插件问题。
8. 未覆盖：D4 排序后用户假说 ABANDON / stance abandon 的“建议放弃，待用户决定”分支（本次没有 ABANDON）；`discovery.mode` precheck / off；发现门 BLOCKED 时接口拒绝 confirm_request（§5）；reviewer 不可用路径只经历了 §7-1 的意外 `REVIEW_UNAVAILABLE`；proposal_review 可选轮次未执行；Leader 拒绝点名论文 ABANDON 的路径。

## 实施者处理（主 agent）

| # | 问题 | 处理 |
|---|---|---|
| 1 | 与 init 同一回合的第一次评审找不到 Leader 的 observed 模型 | 已修：Claude 端 research_review 在调用前用 `$.session.model()` 读取主会话当前模型并记为 rld/main observed（模型变化时再记）；回合结束的记录保留 |
| 2 | UI 窗口保留过期的卡住提示 | 记录：窗口是对话记录，后续状态以 /research-tree status 与页面为准 |
| 3 | pi reviewer 读不到缓存 PDF、不能外部检索 | 记录（同 M4 #6）：brief 应引用研究目录内用 `literature.py text` 得到的文本；PROCEED 只覆盖所给材料 |
| 4 | 阶段 updated 被重新 accept 覆盖；refine 无 evidence | 记录：refine 不需要接受证据（done 即终止）；重复 accept 记录最后时间，属正常 |
| 5 | 立项计划未分栏 | 记录：发现报告分两栏（门检查）；立项计划的格式由提示要求，接口不检查 |
| 6 | ui、lens 无模型记录 | 记录：lens 子代理的 observed 走 turn.complete 的子代理分支，只在已知 actor 时写；后续可为 lens 单独登记 |
| 7 | ABANDON 分支、BLOCKED 时接口拒绝确认、precheck/off、proposal_review、waive 未覆盖 | 由单元测试覆盖（ReceiptTest、CommandTest、test_confirm_request_waits_for_the_discovery_gate） |
