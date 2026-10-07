# M5 Claude 宿主真实测试记录

日期：2026-10-07。批次内容见 03（从想法到实验设计：问题锚点、假说文档章节、claim map、实验块、sanity 先行、提交前跨模型代码审查、失败预算）与 12 §1。宿主：Claude Code v2.1.292，pane w3:pA（已关闭），agent `rt-m5`（后因宿主问题重启为 `rt-m5b`、`rt-m5c`，均 `--resume` 同一会话 53a393a7，保留 Leader 上下文），auto 权限模式，effort medium；
插件：先用 `scratchpad/dist-m5/claude/plugins/research-tree`（M5 构建），因 §7-1 的缺陷后改用 `scratchpad/dist-m5-patched/research-tree`（仅把 `hooks/register.tsx` 中 research_review 的 `3_900_000` 改成 `600_000`，与 M4 测试者的做法相同；源码仓库未改）。
项目：`$T = scratchpad/e2e/rt-test-M5-claude`，project_id `rt-test-m5-claude`（research-tree.yaml version 2；reviewer `openai/gpt-6-luna` via pi，timeout_s 900 后改 600；alert_node_h 0.005 后改 0.05）。
注意：yaml 文件本身没有写 `design.code_review` / `design.sanity_first`，项目记录里 `code_review_required`、`sanity_required`、`design_required` 都为 true（来自默认值，project 记录可见），故行为符合预期。

## 1. 命令

- `herdr pane split --current --direction right --cwd $T --no-focus` → w3:pA；`herdr agent start rt-m5 --kind claude --pane w3:pA -- --plugin-dir $P --add-dir $P --model claude-sonnet-5-5 --permission-mode auto`；信任对话框读后发 `down`、`enter`。
- `/research-tree prepare`、`/research-tree init`（Leader 问 metric_specs 只含 accuracy 而计划还要求 final_loss/train_time_s，我选“只比较 accuracy”）、规划、`/research-tree confirm`（见 §7-2，需要重启宿主才走通）、`/research-tree config apply`（改 timeout_s、alert_node_h 后各一次）。
- 场景由 `herdr agent prompt <name> "<用户指令>" --wait` 发送；`--wait` 在子 agent 仍在工作时就返回，之后轮询 `agent get` 直到不再 working。
- 核对：`$T/.venv/bin/python $P/tools/research_tree.py query {find,get,reviews,help}`；`build_site.py --db research/rt-test-m5-claude/research_tree.db`（`--check`、`--summary`）。工作者接口调用原文取自 `~/.claude/projects/<project>/53a393a7-…/subagents/*.jsonl`。
- `/exit` 因有一条 Leader 记下的“未发送反馈草稿”会弹出确认；我 `escape` 丢弃草稿（未发送），再 `enter` 选 “Exit and stop tasks”。

## 2. observed 模型（research/rt-test-m5-claude/logs/agent_models.jsonl）

ui（4 次）、worker/root、worker/h0003 均为 requested `claude-sonnet-5-5`（effort medium）、observed `claude-sonnet-5-5`；主会话 Sonnet 5.5。worker/h0001、h0002 是重启宿主之前用 `--resume` 复用的会话，没有新的 requested/observed 记录（与 M1/M3 观察一致）。

评审（reviewer）：`logs/review_calls.jsonl` 两条，都是 backend pi、model `openai/gpt-6-luna`、outcome ok：RV-0001（H-0001）cost 0.000409 USD，RV-0002（H-0002）cost 0.000458 USD。pi 合计 0.000867 USD；Claude Code 后端 0。未修补构建的五次调用（H-0001、H-0002 各至少一次）在启动 pi 之前就失败，没有产生费用。

## 3. 场景 A（所有批次）：prepare → init → 规划 → confirm → 根 worker 的 sanity 与基线 → 冻结

结果：**通过**（过程中暴露宿主缺陷，见 §7-2、§7-3）。

