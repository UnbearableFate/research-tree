# M6 Codex 真实宿主补测（进行中）

日期：2026-10-07。scratch：`/tmp/research-tree-codex-20261007-1XA9OP`。只给方向和用户种子场景均须实际执行；未完成不得以单元测试代替。

## 首次仅方向会话

项目 `rt-test-M6-codex`，隔离 `codex-home-M6`，Herdr `rt-codex-m6` / 自建 `w3:pG`，原生线程 `01a11582-9189-74f1-9303-ae61638a688b`。主会话 gpt-6-luna medium / Full access；discovery full、两通用 lenses、triage_top_n=2、max_initial_nodes=3、reviewer anthropic/claude-sonnet-5-5。

prepare 保留方向计划与配置。init 后 phase=planning；D0 brief 完成；D1 实际核验 Adam（arXiv 1412.6980）与逻辑回归近邻工作（2208.06828），文献 D-0007、D-0008 verified，literature 阶段 accepted。D1 是确定性文献检查，未冒充跨族评审。

D2 实际检查发现 MCP/CLI 没有正式只读 lens 入口；插件提示要求由 RLD 生成并标注 generator=leader，与设计 02 的只读助手职责不符。主会话未替代生成，记录 D-0009 `project/reports/discovery-blocker.v1.md`，candidates=failed，resume 指向 candidates；其余阶段 pending。没有候选、训练、确认、review 收据或费用。

配置复制被保护 hook 拒绝，主会话未绕过；已读取的 effective 配置仍为 full。本次 config_doc_id 未生效，不记录为配置登记成功。此项目停止，保留原证据；不计 M6 通过。

## 修复与新项目

已增加 `research_control lens` 正式入口及其只读角色、阶段/模式/配置/同身份运行门，更新技能、规则与规划提示；实际结果保存在 run/answer.txt，由 RLD 核对并写候选分片。边界回归通过，最新 adapter 为 21 项。

全新 `rt-test-M6r2-codex`、隔离 `codex-home-M6r2`，Herdr `rt-codex-m6r2` / `w3:pG`，主会话与配置均 Full access；lens/UI 保持只读。只复制规划/文献内容模板到 planning-inputs，不复制状态或评审。已提交 prepare；正式助手实际模型、D0–D8、两栏报告、用户种子与 ABANDON 决定门尚待执行。

## M6r2 的真实助手与评审失败

prepare/init 实际完成，当前配置 D-0003 已 apply，D0 done、D1 accepted。主线程 `01a11598-c547-7282-be49-bfff2772b0a1`。

| lens | run | thread | actual 结果 |
|---|---|---|---|
| method-transfer | b4d58f268b894796b56f95b18154391b | 01a1159d-4357-79b1-9e53-360bd32798be | completed/exit 0，1 候选，observed gpt-6-luna |
| contradiction | 8ee2f49324974eb0b6b8de16468fc40f | 01a1159d-5645-7d53-a89f-cf39ad9e3d78 | completed/exit 0，3 候选，observed gpt-6-luna |

两个实际原生 session 的 developer 权限记录均为 read-only；node_id=null，没有科学 worker 绑定。实际 JSON 已核对并合并为四候选；完成通知均 queued，真实 RLD 读取后 acknowledge。证据 `M6r2-lens-results.json` 和原 run 记录。D2 done；D3 resume 从 feasibility 开始并 accepted，未重做 D0/D1。

初次控制输入把 feasibility 称为评审，已纠正为确定性 verifier；没有因此创建不存在的 review kind。D4 triage 真实 research_review 返回 `REVIEW_UNAVAILABLE: claude_code: no JSON result; stderr: Error: --json-schema is not a valid JSON Schema: no schema with key or ref "https://json-schema.org/draft/2020-12/schema"`。开始/失败两条收据持久化；0 USD、reviews 空、没有模型推断或 fake review。主会话报告后停止，D4–D8 未完成。

共享包装器仅在 Claude CLI 参数中移除不兼容的方言注解；原本地校验和 review schema 不变。回归先复现再通过。M6r2 停止，保留证据，不在旧安装缓存上继续。

## 当前 M6r3

