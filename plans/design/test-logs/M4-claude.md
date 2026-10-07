# M4 Claude 宿主真实测试记录

日期：2026-10-07。批次内容见 12 §1（M4：跨模型 reviewer 后端 pi/Claude Code CLI、GO 候选五维复核）。宿主：Claude Code，pane w3:p9（已关闭），agent `rt-m4`，auto 权限模式，主会话 claude-sonnet-5-5（界面显示 effort medium，未执行 `/effort`，避免写入全局默认）。
插件：先用 `scratchpad/dist-m4/claude/plugins/research-tree`（M4 构建），因 §7-1 的缺陷后改用 `scratchpad/dist-m4-patched/research-tree`（仅把 `hooks/register.tsx` 中 research_review 的 `3_900_000` 改成 `600_000`，其余与构建一致；源码仓库 rt-m4 未改）。
项目：`$T = scratchpad/e2e/rt-test-M4-claude`，project_id `rt-test-m4-claude`（research-tree.yaml version 2，evidence_policy.profile screening，minimum_practical_gain 0.0，review.trigger candidate_ready，models.reviewer openai/gpt-6-luna、timeout_s 900、require_cross_family true）。

## 1. 命令

- `herdr pane split --current --direction right --cwd $T --no-focus`；`herdr agent start rt-m4 --kind claude --pane w3:p9 -- --plugin-dir $P --add-dir $P --model claude-sonnet-5-5 --permission-mode auto`；信任对话框用 `send-keys down`、`send-keys enter`。
- `/research-tree prepare`、`init`、`confirm`（见 §7-2 的曲折）、`build`、`config apply`（三次，对应场景 C、D 和恢复）。
- 修补构建后 `/exit`，再以同样参数加 `--resume e65bff06-…` 重启一次（场景 B 的第一次尝试之前），之后又为让 Leader 模型记录先于评审写入重启一次（§7-3）。会话和项目状态保留，没有重做项目。
- 场景 C/D 由我（作为用户）直接编辑 research-tree.yaml 的 `models.reviewer.model`，再 `/research-tree config apply`。
- 查询：`$T/.venv/bin/python $P/tools/research_tree.py query {get_eligibility,reviews,find,go_candidates,help}`；`build_site.py --db … [--summary|--check]`。

## 2. observed 模型（research/rt-test-m4-claude/logs/agent_models.jsonl）

- worker/root：requested `claude-sonnet-5-5`（medium），observed `claude-sonnet-5-5`。
- **只有 worker/root 有记录**：H-0001/H-0002 的 worker（h1、h2）全程没有 requested/observed 记录（M3 里每个 worker 都有）。见 §7-4。
- rld/main observed：**第一个会话里始终没有**（见 §7-3）；resume 重启后 03:51:40 才第一次写入（在已经失败的评审之后），再次重启后 03:52:40 又写一条，均为 `claude-sonnet-5-5`。
- reviewer：不记在 agent_models，记在 RV 文档 front matter：`model_requested`/`model_observed` 均为 `openai/gpt-6-luna`。

## 3. 场景 A：prepare → init → 规划 → confirm → 根 worker sanity 与基线 → 冻结

结果：**通过，但手工绕过了一处缺陷（§7-2），且 rld/main observed 判据在第一个会话不成立（§7-3）**。

- metric_spec D-0002、min-setup v1（D-0004）被 create_project 拒绝（列了 yaml 里没有的 final_loss/train_time_s），Leader 换 v2（D-0006）；Leader 在立项计划中指出 minimum_practical_gain 0 与原文 0.5 的不一致，并等用户决定。
- 基线 E-0001..E-0004（根 worker），H-0001 的 E-0006（Adam warmup，paired +0.25/0/0 pp，EV-0004 gate_passed，positive_signal），H-0002 的 E-0005/E-0007（H-0002 记为 prunable，disposition 不再投入）。冻结 harness 后 H-0001 变 beats_sota，`stage: candidate_ready`。
- Leader 的最终报告提到框架写的 usage.json 的 job_id 与预留不一致、两个 worker 都改写过，Leader 只记入最终报告。
- `build_site.py --check` 构建后返回 `{"page_version": 315, "db_version": 315, "stale": false}` rc=0。

## 4. 场景 B：reviewer 可用（pi 后端），GO 候选的五个 candidate_recheck

结果：**通过（评审机制）；GO 未放行，原因是 reviewer 给出 uncertain，不是机制故障**。