- 目标文档 `project/goal.v2.md` 有 `## 问题锚点`，五个字段齐全：底线问题、必须解决的瓶颈、非目标（与 plan.md 的“非目标”节一致）、约束、成功条件（v1→v2 仅改了成功条件里 final_loss/train_time_s 的措辞，Leader 在我选“只比较 accuracy”之后重写）。
- 假说文档 `hypotheses/H1-adam-warmup.v1.md`、`H2-nesterov.v1.md`：我用脚本比较“## 问题锚点”到下一个“## ”之间的文本与 goal.v2 完全相同（两份均 True）；章节依次为 问题锚点、方法步骤、技术缺口、可证伪预测与竞争解释、最接近工作与差异、Claim map、实验块、成本估计、停止条件、有意舍弃的复杂度，另有“创建理由与引用的相关研究”。十个必需章节全部具备。
- 根 worker（T-0001，D-0014，委托 root）：E-0001 sanity（M0，adam，`--sanity` 之外的 run 详见 §5）、基线 E-0002（adam）、E-0003（momentum）、E-0004（momentum_lr0.005），各 3 seed，均 `milestone` M1，`code_ref` 8cd49b7e…；RS-0001..RS-0010 全部 settled；T-0001 accepted（证据 EV-0001..3、D-0023）。冻结 harness_ref=8cd49b7e94eb770f7c8e561b7a30b1696ee6aedd，`sota_experiment_id=E-0002`（adam 均值 90.4167，SD 0.878）。
- 页面：先 `build_site.py` 再 `--check`：`{"page_version": 435, "db_version": 435, "stale": false}` rc=0（构建前 `page_version: null, stale: true` rc=1，同 M3）。最终 attention 3 项：`task_blocked`（H-0003/T-0004）、`extend_seeds`、`task`。

## 4. 场景 B：X01，缺 Claim map 的假说文档

结果：**通过**（Leader 在项目已 NOT GO 之后才做，因此多了前置步骤）。

1. 第一次让 Leader 用 D-0043（`hypotheses/H3-warmup-cosine.v1.md`，故意不含 Claim map）调用 `create_hypothesis`：被项目状态拦下（先于章节门）：
   `ResearchDBError: project rt-test-m5-claude is not_go: no new research work after GO, NOT GO or a stop; resuming needs a user instruction (decide project status active, based_on that instruction)`（项目在筛选后已被 Leader 判 NOT GO、两个节点 `disposition=paused`；这是 Leader 的判断，不是插件问题）。Leader 没有自行恢复。
2. 我下用户指令“恢复研究”：Leader 登记 D-0044（`instructions/UI-0005.v1.md`，原话），写决定文档 D-0045，`decide` 项目 active（DEC-0010）。
3. 带 `parent_id=H-0001` 的调用：`ResearchDBError: H-0001 is verifying: new nodes go below the root (no parent_id) or below a verified, expandable node`（父节点规则先于章节门）。去掉 parent_id 重试，原文：
   `CodedError: DESIGN_SECTION_MISSING: D-0043 (hypotheses/H3-warmup-cosine.v1.md) lacks the sections Claim map; a hypothesis document has the '## ' sections 问题锚点, 方法步骤, 技术缺口, 可证伪预测与竞争解释, 最接近工作与差异, Claim map, 实验块, 成本估计, 停止条件, 有意舍弃的复杂度 (03 §10)`。
4. 无节点残留：此时只有 H-0001、H-0002；Leader 写合规版 `H3-warmup-cosine.v2.md`（D-0046，问题锚点与 goal.v2 逐字一致，1 条主 claim）后创建 H-0003（根节点之下，与 H-0001 用 rel_related `variant_of`）。
- 偏差（模型/接口交互，非缺陷）：我要求“与 H-0001 是 repairs 关系”，接口只允许 `rel_related` 为 competes / shares_control / variant_of，且子节点只能挂在 verified、可拓展的节点下，Leader 如实说明并用 variant_of，没有为通过调用而改 H-0001 状态。

## 5. 场景 C：sanity 先行与提交前代码审查

结果：**通过**（有两个缺陷：§7-1 阻断审查，§7-3 小规模 sanity 无法导入，需要绕行为协议规模的 sanity）。

