# M1 Codex 宿主测试记录（历史中止与本轮补测）

日期：2026-10-06。用户决定：阶段末测试只覆盖 Claude 宿主，Codex 宿主测试中止。本文只记录中止前的观察，**M1 场景（STAT_MISMATCH）在 Codex 端未执行，状态为 blocked/dropped**，不得写成通过。

## 1. rt-test-M1-codex（第一次尝试）

宿主 codex-cli，agent `rt-codex`，gpt-6-luna medium，隔离 `CODEX_HOME=$T/codex-home`。prepare → init → 规划 → 确认均完成；根 worker 由适配器以后台 `codex exec` 启动后，
第一次调用 research_db 即被拒：`MCP tool call requires approval, but approval policy is never`。worker 没有绕过，Leader 记录为阻塞（报告 D-0016）；框架未改，sanity/基线/冻结/SOTA 均未完成。
修复（主 agent）：适配器给后台 worker 传 `mcp_servers.research_tree.default_tools_approval_mode="approve"`，并重建 dist/codex。同时 Codex 周额度只剩 2%。

## 2. rt-test-M1b-codex（修复后，部分运行）

- `CODEX_HOME=$T/codex-home codex plugin add research-tree@research-tree --json` 成功，缓存与 dist/codex 逐文件一致（diff 无差异）。
- 过程中的测试环境问题（不是插件缺陷）：`herdr agent start` 不继承调用方的 `CODEX_HOME`，第一次 pane 启动用的是默认 `~/.codex`（该会话已退出，只跑过一次没有匹配技能的 prepare）；之后先在 pane shell 里 `export CODEX_HOME` 再启动。
  新项目未被信任时工作区只读，`prepare` 无法写 `.git`/`uv init`；在 `codex-home/config.toml` 增加该项目 `trust_level="trusted"` 后重启通过。
- 审批：prepare 的 uv/网络、research_tree 的 MCP 工具（research_control、research_db、post_to_ui）均以 "Allow for this session" 通过；文献下载（arxiv/mlr，保存到 `research/<id>/cache/literature/`）与 Leader 提交 harness 的 git commit 各批准一次。
- `$research-tree prepare`、`init`、确认（用户原话）均执行；确认后根 worker 能调用 research_db（旧 bug 不再出现）。
- 中止时数据库（只读核对）：project `rt-test-m1b-codex` active；6 个 run，EV-0001、EV-0002，seed 17/23/42；`agent_models.jsonl` 中 worker/root 的 requested 为 gpt-6-luna medium（4 条，无 observed 条目）。
- 可疑点：Leader 本人（而不是 worker）提交 harness（git add/commit 请求审批，理由 "May I commit the reviewed harness"），可能是 worker 沙箱不能提交；未进一步核实。
- 未执行：sanity/基线/冻结/SOTA 的数据库核对、M1 错数字场景、build_site --check。无 reviewer 费用。

## 2026-10-07 新隔离项目补测

本节属于用户重新授权的 Codex 全功能补测；上文 2026-10-06 的中止记录不改写。新 scratch `/tmp/research-tree-codex-20261007-1XA9OP`，项目 `rt-test-M1-codex`，隔离 `codex-home-M1r2`，Herdr `rt-codex-m1r2` / 自建 `w3:pH`。实际主线程 `01a115ca-1a2d-7c61-ab9a-1f1f3e9145af`、root worker `01a115f5-acf3-7142-84a0-49d27a1de8dd`，observed 均 gpt-6-luna。

prepare 保留输入，原生 init 重新登记本项目文档并核验 warmup、Momentum 文献。三轮 proposal_review 为 REVISE，第四轮实际 Claude Code / Sonnet5.5 review RV-0004 为 READY；正式计划 D-0028 请求确认。临时测试控制器阅读具体计划后明确确认根七次运行，并授权仅 H-0001 的 warmup114 方法至有充分依据的 GO/NOT GO；H-0002 暂停待范围决定，不是科学负向。

协议要求 top-level steps=1140，提供的 wrapper 初版缺少该实际字段。根 worker 在冻结前从真实 raw_metrics.steps 写出该字段与 crosscheck，经 RLD 审核冻结 `8f8b693da2afc68c1fc79bfb0993f7b63ba5944c`，没有注入估计计数或放松协议。根任务 T-0003 于10:54:17 accepted，交付 D-0040、接受依据 D-0032/D-0033/D-0037/D-0039/D-0042；此前两个被替代任务 cancelled，历史保留。

真实 managed root 经提供的工程驱动和安装包 public MCP 执行七个本机 CPU run：一次 sanity、Adam 与 Momentum 各 seeds0/1/2。只读快照 `<scratch>/M1-root-accepted.json` 显示7个reservation全settled、实际7 node-seconds，EV-0001/EV-0002为artifact_imported；Adam mean90.41666666666667/SD0.8779711460710615 pp，Momentum mean90.16666666666667/SD0.14433756729740643 pp。不外推代理任务结论。