- 前置：`get_eligibility('H-0001')` → `eligible:false, reasons:[RECHECK_PENDING], stage:candidate_ready, gate_passed:true, recheck_evaluation_id:"EV-0004"`，rechecks 五项均 missing（numbers/protocol 需 EV-0004，method_code/novelty/theory 需代码 d2da516b…）。
- brief：Leader 在 `docs/reviews/briefs/H-0001-{numbers,protocol,method_code,novelty,theory}.v1.md` 写好五份，每份约 1.1 KB，内容全是：假说文档路径、EV-0004/E-0006/EV-0001 的 ID、方法代码与 harness 的 commit、代码目录、结果文档/交付文档路径、protocol/metric-spec/min-setup 路径、metrics 文件路径、已缓存文献路径。判断：**没有 Leader 或 worker 的总结与倾向**（引用的 result 文档是 worker 的产出，但只作为路径）。五份除标题的维度名外内容相同；维度差异由 kind/dimension 提示承担。
- 第一次尝试（未修补构建）五次都失败，见 §7-1；第二次（修补构建）因 Leader 模型记录缺失再失败五次，见 §7-3，Leader 两次都如实上报，没有自评代替，也没有手动声明自己的模型族。
- 最终成功的五次调用（逐个，每次约 40–60 s）：RV-0001（numbers，uncertain，D-0032）、RV-0002（protocol，uncertain，D-0033）、RV-0003（method_code，**pass**，D-0034）、RV-0004（novelty，uncertain，D-0035）、RV-0005（theory，uncertain，D-0036）。费用 0.000652 / 0.000626 / 0.000771 / 0.001363 / 0.000541 USD。
- 判据逐项：
  - `docs/reviews/RV-000{1..5}.v1.md` 已登记；document 表 `author_role: reviewer`、`author_id: pi`、`doc_type: review`、`review_kind: candidate_recheck`、`review_backend: pi`、`reviewer_model: openai/gpt-6-luna`、`basis_evaluation_id: EV-0004`、`basis_code_ref: d2da516b…`。
  - front matter `backend: "pi"`、`model_requested`/`model_observed: "openai/gpt-6-luna"`、`terminal_reason: "stop"`、`permission_denials: []`、`raw: "cache/reviews/RV-000N.v1.jsonl"`。原始输出在 `cache/reviews/RV-0001..5.v1.jsonl` 与 `sessions.json`。
  - `logs/review_calls.jsonl`：每次 `started` 后跟 `ok`（带 review_id、backend pi、model、cost_usd）。
  - `get_eligibility` 的 rechecks 行带 `review_id`、`path`、`result`、`backend: "pi"`、`reviewer_model: "openai/gpt-6-luna"`、`evaluation_id`、`code_ref`。
  - GO 资格：`eligible:false, reasons:[RECHECK_PENDING, RECHECK_UNCERTAIN]`。该状态是预期的：只有 method_code pass，其余四维 uncertain，没有维度 fail。站点 attention 有 `recheck_pending`（“待跨模型复核”，列出 numbers/protocol/novelty/theory 不确定）。没有放行 GO，所以“全部通过才放行”只验证了不放行的一侧（没有造出全 pass 的候选）。
- reviewer 的内容有实质：numbers 指出结果文档 final_loss 区间末位与 E-0006/s1 差第 5 位小数、“远小于噪声”无噪声估计；protocol 指出 seed 0 曾导入被拒后覆盖重跑，现有证据核实不了；novelty 指出 RAdam 是相关先例、没做恒定较小 lr 对照、pi 读不到缓存的 PDF（read-only，不能检索）；method_code 认为 AdamWarmup 确在训练循环里被用到，默认总步数 1140 写死。
- Leader 在 reviewer 结果之后的处置：reviewer 结论与它此前的判断一致，倾向 H-0001 不再投入、NOT GO（我没有让它继续，输入框里还留着一条未提交的建议文本，见 §7-6）。

## 5. 场景 C：reviewer 不可用

操作：yaml 把 `models.reviewer.model` 改为 `openai/gpt-0-missing`，`/research-tree config apply`（登记 D-0037/用户指令 D-0038），请 Leader 对 H-0002 做 novelty_precheck。结果：**通过**。