全新 `rt-test-M6r3-codex`、隔离 `codex-home-M6r3`、Herdr `rt-codex-m6r3` / `w3:pG`，安装最新构建，主会话 Full access。规划输入只复用正文，未复制状态或 review 收据；初始评审阈值 5 USD，先验证有效 triage，再由测试用户将阈值调低验证 R14，避免把过小的单次 CLI 费用上限误当可用性证明。已提交 prepare；方向-only 全流程及用户种子场景仍待完成。

M6r3 两个正式 lens 均真实完成：contradiction run `11b85c029eb54794898a95e015eef096`（3 候选），method-transfer run `67b98ff12b114b9cbee2ae7570976974`（2 候选，thread `01a115b5-eec4-7e80-8302-a691452d0d80`），observed 均为 gpt-6-luna。模型已读取并确认通知；尚未把助手完成误当 D4 或 discovery gate 已接受。从 persistent candidates/feasibility 继续，真实 triage 正在执行。

M6r3 的真实 triage D-0014/RV-0001 为 claude_code，is_error=false、terminal_reason=completed、modelUsage仅claude-sonnet-5-5，raw total_cost_usd=0.1453564，登记费用为0.145356（舍入）。D3、D4 accepted；前一次错误只是 brief 漏 docs/ 前缀，发生在backend之前，保留日志后纠正路径成功。

实际R14：测试用户将阈值从5降到0.01，config.v2/UI-0005登记并apply；CAND-0002 novelty_precheck 于09:47:27返回 REVIEW_BUDGET，cost_usd=0，无started或新review，不降级。测试用户随后明确提高至20，config.v3 D-0017已apply。D5/D6真实review正在完成，尚未把它们记作整个M6通过。

M6r3 仅方向 D0–D8 已真实完成：gate PASS（09:56:45）、两栏报告 D-0026、初始H-0001/H-0002、正式立项计划和未分配根T-0001；确认前快照 `M6r3-discovery-complete.json` 为 awaiting_confirmation、0 experiment/run。五次有效ClaudeCode review 原始费用合计0.5484006 USD，登记舍入合计0.548401；triage/两novelty/两critical均严格completed且observed为Sonnet5.5。一次外部code Grep permission_denial在review及计划中明确保留（R22实际拒绝，没有把未读代码当已核验）。

测试控制器阅读计划后明确确认仅根harness sanity/六基线/冻结/验收，不授权假说/确认seed计算。新增test-inputs仅用户提供的wrapper/stats/config代码正文与固定角色MCP驱动，不复制研究状态或结果；根公共流程正在执行。用户seed、低排名及ABANDON待用户决定仍待新场景，不将仅方向成功写作M6全部通过。

### M6r3 根任务验收

正式 RLD observed `gpt-6-luna`，thread `01a115af-dcf0-7342-97bf-2cd9d4e1fa6c`；实际 worker/root observed `gpt-6-luna`，thread `01a115d2-7840-7113-9c1b-c734fd600cae`，各轮以同身份恢复。用户提供的驱动由真实 managed worker 调用安装包的 public MCP，并运行真实本机 CPU 训练；它不是数据库造数或模型替身。请求/响应在 `logs/host-harness-mcp.jsonl`，逐 run manifest/metrics/curve/log/usage 在 outputs。

初轮 Adam sanity/三个 seed 有效，Momentum s0 因 runner 传入 train.py 未支持的 beta 参数退出2；E-0003/s0@1、原始日志与实际1秒费用保留，无科学负向评价。worker 修复 CLI 后，RLD审核并冻结新 commit `51369c5a23b6930e73f5427c454ef29b2ea6135d`，新建 E-0004 sanity、E-0005 Adam、E-0006 Momentum，完成七个有效 run，不改旧 attempt。当前 Adam：89.5/90.5/91.25 pp，mean90.41666666666667、SD0.8779711460710615；Momentum：90/90.25/90.25 pp，mean90.16666666666667、SD0.14433756729740643，均为 API 从产物重算，synthetic_proxy 限制保留。