M1 实际反例与幂等重导通过：worker 在首个 Adam run 导入后、正式 Evaluation 前登记明确标为故意无效的草稿 D-0036，accuracy声明0.995，而真实metrics为0.895。set_document_current 返回 CodedError STAT_MISMATCH；拒绝前后 evaluations 均空，草稿未变现行。同一真实 manifest 重导返回同一 import_record/metric，无新增科学样本。详细收据 `root/logs/m1-native-probes.json`，manifest sha256 `5bd9981…`、metrics sha256 `23458d1…`、原imported_at10:48:03保留；原始科学产物未改。

根流程/M1反例已通过，页面最终核对、每批同族反例与方法端到端验收继续执行，不将整批记完成。当前方法 worker 已在独立 worktree 新增 warmup 类并提交 `1d22b1897cc6cb98489682d813019c926bb2bef9`，真实跨族 code_review RV-0005 已返回；具体评审判据、sanity/controls/screen/replication和结项仍须核验。

方法sanity首次工程失败：同一worker线程`01a11602-f76f-7690-929f-f811a9783887`直接调用toytrain.train而非提供的runner，实际exit0/accuracy0.86/200-100-2-14，却没有manifest，不能导入/有效。update_run重复传未变化attempt1被拒；worker停止并报alert，report类写入也按角色拒绝。RLD核对原始停止记录后将原run记succeeded/valid=false，真实usage1秒结算RS-0008；累计8node-seconds、无heldreservation，无科学判断。原始错误及文件保留在D-0048。11:11测试控制器阅读具体停止报告并明确D-0049仅授权同E-0004/s0 attempt2、新key/新目录、同reviewed代码、正确runner，经同线程恢复；禁止覆盖a1/新等价experiment/自动attempt3。执行继续，尚不记sanity通过。

截至RV-0005，真实ClaudeCode review原始费用0.8177806USD（四proposal共0.7294894，加code_review0.0882912），均严格completed/单Sonnet5.5；证据`native-review-costs-1107.json`。当前check实际page_version=null/db_version227/stale=true，页面验收未完成，不能沿用其他项目的页面成功。

11:28:12 的同身份恢复已实际通过：在 attempt2 尚 planned/RS-0009 已 attached 的前置快照后，控制器明确授权继续这一已准备 attempt，而不是再建 attempt3。实际 worker 执行提供的 run_sanity_attempt2.py，通过公共 MCP submitted→真实runner一次→artifact import→valid→settle；E-0004/s0 attempt2 succeeded/valid=true、原 a1 invalid/spent1 保留。原始 manifest sha256 4481ce…、metrics a4055e…、原方法 code_ref 1d22…；真实新用量1秒，累计9node-seconds。证据 logs/m1-sanity-attempt2-result.json / m1-sanity-attempt2-mcp.jsonl 和 M1-attempt2-prelaunch.json。控制器仅语法检查，未伪装 worker 执行。

11:42只读 M1-live-1140.json 显示同实际方法提交 Adam 控制 E-0005 的 seed0 已 valid、seed1 正在导入；唯一 H-0001 worker 仍真实运行。不将控制/后续筛选未结束写成方法或整批完成。

## H1真实方法、追加重复与NOT GO（12:19 UTC）

实际同commit Adam controls E-0005 seeds0/1/2均valid；warmup E-0006首seed的EV-0003为inconclusive，配对差+0.25pp，随后RLD明确extend_seeds并续接同worker完成原E-0006的seed1/2。EV-0004是第2版artifact_imported Evaluation，对原冻结SOTA E-0002配对差[+0.25,0,0]pp、均值+0.08333333333333333pp、SD0.14433756729740643pp；未过严格>0.5pp，outcome=inconclusive，旧EV-0003保留。没有把追加seed另建等价方法实验，也没有强制科学负向或进入候选/确认。

RLD独立审计D-0061、交付D-0064；正式T-0004于12:14:53 accepted，依据D-0063/EV-0004/D-0064/D-0061/D-0059。H1在当前范围退役但保留不确定证据；H2仍未测试、因范围暂停。结项报告前两版被NOT GO报告门拒绝，原生RLD补齐六类范围后D-0067/final-stage1-decision.v3登记，DEC-0008于12:18:11将project置not_go。没有凭报告模板宣布实验成功。实际15个reservation全settled/总15nodeSec（14个run行包含原sanity的两个attempt），无obligation或活跃worker；仅无效sanity a1的model.pt被结项清理，有效证据保留。M1-state-1221.json保存完整决定、evaluation与账务。该路径验证方法运行、真实结果导入、追加重复、cleanup与NOT GO结项；五维及独立确认未达到科学前提，由单独声明的M4功能仿真夹具覆盖。每批R04与最后页面仍继续。

R04于12:24:32真实proposal_review拒绝：reviewer暂改openai/gpt-6-luna、跨族仍true，REVIEW_UNAVAILABLE明确同Leader gpt-6-luna族，session=null/cost0/未启动后端。原用户配置随后恢复Anthropic Sonnet5.5（config.v4 D-0070/UI-0011 D-0071），project仍not_go/实际15nodeSec，无新CPU或费用。最终原生build后独立CLI check实际393/393/stale=false；M1-final-independent-page-check.json、M1-state-1230.json与两次配置收据完整保留。主会话正常/exit，自建pH复用于M7。Codex规定M1场景及这条真实方法NOT GO流程已验证，独立终审与整个补测目标尚未完成。