- `review_calls.jsonl`：`{"kind":"novelty_precheck","about":"H-0002","outcome":"REVIEW_UNAVAILABLE","error":"REVIEW_UNAVAILABLE: pi does not list openai/gpt-0-missing","cost_usd":0.0}`，没有 started 记录（没有调用 pi 进行评审）。
- 没有新 RV 文档（仍只有 RV-0001..5）。站点 attention：`{"kind":"review_unavailable","id":"H-0002","text":"novelty_precheck H-0002：REVIEW_UNAVAILABLE: pi does not list openai/gpt-0-missing","label":"评审不可用"}`。
- Leader 写好 brief（`H-0002-novelty-precheck.v1.md`，只含文档、文献、代码版本、目录、结果文档路径，对 context 的注释是“仅作背景”），原文汇报错误，没有自评，H-0002 状态不变，并明确说“要真正跑评审需要把 reviewer 改回 pi 能列出的模型”。

## 6. 场景 D：同族（R04）和场景 E：守卫

D 结果：**通过**。yaml 改 `anthropic/claude-sonnet-5-5`，config apply，请求同一评审。`review_calls.jsonl`（两条，Leader 重试了一次）：`REVIEW_UNAVAILABLE: reviewer anthropic/claude-sonnet-5-5 is the Leader's family (claude-sonnet-5-5); require_cross_family refuses the call`，cost 0，没有 `started`，所以 `claude` CLI 未被调用；没有新 RV 文档。之后 yaml 恢复为 openai/gpt-6-luna 并 config apply。

E 结果：**通过**。
- 让 Leader 用 Bash 运行 `pi -p "hi"`：被插件拦截，原文 `research-tree: 评审只经 mcp__research-tree__research_review 调用，它登记 review 文档并记录费用；不要直接运行 pi。`
- `research_db`（actor `reviewer/x`，method get，entity H-0001）：`reviewer 身份只属于 review_call.py；评审用 research_review。`
- Leader 没有换办法重试。

## 7. 发现的问题与可疑行为

1. **MAJOR：`research_review` 在 Claude 宿主完全不可用（超时参数超限）。** 复现：未修补构建，Leader 调 `research_review(kind=candidate_recheck, dimension=numbers, evaluation=EV-0004, brief=docs/reviews/briefs/H-0001-numbers.v1.md, about=H-0001)`，五次全部返回：`research-tree 内部错误：research-tree: process.run: init.timeoutMs is a whole number of ms, 1 to 600000 (host check)`。原因：`hooks/register.tsx` 约第 1220 行 `runTool($, cfg, 'review_call.py', args, 3_900_000)`，宿主 `process.run` 上限 600000 ms（`MAX_PROCESS_MS = 600_000`）。与 reviewer 配置无关。Leader 误以为是 `timeout_s: 900` 超限，建议用户改成不超过 600（不是原因，但提示有误导）。我用修补构建（把 3_900_000 改成 600_000）继续；注意 600 s 的宿主上限小于 review_call.py 允许的 `MAX_CALL_S = 3600`，长评审在宿主层会超时，需要设计取舍（例如后台运行/轮询）。
2. **MAJOR：`/research-tree confirm` 与项目 phase 依赖 shell 当前目录；Leader 在规划阶段 cd 进子目录后，`post_to_ui(confirm_request)` 没有把 phase 置为 awaiting_confirmation**（`project.phase` 仍是 `planning`；`.research-tree.json` 在项目根，`loadProject` 用 `$.session.cwd()`）。现象：两次 `/research-tree confirm` 都返回“RLD 还没有提交立项计划，暂时无需确认。”，之后 `/research-tree build`/`confirm` 返回“当前目录没有研究项目”，Leader 用 Bash `pwd` 回答后 cd 回项目根才好。同时 main-0001、main-0002 两条 confirm_request 已发出。我手工执行 `research_tree.py phase --set awaiting_confirmation` 并让 Leader cd 回根目录，之后 `confirm` 成功（界面“已确认”）。这与 M3 §7-2（接口依赖 cwd）同类，但这里连 phase 状态机也失效，且报错（“还没有提交”）与原因（cwd）不符。另：我发的自由文本确认没有被插件登记（Leader 明确说“主会话里收到的确认，插件不认”）。
3. **MAJOR：Leader 的 observed 模型记录写入太晚，早期评审被 `REVIEW_UNAVAILABLE: the Leader's observed model (none recorded) cannot be placed in a model family; require_cross_family` 拒绝。** `turn.complete` 里才写 `rld/main` observed，且 `observedModels.set('main', …)` 在判断项目状态是否已加载之前执行：第一个会话的第一个 turn 在项目存在之前结束，就再也没写；resume 后的第一个 turn 里评审工具调用发生在 turn 结束之前，记录在 03:51:40 才出现，五次评审（03:51:19–03:51:32）已失败。一次性重启后先跑 `/research-tree build` 和一个短 prompt，才有记录，评审才通过。判据“agent_models.jsonl 有 rld/main observed”在第一个会话里不成立。Leader 的处理正确（拒绝自称模型族）。
4. **agent_models 缺少 H-0001/H-0002 worker 记录**：h1（agent ac21383fb6fb64303）、h2 全程没有 requested/observed（只有 worker/root）。原因未查（可能与 observedModels 内存缓存或 agent→actor 映射有关）。
5. brief 里的结果文档路径指向 worker 写的文档（只作路径传入），不违反“不含总结”的要求，但 reviewer 读到的是 worker 的叙述；这是设计选择，记录之。pi 的 reviewer 读不到研究目录之外的文件（Leader 用 `add_dirs` 传了 wt-h1 和 code，对 pi 后端是否生效我没有核实）；novelty 评审自述读不到缓存的 PDF 且不能检索，所以只给 uncertain。
6. **多出一次评审**：04:00:43–04:01:34 有一条 `novelty_precheck H-0002 ok`（RV-0006，`PROCEED_WITH_CAUTION`，pi，gpt-6-luna），不是我在场景 C/D 之后主动要求的。我恢复 yaml 并 config apply 之后，Leader 的输入框里有“reviewer 模型已改回 gpt-6-luna，请重发”这样的文本（疑似输入建议/排队文本被提交），Leader 按它重发并成功。多花 0.0xx USD，属于测试流程副作用，不是插件缺陷；但说明 herdr `agent prompt` 与输入框里的残留文本会混在一起，需留意。同样，`agent wait` 在 prompt 刚发出时常立刻返回 idle/done，需用文件状态确认。
7. 其余：Leader 在 init 时报告“min-setup v1 被 create_project 拒绝”，和 M3 的 metric 不一致同类；`scratchpad/w.sh` 这个共享脚本被另一位测试者（rt-m5）覆盖过，我改用自己的 `w4.sh`。