- H-0001（worker h0001，分支 BR-0001 h0001-adam-warmup，提交 4180c5133f23648b84d22f7370db0696dc48700e）与 H-0002（h0002，BR-0002 h0002-nesterov，f6e933b5aca9b6135dddaa1d39cd019455ee49b8）：
  1. 各先建 `kind=sanity` 实验 E-0005 / E-0006（`--sanity` 小规模：n_train 200、n_val 100、epochs 2）；`import_run_result` 拒绝：
     `PAIRING_MISMATCH: manifest.json does not describe E-0005/s0@1: counts.n_val is 100, the protocol requires 400; counts.n_train is 200, the protocol requires 1200; counts.epochs is 2, the protocol requires 30`（E-0006 同）。run 停在 succeeded、valid 未设；Leader 登记了 OB-0001/OB-0002；工作者没有自行把 run 标 valid（没有绕过）。
  2. Leader 写 brief（`docs/reviews/briefs/H-000{1,2}-code-review.v1.md`）调用 `research_review(kind=code_review, code_ref=…)`：原版构建下两次都因 §7-1 失败；换修补版后：RV-0001（D-0030，`reviews/RV-0001.v1.md`）和 RV-0002（D-0031）均 backend `pi`、`reviewer_model: openai/gpt-6-luna`、`result: clear`、`basis_code_ref` 分别等于上面两个提交、`issues: []`、`method_implemented: true`（评审原文说明它读不到协议/指标规范文件，只核对了代码目录）。
  3. 审查 clear 之前 worker 就建了 B1（E-0007 H-0002 nesterov、E-0008 H-0001 adam_warmup，kind=method，seeds [0]，milestone M2）并 `reserve_submission`：被拒，原文：`CodedError: SANITY_REQUIRED: E-0008: run a sanity experiment (kind sanity) of code 4180c5133f first and accept its run (valid=true: counts, loss, metric file, reload) — the exit code is not enough`；E-0007 同（code f6e933b5ac）。工作者停下并如实报告，没有绕过。
  4. 修复：Leader 让工作者用协议规模重跑 sanity：E-0009（h0002，nesterov，f6e933b5）、E-0010（h0001，adam_warmup，4180c513），各 1200/400/30 epochs，`import_run_result` 成功，`update_run valid=true`；RS-0013（04:16:50）、RS-0014（04:16:55）；之后 E-0007 的预留 RS-0015（04:17:18）、E-0008 的 RS-0016（04:17:23）才被接受。顺序为：代码审查 clear（04:15）→ 有效 sanity（04:16:4x）→ 方法实验提交（04:17）。
  5. `CODE_REVIEW_REQUIRED` 没有出现（审查先于第一次提交成功）。没有任何 `waive_code_review` 调用：全程只出现 `research_db help waive_code_review` 的查看（Leader 读规则）；Leader 在 reviewer 不可用时明确说“规则允许写决定文档放行，但我不这样做，因为改一个配置值就能恢复审查”，向用户提出二选一（修插件或关闭 code_review_required），没有自行放行。
- 与 X05 的关系：sanity 的合规性靠“协议规模”才能通过导入，见 §7-3。
- 一次宿主权限拒绝：H-0001 的 E-0008/s0 训练命令被 auto 模式分类器拒绝（`[Modify Shared Resources]`），而同类命令此前（E-0005、E-0010）通过；worker 如实停下。我没有改任何权限设置，让 Leader 原样重试，随后成功（E-0008 seed 0..2 完成）。属宿主分类器的不稳定，不是插件问题。
- H-0001/H-0002 之后各自补到 3 seed（E-0007/E-0008，E-0011），Leader 以 inconclusive 把两个节点 `disposition=paused`，项目 `status=not_go`（SOTA SD 0.88 高于 0.5 个百分点的门槛）。

## 6. 场景 D：X06 / X07 失败预算

结果：**通过**。节点 H-0003，worker h0003，任务 T-0004（D-0047），分支 BR-0003 h0003-warmup-cos。worker 用一个返回 NaN 的 `_div` 辅助函数实现“学习率衰减除以 0”（Python 的 `/0` 抛 ZeroDivisionError，不产生 NaN），六次 sanity 运行 train.py 都输出 `ERROR non-finite parameters` 并退出码 1（E-0012..E-0017，提交 c3f2a8b、500e0ad、e43a42a、a21ed32、5b82676、388c0e4）。同一个 root_cause `sanity loss NaN: lr decay divides by zero`（接口存成小写，匹配大小写不敏感）。

| # | remedy | 返回 |
|---|---|---|
| 1 | patch | `{"ok": true, "result": {"blocked": false, "patches": 1, "rewrites": 0}}` |
| 2 | patch | `{"blocked": false, "patches": 2, "rewrites": 0}` |
| 3 | patch | `CodedError: FAILURE_BUDGET: 'sanity loss nan: lr decay divides by zero' was patched 2 time(s): rewrite from the hypothesis document, or report to the Leader`（code FAILURE_BUDGET，**拒绝**） |
| 4 | rewrite | `{"blocked": false, "patches": 2, "rewrites": 1}` |
| 5 | rewrite | `{"blocked": false, "patches": 2, "rewrites": 2}` |
| 6 | rewrite | `{"blocked": true, "reason": "'sanity loss NaN: lr decay divides by zero' failed the same way after 2 rewrites: the plan or the environment", "patches": 2, "rewrites": 2}` |

