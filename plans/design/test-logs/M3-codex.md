# M3 Codex 真实宿主补测（场景已验证，终审待完成）

日期2026-10-07，scratch `/tmp/research-tree-codex-20261007-1XA9OP`，新 `rt-test-M3-codex`/隔离 `codex-home-M3`，Herdr `rt-codex-m3` / 自建w3:pG。实际主线程 `01a11613-3b84-74d3-8c36-ba9ac1c896a5`、observed gpt-6-luna/FullAccess。主控只提供planning/code/脚本文本，不复制研究状态或评审。

prepare保留输入，原生init认证预检11:16:24Z/claude_code/Sonnet5.5/ok=true，正式计划区分认证与模型调用。两篇实际核验文献2406.09405/2208.06677。正式立项计划经过测试控制器阅读后明确确认仅根七run/600nodeSec/每次1node10s；两个假说及M3附加场景当时仍未授权执行。

代码冻结 `cfd319a44101cea60230aeefed84f17a57694ce6`，六路径不含methods.py，实际root thread `01a1161f-3645-79c1-9d71-da854ef7a906`。驱动经public MCP真实CPU完成七个valid run/两artifact_imported Evaluation、七reservation全settled、实际7nodeSec。第一版交付被新版替代后，RLD拒绝旧交付状态，由同worker身份的新线程 `01a11623-1128-77a3-ad37-7a9656cada65` 仅重交现行D-0021，不重新运行训练。T-0001于11:34:03accepted，依据D-0021/E-0001/EV-0001/EV-0002/D-0017/D-0019，记录 `M3-root-accepted.json`。当前最终page核对继续，不将旧page当现行。

M3预算/恢复工程脚本 `test-inputs/m3_budget_probe.py` 仅语法检查、未从控制器伪装worker运行。设计固定真实worker角色/任务/项目，public MCP保留原文，两个worker同ready barrier争最后10nodeSec，仅赢家实际运行一次固定Adam sanity。故障明确为SIMULATED lost scheduler response；CPU作业、manifest/metrics/usage均真实。unknown保留预留、拒绝重复claim/attempt，等待新用户指令后同身份按原key/job/attempt1恢复并导入/重复settle验证不重复费用；不生成科学负向判定。

根验收后测试控制器根据真实已花7把total_limit从600降低到17，native human config apply登记config.v2 D-0022、UI-0004 D-0023，剩余10。原600预算备份保留。已要求RLD仅写具体附加计划和未分配任务，等待审阅后再授权worker；尚未执行争额度、unknown或重复结算，不将脚本存在当通过。

## 附加计划审阅与准备门（11:48 UTC）

根流程最终页面原生build/check实际153/153、stale=false。RLD登记 m3-budget-plan.v1、两个open未分配任务 T-0002/T-0003 后停止。控制器读方案与脚本，依据生产 EXEC_TRANSITIONS/update_run/_check_submission 和 test_submit_timeout_before_submitted_is_unknown 核验：claimed reservation 的 planned→unknown 是专为提交响应丢失保留的合法接口，不要求先attach；没有放松门。显式授权prepare+contend，recover仍须单独当前指令。原计划风险判断由版本化更正文档保留。

两个真实worker observed gpt-6-luna：h0001线程01a1162e-b457-7f43-b203-af6f2ccd419c、h0002线程01a1162e-b5e1-7263-9024-be2f387347e2。准备失败均正确停止：h0001先误在uv外层git核验无HEAD，纠正-C code后DB拒绝H1未有branch，留下D-0029但无experiment/run；h0002把shell --project误传项目ID，绑定校验在MCP前拒绝。无reservation/CPU/账务变化，真实快照 M3-preparation-refusal.json；不是科学负向或科研attempt失败。