驱动复用旧设计文档造成 code_ref 文字过时，由实际 RLD 独立核验发现，写新版交付/补充说明，保留旧文档与运行；新 manifest/experiment/冻结 commit 一致。后续未开始的夹具驱动将 design/delivery 文件名绑定实际代码提交，活跃 M6 输入和证据未被改写。此为测试输入缺陷，不改产品校验。

T-0001 于10:22:28由 rld/main accepted；accepted_evidence D-0040/D-0036/D-0037/D-0038；当前 SOTA E-0005。所有12份reservation settled、实际总12 node-seconds（包括失败），无活跃worker。只读快照 `<scratch>/M6r3-root-accepted.json`；原生check实际返回 page_version231/db_version231/stale=false。本轮 direction-only + common root 路径通过；用户种子、低排名及点名 ABANDON 的用户决定门仍需新独立场景，不将整个M6写成完成。

## 用户种子独立场景

全新 `rt-test-M6-seed-codex`、`codex-home-M6-seed`，Herdr `rt-codex-m6seed` / 自建 `w3:pG`。实际 RLD thread `01a115e8-642c-7320-bb29-01ba13dce3f9`，observed gpt-6-luna。prepare 保留输入；discovery full、triage_top_n=1，用户种子 NovelAdam 明确为 Adam 复制更名，未提供虚构结果。提供的完整代码 HEAD `277dbd7c7de50eb877797584923ecfb2d33461ff`。

六个实际只读 lens（两通用、variant/combination/competing/repair 四个seed视角）全部 completed、observed gpt-6-luna，合并16个候选。CAND-0001 origin=user/selected=true，真实triage排名16/16，仍被选入 novelty/critical；没有因低排名抹掉用户假说。novelty D-0010/RV-0002 为 ABANDON、score1，点名 Kingma & Ba 的 Adam（arXiv1412.6980，已核验/读D-0006）；critical D-0012/RV-0004 proceed，但外部代码读取拒绝与局限保留。五次实际 Claude Code/Sonnet5.5评审登记舍入累计0.561088 USD，严格完成/单requested模型；原始费用另行从缓存核对。

两栏报告 D-0014 原样保留低排名及“建议放弃，待用户决定”，当时0 hypothesis/experiment/run，phase=planning；只读证据 `<scratch>/M6-seed-pending.json`。测试控制器阅读报告后，明确 D-0015 仅保留 CAND-0001 作为 Adam/NovelAdam 标签同一性的工程控制，不认可创新或授权运行。系统随后才建立 H-0001，不对其他未核验候选建节点；accepted discovery 阶段和付费review未重做。

原生规划有两类调用错误，完整保留：一度把MCP的封包对象而非D-ID传给doc_id，被TypeError拒绝；首次protocol.v1混淆per-run counts与三seed门，并把model字符串写短，测试控制器在确认前读取实际wrapper发现。RLD登记新 protocol.v2 D-0027，`match.model` 对齐 `local logistic regression in code/toytrain/train.py`，`required_counts={n_train:1200,n_val:400,epochs:30,steps:1140}`，min_pairs=3独立run要求不变；未改runner制造计数、未降门。新任务请求D-0028/launch-plan.v3 D-0029保留旧错误版本、六文件冻结，methods.py排除；确认前仍无worker/训练。

测试控制器审阅新版具体文件后明确确认，仅一次Adam sanity及Adam/Momentum各seeds0/1/2六基线，600node-seconds/每次1node10s，不授权NovelAdam或确认seed。真实root run `cbfa6814a9454693b14c327f2f804f98` 已启动；原生worker先误用上级venv路径，依据实际项目路径恢复执行。当前已有真实sanity/部分基线，交付/审计/预算/页面仍在核验，不将其计为共同根流程通过。

### 用户种子根流程与 R04 通过

root thread `01a11606-32e2-79a1-872a-e6e80e371aee` 实际 observed gpt-6-luna；主/root的原生 turn_context 均 danger-full-access/approval never，证据 `M6-seed-native-full-access-proof.json`。七run全部valid/artifact_imported、七reservation settled、实际7node-seconds。T-0001于11:07:28 accepted，依据D-0038/D-0034/D-0036/D-0027/两个EV/三个E；该任务历史交付指针仍D-0037，补充现行详细交付D-0038明确作为接受证据，未把被拒的指针更新当成功。快照`M6-seed-root-accepted.json`，首次验收check175/175/stale=false。Adam/Momentum值与本协议固定基线一致；没有NovelAdam或confirmation run。

