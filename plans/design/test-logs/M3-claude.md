# M3 Claude 宿主真实测试记录

日期：2026-10-07。批次内容见 12 §1（M3：预算预留、提交协议、unknown 对账）。宿主：Claude Code v2.1.292，pane w3:p8（已关闭），agent `rt-m3`，auto 权限模式，`/effort medium`；
插件 `scratchpad/dist-m3/claude/plugins/research-tree`（M3 构建）。项目：`$T = scratchpad/e2e/rt-test-M3-claude`，project_id `rt-test-m3-claude`（research-tree.yaml version 2，budget.total_limit 先 1500，后降到 665 node-seconds，per_run 1 node × 10m，max_parallel_workers 2，alert_node_h 0.005）。

## 1. 命令

- `herdr pane split --current --direction right --cwd $T --no-focus`；`herdr agent start rt-m3 --kind claude --pane w3:p8 -- --plugin-dir $P --add-dir $P --model claude-sonnet-5-5 --permission-mode auto`。启动时遇到工作区信任对话框（`agent_not_ready`），读后发 `down`、`enter` 信任该目录。
- `/effort medium`（界面提示 "saved as your default for new sessions"，即写入了用户全局默认；协议 §4.2 本身要求此步，此处只记录副作用）。
- `/research-tree prepare`、`init`、规划、`/research-tree confirm`；场景 B 前手工把 `budget.total_limit` 改成 665，`/research-tree config apply`（登记为用户指令 D-0032，config 文档 D-0031）。
- 核对：`$T/.venv/bin/python $P/tools/research_tree.py query {budget_status,find,get,reconcile_submission,help}`；`build_site.py --db research/rt-test-m3-claude/research_tree.db`（先构建再 `--check`；`--summary` 读 attention）。
- 场景由 `herdr agent prompt rt-m3 "<用户指令>" --wait` 发送；`--wait` 在子 agent 仍在工作时就返回 idle，之后用 `agent get` 轮询 status 才能等到真正完成（工具/宿主层面的观察，不是插件问题）。
- 工作者的接口调用原文取自 `~/.claude/projects/<project>/68f9acec-…/subagents/*.jsonl`。

## 2. observed 模型（research/rt-test-m3-claude/logs/agent_models.jsonl）

worker/root（af36c3cb08acefb17）、worker/h0001（a01a08eb35943c24f）、worker/h0002（a4f1974e5daecd1f2）均为 requested `claude-sonnet-5-5`（effort medium）、observed `claude-sonnet-5-5`。主会话 Sonnet 5.5 medium。
之后复用同一 worker 会话的 E-0006/E-0007/E-0008 没有新增 requested/observed 记录（与 M1 观察一致）。无 reviewer 调用（M3 不含）。

## 3. 场景「所有批次」：prepare → init → 规划 → confirm → 根 worker 的 sanity 与基线 → 冻结

判据：数据库状态与文件一致；`build_site.py --check` 通过；每个基线 run 都在预留之下提交。结果：**通过**（有一条站点构建的观察，见 §7-6）。

- metric_spec（D-0002，`project/metric-spec.v1.json`）由 research-tree.yaml 生成：primary accuracy，direction higher，fraction → percentage_point，minimum_practical_gain 0.5，valid_range [0,1]，字段与 yaml 逐项一致；Leader 在立项计划首节主动指出 yaml 的 metric_specs 只含 accuracy、计划原文还有 final_loss/train_time_s，未自行取舍。
- 协议（D-0005，`protocol.v1.json`）：`profile=stage1_confirmed`，`confirmation_seeds=[100,101,102]`，`min_confirmation_pairs=3`，`max_confirmation_candidates=2`，与 yaml 的 verification 一致；项目 `seeds=[0,1,2]`、`screen_budget_node_h=0.05`、`max_parallel_workers=2`、`alert_node_h=0.005`。
  注意：yaml 中 `verification.screening_seeds=[0]`、`replication_seeds=[1,2]`，而 Leader 把搜索 seed 设成 0,1,2（项目 seeds 的前 3 个），筛选实验默认就跑 3 个 seed（见 §7-3）。