控制器提供仅prepare恢复的独立v2 helper（原v1不改）：允许复用h1当前D-0029、严格检查节点尚无experiment；contend/recover未改。v2 SHA256 f817f2db6502a49fa4c3b5229f49dacccdfe5216bb037a5ac8d8dce1889f4ee1，语法检查通过。明确授权RLD建立并登记真实空方法branches/worktrees（原frozen commit、文件不改），现有身份一次续接prepare，shell必须绝对project路径；无账务重置、自动重复CPU或放宽生产门。争额度/unknown/恢复尚未验证。

## 真实预算竞争、unknown 与原作业恢复

两分支 BR-0001/BR-0002 基于原冻结commit、文件未改。实际worker经v2 prepare创建 E-0004/s0、E-0005/s0，各attempt1，并在共享barrier争最后10nodeSec：h0001获得唯一 RS-0008，重复相同key reserve返回同RS/created=false；h0002收到BUDGET_EXCEEDED（17/17committed）、无reservation/job/CPU。两边budget_before均7/17，不把顺序调用冒充无竞争；ready时间及全部public MCP请求保留。

h0001真实CPU Adam sanity只启动一次，实际job local-E-0004-m3-s0-a1、exit0、usage1node1second；响应丢失故障明确为SIMULATED。DB planned→unknown、RS8 held_unknown/claimgen1/job_id尚未知，保留10预算；再次claim被SUBMISSION_AMBIGUOUS拒绝，attempt2也被unknown状态门拒绝。M3-held-unknown.json 与 M3-race-proof.json 同时保存原manifest hash/真实scheduler/usage与实际nativeFullAccess/model context。双方轮次均结束后，控制器读具体证据才明确单独当前恢复指令 D-0039。

同h0001线程实际recover经公共MCP reconcile→attach原job/gen1→succeeded→import原manifest→valid→两次settle：原attempt1/key/job不变，manifest SHA25659986741b42817e50c3c8f5532065df0f00b5910e815cbb2d1076aed31c58206、metrics e4576b634254c90686499b138ce56263157b056d1aa654029ac287c4bab56a78；原CPU未重跑，实际用量1秒。两次settlement结果同actual_units1，前后budget完全相同，最后committed8/limit17/available9/open_reservations=[]。M3-recovery-progress.json/原MCP日志包含完整真实收据。

任务生命周期额外拒绝保留：RLD此前已接受hold检查点T2，恢复启动先因无actionable任务被拒；新正式运维T4让同worker可续接。v2 helper实际恢复/计费成功后尝试把accepted T2改delivered，被终态门拒绝；不能重开历史任务或重复执行恢复。RLD按已授权运维取消路径取消T4，真实恢复结果与交付文件保留、独立账务核验，不把取消任务写成accepted；纯工程sanity未形成H1/H2科学结论。临时v3助手只语法检查、未使用，不能计作任何通过证据。R04同族反例/配置恢复与最终页面继续。

## R04、恢复配置与最终页面（12:20 UTC）

用户配置入口将 reviewer 暂改为 openai/gpt-6-luna/config.v3，require_cross_family 仍开启。实际 native proposal_review 于12:02:52返回 REVIEW_UNAVAILABLE（同族拒绝），session=null、cost=0，未启动评审后端。随后从已保留的跨族配置备份恢复 anthropic/claude-sonnet-5-5，登记 config.v4 D-0048/UI-0010 D-0049，预算仍17；原生 RLD 读取并 acknowledge。原始失败与恢复收据 M3-r04-and-config-restore.json；Claude Code与pi本批评审费用均0。

最终原生报告 D-0053（tasks/m3-final-state-check.v2.md）登记后重新 build/check，实际 page_version=255、db_version=255、stale=false。账务8/17、可用9、open_reservations=[]；worker/root、h0001、h0002均completed/live=false，inbox=[]，verify_document(D-0053)=true。M3-final-native-page-check.json 与 M3-state-1221.json 保存原始状态。主会话正常 /exit，自建pane保留并复用于M5；用户pane未关闭。M3规定的Codex场景已验证，整个补测目标及独立终审仍未完成。