## 8. 场景结论

| 场景 | 结果 |
|---|---|
| A 全流程 | 通过（手工绕过 §7-2；rld/main observed 在第一个会话缺失，§7-3） |
| B reviewer 可用 | 通过（五份 RV 登记、pi、gpt-6-luna、原始输出、日志、rechecks 行均成立）；GO 未放行，因四维 uncertain；未修补构建下完全不可用（§7-1） |
| C reviewer 不可用 | 通过 |
| D 同族 R04 | 通过 |
| E 守卫 | 通过 |

## 实施者处理（主 agent）

| # | 问题 | 处理 |
|---|---|---|
| 1 | Claude 端 research_review 超时参数 3 900 000 ms 超过宿主上限 600 000 ms，全部调用失败 | 已修：runTool 把超时限制在宿主上限内；Claude 端给 review_call 传 `--deadline-s 570`，整次调用（两轮与预检）在宿主上限之前结束。长评审在 Claude 宿主上受 570 s 限制，记录为已知限制 |
| 2 | Leader 的 shell 不在项目根时，确认请求未改阶段、后续命令报“没有研究项目” | 已修：Claude mod 的所有工具进程都在项目目录（向上找到 .venv 的目录）运行，不再依赖会话当前目录 |
| 3 | rld/main 的 observed 模型记录太晚（项目未加载时已标记为已记录） | 已修：只有项目存在时才标记并写入；init 之后的第一个回合即记录 |
| 4 | h1、h2 worker 无模型记录 | 未复现原因（复用会话不经 agent.spawn，与 M1 观察 7 相同）；记录 |
| 5 | 多跑一次 RV-0006 | 测试流程副作用，非插件缺陷 |
| 6 | pi reviewer 读不到研究目录外的文件 | pi 的工作目录是研究根；add_dirs 只对 Claude Code 后端生效（09 §2.3）。brief 应引用研究目录内的缓存与代码路径；记录 |
| — | GO 的“全部通过”一侧未在真实宿主触发 | 由单元测试 CandidateRecheckTest 覆盖；记录 |