- 基线 E-0001/E-0002/E-0003 共 9 个 run，exec_status succeeded、valid=true，每个 run 有 `submission_key`（形如 E-0001-s0）与 `job_id`（`local-E-0001-s0`）；对应 RS-0001..RS-0009，均 `accounting_status=settled`，`submission_phase=attached`，`reserved_units=600`，`actual_units=1`，`accounting_ref=outputs/E-000X-sN/usage.json` 且记录了 `accounting_sha256`。即走完 reserve → claim → attach_job → settle，用量文件 `{"job_id":"local-E-0001-s0","nodes_used":1,"walltime_used_s":1}`。
- 冻结：`harness_ref=e199ab4c2e56b5cd49acd7258dc8dd5735bb3552`，`sota_experiment_id=E-0001`。
- 站点：`build_site.py --check` 一开始返回 `{"page_version": null, "db_version": 246, "stale": true}` rc=1（站点从未构建，`site/` 为空）；构建后 `{"page_version": 246, "db_version": 246, "stale": false}` rc=0；结束时 `{"page_version": 299, "db_version": 299, "stale": false}` rc=0。
- 提交身份与记账的补充（natural，未人为构造）：基线之后 H-0001/H-0002 的 worker 并行跑第一轮筛选（E-0004/E-0005），00:33:13 h0001 对 `E-0005-s0` 和 `E-0005-s1` 的 `reserve_submission` 都返回
  `CodedError: BUDGET_EXCEEDED: 600 node-s do not fit the total budget: 1209 of 1500 committed (settled, reserved or recorded); report to the user, who decides`（此时 H-0002 持有一个 600，另有一个 600 在途）。h0001 没有缩小预留、没有无预留运行，把阻塞原样报告，之后在额度释放后串行完成 E-0005（RS-0013..15）。

## 4. 场景 M3(a)：两个 worker 争用最后额度

准备：基线与第一轮筛选后 `budget_status` 为 committed 15、available 1485（total 1500）。将 `total_limit` 降到 665（= 15 + 一次 600 的预留 + 50）并 `config apply`（D-0032，Leader 记录"项目记录更新了 total_limit"）。Leader 经 reply 重新评估后停止（预算降低不构成判 NOT GO 的理由），之后用户指令：不加 seed，为 H-0001、H-0002 各开一个新筛选实验（H-0001 E-0007：adam_warmup5，H-0002 E-0006：nesterov lr 0.02，各 seed 0），两个 worker 并行提交各自第一个 run；被拒绝时不要绕过、不要调高上限，原文汇报。

判据：只准入一个；另一个 BUDGET_EXCEEDED 并被 Leader 报告给用户，没有绕过；agent 无法自行调高 cap。结果：**通过**。

- 00:40–00:41：h0002 的 `E-0006-s0` 先预留成功：RS-0016（600，`reserved`，之后 attached）。h0001 的 `E-0007-s0` 同时预留被拒（原文，来自子 agent 工具结果）：
  `CodedError: BUDGET_EXCEEDED: 600 node-s do not fit the total budget: 615 of 665 committed (settled, reserved or recorded); report to the user, who decides`
  当时 `budget_status`：`{"limits":{"total":665,...},"committed":{"total":615,...},"available":{"total":50,...},"open_reservations":[{"reservation_id":"RS-0016","submission_key":"E-0006-s0","reserved_units":600,"accounting_status":"reserved","submission_phase":"attached","job_id":"local-E-0006-s0",...}]}`。
- E-0007/s0 此时 `planned`，没有 reservation、claim、进程、输出（worker 报告原文："It has no reservation, claim, process or output"）。Leader 向用户报告了拒绝原文、budget_status、原因（"两个 worker 同时提交，H-0002 的 E-0006/s0 先预留了 600 秒，剩 50 秒"），并问是否重试，没有自行改上限、没有拆小预留。
- E-0006/s0 完成并结算（RS-0016 settled，actual 1）后 committed 回到 16，available 649，无 open reservation。
- 禁止自行调高上限的检查：用户要求 Leader 做一次不带 user_instruction_doc_id 的 `update_project(total_limit=5000)`。第一次因 Leader 的 shell 停在 outputs/ 目录，接口找不到项目（见 §7-2）；回项目根后返回：
  `{"ok": false, "error": "CodedError: BUDGET_EXCEEDED: raising total_limit is the user's decision: pass user_instruction_doc_id, the current user_instruction document that records it (research-tree.yaml, config apply)", "code": "BUDGET_EXCEEDED"}`；total_limit 仍为 665。