每批同族R04实际反例：测试用户apply同族config.v2 D-0039/UI-0007，proposal_review被拒REVIEW_UNAVAILABLE、0费用，实际日志含11:10:15拒绝；RLD复核探针审计D-0041亦记录11:10:43拒绝，无新review。用户恢复原跨族config.v3 D-0042/UI-0008，RLD核验并ack，最终页面189/189/stale=false、inbox空、无liveworker，正常退出主会话。自建pane保留并复用于M3。

五次真实查新评审原始ClaudeCode费用为0.1535414、0.0952308、0.0704342、0.11641、0.1254722，合计0.5610886USD；数据库舍入合计0.561088。严格is_error=false/terminal_reason=completed/modelUsage仅claude-sonnet-5-5，证据`native-review-costs-1107.json`。M6方向、用户种子、低排名、ABANDON等待决定、中断不重做accepted阶段、共同根流程与同族场景已实际通过；批次终审和整体验收仍待完成。

## 逐批 R19 跳过说明（19:08 UTC补记）

M6 未单独执行14 §5要求的“Claude未登录”R19探针；这是该批次的协议执行缺口，不能写为已经执行。相同后端拒绝边界在 [M4](M4-codex.md)、[M5](M5-codex.md)、[M7](M7-codex.md)、[M8](M8-codex.md) 有实际原生拒绝证据。这些交叉证据覆盖插件功能，但不替代M6逐批重跑的事实；依14 §6明确披露本项跳过。

## R19 新原生项目补齐（19:25 UTC）

终审R10遭遇Claude额度限制后，在等待恢复期间补齐上述逐批缺口。全新`rt-test-M6R19-codex` / `codex-home-M6R19` / 自建`w3:pT`加载最新插件；线程`01a117cd-2b9f-7a60-81b4-f55cb088a98c`实际observed gpt-6-luna medium，原生turn_context为danger-full-access/never。配置仍discovery.full，另设空`CLAUDE_CONFIG_DIR`；实际auth status为loggedIn=false，进程白名单读取确认插件MCP使用该目录。

只登记planning metadata，未确认、启动lenses/worker或运行科学流程。init实际返回claude_code/Sonnet5.5 precheck不可用。min_setup D3、protocol D4从预先提供的文件逐字复制，metric_spec D2来自init，实际P-M6-R19记录使about有效；brief在根内docs/reviews/briefs，仅列路径。19:20:16实际public research_review(proposal_review)拒绝`REVIEW_UNAVAILABLE: claude is not logged in (claude auth status)`；失败日志session=null/cost_usd=0，未分配review、未调用付费评审、不改认证或路由。没有实际Pi已登录条件的证明，Pi-ready仍仅有确定性反事实覆盖。

只读独立核验26个canonical MCP事件、五份current文档SHA、原始metadata字节、源码/dist/cache四文件一致、observed模型与权限、0experiment/run/reservation/task/review/费用、无活跃代理。配置YAML预算600未apply到只含metadata的project，实际DB预算默认值照实保留，不用本探针证明科学准入或预算门。最终报告D5及页面11/11/stale=false均核验。两次register_document多带docs/被准确拒绝后改为正确路径；控制器最初误认为失败日志有backend字段，改为核对实际REVIEW_UNAVAILABLE/session=null格式，未修改产品。初次auth status误加--json的无结果不作为认证证据，使用正式auth status结果。

实际/exit后agent list确认消失，关闭自建pT；19:25:08去凭据归档并删除project/home，空Claude profile亦删除。project tar SHA256`c3c63f60c193cb74e96c6f7fc623051fd664c04c0db1b527551bf353189520e7`。独立controller-closeout/final-state/native-results/environment/page及36个可读项目文件保留于scratch/evidence-archive/M6R19-audit、M6R19-readable；cleanup-receipts第24项。上述19:08时的跳过事实保留，当前M6 R19已由新的实际原生探针补齐。最终有效Fable终审仍待额度恢复。