- 阻塞后 worker 只试一次新建 sanity 实验，被拒：`CodedError: FAILURE_BUDGET: T-0004 is blocked ('sanity loss NaN: lr decay divides by zero' failed the same way after 2 rewrites: the plan or the environment): the Leader decides (unblock_task) before anything else runs here`；没有重试，Leader 向我报告并问我是否 unblock。
- 页面 attention：`{'kind': 'task_blocked', 'id': 'H-0003', 'text': "T-0004 已阻塞：… 不再自动重试，由 RLD 决定（unblock_task）", 'label': '任务阻塞（失败预算）'}`；`build_site.py --check` stale=false。任务记录里 `status` 仍是 `in_progress`，阻塞体现在 `failure_log` 最后一条 `remedy: "blocked"` 与 `blocked_reason`（见 §7-5）。
- `unblock_task(T-0004, doc_id=D-0043)`（D-0043 是普通假说文档）被拒：`ResearchDBError: unblocking needs a current decision document`；任务仍 blocked。我没有让 Leader 写决定文档解除。

## 7. 发现的问题与可疑行为

1. **MAJOR（M4 已发现，M5 构建仍未修）：`research_review` 在 Claude 宿主完全不可用。** 复现：Leader 调 `research_review(kind=code_review, brief=docs/reviews/briefs/H-0001-code-review.v1.md, about=H-0001, code_ref=4180c513…, add_dirs=[…])`，返回 `research-tree 内部错误：research-tree: process.run: init.timeoutMs is a whole number of ms, 1 to 600000 (host check)`。原因：`claude-mod/research-tree/hooks/register.tsx` 的 `runTool($, cfg, 'review_call.py', args, 3_900_000)` 超过宿主 `process.run` 上限 600000 ms（`MAX_PROCESS_MS = 600_000`），与 reviewer 的 `timeout_s` 无关。Leader 一度误判为 `timeout_s: 900` 超限，我据此把 timeout_s 改 600 并 config apply，仍失败；换修补版后才通过。M5 把代码审查变成每个节点的必经门，因此未修补时节点无法提交（只能 waive 或关掉 `code_review_required`）。另：宿主上限 600 s 小于 review_call.py 的 MAX_CALL_S（3600），长评审需要后台运行/轮询。
2. **MAJOR：`/research-tree confirm` 一直提示“RLD 还没有提交立项计划，暂时无需确认”。** 现象：Leader 用 `post_to_ui(type=confirm_request, docs=[project/reports/init-plan.v2.md])` 发了确认请求（messages/main.jsonl main-0001，窗口里 w-0002 显示“【需要你决定】…”），但 `.research-tree.json` 的 `phase` 仍是 `planning`，confirm 的判断 `project.phase !== 'awaiting_confirmation'`（register.tsx 约第 909 行）因此拒绝。`post_to_ui` 钩子（约第 1247 行）本应在 `confirm_request` 且 phase 为 planning 时执行 `phase --set awaiting_confirmation`，没有生效，原因未查清（Leader 在 Python 工具、`$.state` 的 project 缓存与实际 marker 之间可能不一致）。再发一次 confirm_request（main-0002）仍无效；UI 子代理（LLM）还在窗口里回复“已登记你对立项计划的确认（D-0016）”，**但没有任何确认被登记**（`docs/instructions` 里只有 UI-0001，phase 不变），是错误的成功声明。我手工执行 `research_tree.py phase --set awaiting_confirmation` 后，宿主进程内缓存的 project 仍是 planning，confirm 依然拒绝；`/exit` 并 `--resume` 重启宿主（重新读取 marker）后 `/research-tree confirm` 立即成功（D-0018，confirmed_at 03:58:17）。结论：phase 迁移与 mod 缓存在真实宿主里会失步；UI 子代理会在没有登记的情况下声称已登记。
3. **MAJOR：sanity 实验无法按设计的“最小规模”导入。** 03 §8 与 M0 要求 sanity 是最小规模、不计 seed；但 `import_run_result` 要求 manifest 的 counts 与协议一致，`--sanity` 的 run（200/100/2）被 `PAIRING_MISMATCH` 拒绝（上文原文），run 无法 `valid=true`，于是 `SANITY_REQUIRED` 门永远过不了。根 worker 的 E-0001、E-0005、E-0006 都停在 succeeded/valid 未设；Leader 的绕行是用协议规模重跑 sanity（E-0009、E-0010），失去了“最小规模”的意义，Leader 另登记 OB-0001/OB-0002 后关闭。与 X05（sanity 标 valid 不计 seed）的实现路径冲突，需要设计取舍：sanity 的 counts 应由 sanity 的 manifest 另行校验。
4. **MEDIUM：斜杠命令依赖 Leader shell 的当前目录（M3 §7-2 修复不完整）。** 修复后工具会向上查找 `.venv`，但 `loadProject` 只在会话 cwd 查 `.research-tree.json`。Leader 为读 worktree 把 shell 停在 `wt-h0001` / 子目录后，`/research-tree config apply`、`build`、`check` 返回“当前目录没有研究项目：先运行 /research-tree prepare，填写 plan.md 后运行 /research-tree init”（至少出现 4 次），报错指向 prepare，有误导。Leader 重新 cd 回项目根后恢复。`research_review` 的同类检查（`当前目录没有研究项目：先运行 /research-tree init`）也有此依赖。
5. **MINOR：被阻塞任务的 `status` 仍是 `in_progress`。** 阻塞只体现在 `failure_log` 与 `blocked_reason`；表格里的任务状态不变，需要读 failure_log 才知道。页面的 `task_blocked` attention 项是正确的。
6. **MINOR：失败 run 的预留不结算。** 失败的 sanity 运行没有写 usage.json，RS-0024..RS-0029（60 秒/条，共 360 节点·秒）一直 `reserved`，`budget_status` committed 达 383 节点·秒，超过提醒线 180（0.05 node·h），但接口没有暂停准入（未出现 admission_paused）；Leader 说按规则不能单方面释放（已 claim、挂作业）。失败路径如何结算/释放需要说明。worker 把 sanity 实验的预留写成 60 秒而不是 2 秒（实验 `walltime_s` 与预留不一致，未被拒绝）。
7. 阶段“项目已 NOT GO”后创建节点会先报状态错误，再报父节点规则，章节门排在第三位：X01 的触发要在状态与父节点规则之后。顺序合理，但会让第一次尝试看不到 DESIGN_SECTION_MISSING；记录。
8. Leader 在场景 B 之前就把项目判 NOT GO（两个节点 3 seed 都是 inconclusive、SOTA SD 高于门槛），导致场景 B/D 需要先“恢复研究”。是 Leader 的判断，不是缺陷。恢复流程（用户指令 D-0044 → 决定文档 D-0045 → decide active DEC-0010）工作正常。
9. 宿主 `/exit` 因 Leader 在主会话里“记了一条反馈草稿”而多一层确认（“You have 1 unsent feedback draft”），我丢弃了草稿，没有发送。
10. `agent start --resume` 需要名字不同（rt-m5b/rt-m5c），因为旧 agent 名在 pane 退出后才释放；不是插件问题。
11. 未覆盖：X02（锚点不一致）、X03（claim 数超限）、X04（缺 design_doc）、X08（overrun）、X09–X11 由单元测试覆盖；`CODE_REVIEW_REQUIRED` 的真实触发（审查先于提交成功）与 `waive_code_review` 的拒绝没有在真实宿主触发；reviewer 不可用路径只经历了“工具故障”而没有 `REVIEW_UNAVAILABLE`。