- 争用是靠时间重叠出现的（600 单位的预留按 10 分钟上限，而实际只跑 1 秒）：第二个 worker 能通过的唯一办法是第一个预留被结算。这符合设计 05 §4.2（预留按申请资源与上限，而非平均时间）。

## 5. 场景 M3(b)：提交状态 unknown，不自动重提

### 5.1 第一轮（E-0007/s0，进程实际已发出）

用户指令：让 h0001 重试 E-0007/s0；worker reserve、claim、实际启动本地进程，但把"调度器返回"当作丢失，不 attach_job，标 unknown；之后不得重提，用 reconcile_submission 对账，按 key 找回原作业并 attach 原 job_id，正常结算。

判据：run 变 unknown，reservation held_unknown，用 reconcile_submission，不重提，同一 run attempt 不出现第二个 reservation/submission，最后对账并结算。结果：**通过**。接口返回（工作者子 agent 记录，时间戳 00:44）：

- `reserve_submission` → `RS-0017 created, accounting_status=reserved, submission_phase=intent, reserved_units=600`；`budget_status` committed 616 / available 49。
- `claim_submission` → `{"submission_key":"E-0007-s0","claim_generation":1}`。
- 进程启动，`update_run E-0007/s0 exec_status=unknown` → `ok`；`budget_status`：RS-0017 `held_unknown`，`submission_phase=claimed`，`job_id=null`，committed 616（预占保留）。
- `reconcile_submission` → `runs: {"E-0007/s0@1":"unknown"}`，`next: "SUBMISSION_AMBIGUOUS: the scheduler may have it; query it by the submission key and attach_job when found; release only once sure nothing was submitted (user instruction)"`。
- 按 key 找回本地作业 `local-E-0007-s0`（输出目录 outputs/E-0007-s0）→ `attach_job(E-0007-s0, local-E-0007-s0, claim_generation=1)` → `submission_phase=attached`（accounting 仍 held_unknown）→ `update_run succeeded` → `reconcile_submission next: "settle_reservation with the scheduler's accounting for the job"` → `import_run_result` 成功 → `settle_reservation(RS-0017, outputs/E-0007-s0/usage.json)` → `accounting_status=settled`，`actual_units=1`；`budget_status` committed 17 / available 648 / open_reservations []。
- 全程只有一个 reservation（RS-0017）和一个 submission_key；DB 中 `reservation` 表无 E-0007 的第二条记录。EV-0007：accuracy 89.75（n=1），相对 SOTA +0.25，outcome inconclusive。

### 5.2 第二轮（E-0008/s0，进程从未发出，测拒绝与释放）

用户指令：h0002 新建 E-0008（H-0002，nesterov lr 0.03，n_seeds=1）：reserve、claim 后不启动进程，标 unknown；然后依次尝试 (a)(b)(c)(d)，之后对账，我再给释放指令。接口返回原文：

- RS-0018 `reserved/intent` → claim `claim_generation 1` → `update_run exec_status=unknown` → RS-0018 `held_unknown`，`submission_phase=claimed`，job_id 空；committed 617 / available 48。
- (a) 同一 run attempt 换 key `E-0008-s0-retry` 再 `reserve_submission`：
  `CodedError: SUBMISSION_AMBIGUOUS: E-0008/s0@1 is unknown: it was submitted already; reconcile, do not reserve again`
- (b) 原 key 再 `claim_submission`（不带 reclaim）：
  `CodedError: SUBMISSION_AMBIGUOUS: E-0008-s0 is claimed (generation 1); query the scheduler by the key before any new submission, then reclaim=true if nothing was submitted`
- (c) `update_run exec_status=submitted`（从 unknown）：
  `ResearchDBError: exec_status unknown -> submitted is not allowed; from unknown: running, succeeded, failed, cancelled`
- (d) 不带用户指令 `release_reservation(E-0008-s0)`：
  `CodedError: SUBMISSION_AMBIGUOUS: E-0008-s0 is claimed: the scheduler may run it; releasing needs the user's instruction`
- `reconcile_submission` → 同 5.1 的 `SUBMISSION_AMBIGUOUS` next；本地没有 outputs/E-0008* 目录，`pgrep` 无训练进程；Leader 不自行释放，仍占 600，available 48，说明释放前任何新的 600 预留都会被拒。
- 站点 attention 出现 `run_unknown`（"E-0008/s0 执行状态 unknown"，标签 作业状态未知）与 `submission_unknown`（"E-0008-s0（claimed，held_unknown）：按提交身份向调度器核对，不要重新提交"，标签 提交状态待核对）。
- 用户指令释放：Leader 登记为用户指令文档 D-0039（`instructions/UI-0004.v1.md`，"User instruction: release RS-0018"），带 `user_instruction_doc_id` 调 `release_reservation`，RS-0018 变 `accounting_status=released`，note "User confirmed locally no process/output exists for E-0008-s0; the submission was never sent (user instruction D-0039)"；run E-0008/s0 → `cancelled`；`budget_status` committed 17 / available 648 / open_reservations []，total 仍 665。

## 6. 其他观察项

- notify（`research/…/logs/notify.jsonl`）：只有一条 `confirm_request`，`outcome: "skipped: no notify.url"`，符合预期。没有 `alert` 条目：累计用量 17 node-seconds，阈值 `alert_node_h=0.005`（18 秒），始终没越线；因此 `alert`、`admission_paused`、`overrun`、`run_stale` 没有出现（页面 HTML 中 "overrun" 只是字段名，非 attention 项），这些场景在本次未覆盖。
- `/research-tree inbox`：返回 "research-tree: 所有转交都已有RLD回执。"。底部窗口（statusLine/window）持续显示确认请求卡片，状态为"已确认"（卡片文字没有因后续进展更新，见 §7-8）。
- 用户指令登记：只有 slash 命令被登记为 user_instruction 文档（D-0001 plan、D-0016 confirm、D-0032 config apply）；我以自由文本发的指令（场景 B 的并行启动、E-0007 重试、E-0008 演练）没有自动登记，Leader 在 DEC-0005/DEC-0006 的 reason 里写 "User instruction in main session: …" 而没有 doc id；仅释放那次因接口要求才由 Leader 自建 D-0039。
- 站点：结束时 `build_site.py --check` 通过；attention 17 项，其中除下面的 curve_missing 外为 `run_unknown`/`submission_unknown`（释放前）。

## 7. 发现的问题与可疑行为