## 实施者处理（主 agent）

| # | 问题 | 处理 |
|---|---|---|
| 1 | research_review 超时参数超过宿主上限 | M4 已修（runTool 限制在 600 s 内，review_call 用 --deadline-s 570），已合并进本批 |
| 2 | confirm 读到过期的阶段；post_to_ui 未改阶段时静默 | 已修：confirm 每次重新读取 marker；post_to_ui 改阶段失败时返回错误而不是静默；工具在项目目录运行（M4 修复）消除了阶段未改的根因（shell 在子目录时 research_tree.py 找不到 marker） |
| 3 | 最小规模 sanity 运行无法导入 | 已修：sanity 实验不比较，不要求协议的 required_counts 与 match；其他实验仍要求。测试 `SanityScaleTest` |
| 4 | 斜杠命令依赖 shell 当前目录 | 已修：loadProject 从会话目录向上查找 .research-tree.json |
| 5 | 阻塞任务的 status 仍是 in_progress | 记录：阻塞是失败预算的独立标记（blocked_reason，页面待处理项可见），不改任务状态机 |
| 6 | 失败运行的预留一直 reserved | 提示补充：失败的作业也写用量文件并结算；接口保持“已认领的预留只有结算或用户指令才能释放” |
| 7 | 检查顺序、NOT GO 后恢复、反馈草稿、未覆盖项 | 记录；未覆盖的 X02–X04、X08–X11、CODE_REVIEW_REQUIRED、放行被拒由单元测试覆盖 |