1. 本次 M3 的核心判据全部成立（见 §4、§5），没有发现预算准入、claim、unknown 状态机或释放规则的 bug。reserve 失败信息明确，`SUBMISSION_AMBIGUOUS` 的 next 提示可直接执行。
2. **接口依赖当前工作目录**：Leader 为读 metrics.json 把 shell 停在 `research/…/outputs/`，之后 `update_project` 的调用返回"outputs 下没有 .venv/bin/python：先运行 /research-tree prepare"，错误指向 prepare，实际是 cwd 问题，且该调用没有写入任何东西。Leader 正确识别并没有重试，但这条提示容易误导 agent（可能引导其重跑 prepare）。建议工具从 project 根解析路径或在报错里提示 cwd。
3. 筛选实验默认跑 3 个 seed（项目 seeds=[0,1,2]），而 yaml 的 `verification.screening_seeds` 是 `[0]`；搜索 seed 的集合与 yaml 的 screening/replication 划分不是一一对应（Leader 的 init 计划写成"搜索 seed 0,1,2，确认 seed 100–102"）。需要核对 yaml 的 screening_seeds 到底被谁使用；如果它决定首轮 seed 数，这里的行为就与配置不符。这轮没有再核对，仅记录。
4. 预留按 `per_run` 的 walltime 上限（600）而不是实际时长，所以总额 1500 只能同时容纳两个 run（第一轮筛选时 h0001 就遇到 `1209 of 1500` 的 BUDGET_EXCEEDED），三个 worker 并行会互相排队。符合 05 §4.2，但对"秒级"任务而言保守，worker 需要靠串行完成；是否应在 yaml 提供 per_run 以外的预估，是设计问题。
5. Leader 在场景 B 之前就让两个节点各跑完 3 个 seed 的筛选（E-0004、E-0005），再进入"等待用户决定"（增加 seed 或 NOT GO）。因此 M3(a) 的争用要靠我另外要求新实验（E-0006/E-0007）才出现；不是插件问题，只是测试流程多了一步。
6. 首次 `build_site.py --check` 报 stale（`page_version: null`）：整个流程（含 Leader 完成基线、冻结、评估）后站点仍未生成，需手工 `build_site.py` 才有 index.html。若站点应在流程中自动构建，这是缺口；若按设计由用户/技能触发则无问题。M1 记录里也是"重建后"通过。
7. 页面 attention 对每个 run 都报 `curve_missing`："曲线文件无法读取：outputs/E-0001-s0/curve.csv（Expecting value: line 1 column 1 (char 0)）"。toytrain 的 `curve.csv` 是 `step,loss` CSV，页面按 JSON 读取。是测试项目产物格式与页面期望不一致，还是页面应支持 CSV，需要确认（站点技能/01 §4 有无曲线格式约定）。
8. Leader 偶发 `No such tool available: mcp__research-tree__reconcile_submission_placeholder`（h0001 在 00:44:39 调用了一个不存在的 MCP 工具名），随后改用 `research_db` 的 `reconcile_submission` 正常完成；无副作用，属 agent 小失误。
9. 底部卡片/状态栏在流程推进后仍显示旧的"等待用户确认"提示（标题已是"已确认"，内文仍是立项请求）；以及输入框里出现类似"选 1，加 seed 3、4、5"的灰色建议输入（宿主的提示建议），不是实际发送的消息，也没有被发送。
10. `/effort medium` 把 effort 写入用户全局默认（"saved as your default for new sessions"）：协议 §4.2 要求该步，但会改全局设置，测试后需要提醒用户。
11. `agent start` 首次返回 `agent_not_ready`（等待信任目录对话框），读屏后发 `down`、`enter` 信任项目目录（只是目录信任，不是全局设置）。结束时我直接 `herdr pane close` 关闭了 pane，没有先发 `/exit`（`/exit` 的 prompt 需要 `--wait`，我用了无 `--wait` 的 `--timeout`，被 CLI 拒绝）。
12. 未覆盖：`alert`/`admission_paused`/`overrun`/`run_stale` attention 项、`resume_admission`、实际超额的如实记账（本地任务只有 1 秒，不会超额）、`reclaim=true` 的重领取分支、statusLine 中的待办回执细节。

## 实施者处理（主 agent）

| # | 问题 | 处理 |
|---|---|---|
| 1 | 会话 cwd 移到 outputs/ 后工具报“先运行 prepare” | 已修：Claude mod 从会话目录向上查找 `.venv/bin/python`，错误信息指出须在项目目录运行 |
| 2 | v2 `screening_seeds: [0]` 未限制筛选 seed 数（实际 3 个） | 已修：项目新增 `screen_seeds`（v2 = screening_seeds 个数），`_screen_seeds` 以它为上限；测试 `test_configured_screening_seeds_cap_the_screen` |
| 3 | 预留按 per_run walltime 上限计，偏保守 | 符合 05 §4.2（预留按申请资源与上限）；worker 可按实际申请的较小 walltime 登记实验，记录 |
| 4 | 未构建页面时 `--check` 返回 stale | 预期行为（页面尚不存在）；记录 |
| 5 | curve.csv 不是 JSON | M2 已修（夹具另写 curve.json） |
| 6 | 自由文本用户指令未登记为 user_instruction | Leader 行为，规则已要求 main 中的用户指令由 RLD 代为登记；记录，留待后续提示强化 |
| 7 | 调用不存在的 MCP 工具后自行恢复 | 模型行为，无副作用；记录 |
| 8 | 状态卡片文字滞后 | 记录（UI 显示，不影响数据） |
| 9–11 | /effort、herdr wait、关闭 pane 方式 | 测试执行细节，记录 |
| 12 | 复用 worker 无新 agent_models 记录 | 已知（M1 观察 7）；不影响判定，记录 |
| 13 | alert、admission_paused、overrun、run_stale、resume_admission、reclaim 未在真实宿主触发 | 由单元测试 B01–B14、X08、run_stale 覆盖；记录 |
