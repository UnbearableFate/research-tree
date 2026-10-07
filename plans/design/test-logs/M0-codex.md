# M0 Codex 真实宿主补测（进行中）

日期：2026-10-07。scratch：`/tmp/research-tree-codex-20261007-1XA9OP`。主模型要求 gpt-6-luna / medium；没有用 requested 代替 observed。基础设施记录见 `codex-infrastructure.md`。

## 已中止的尝试

- `rt-test-M0-codex`：首次立项会话中止。确认前未开始根训练。暴露首次 init 漏记主模型、测试计划与配置指标不一致等问题；保留原始目录，不记通过。
- `rt-test-M0r2-codex`，Herdr `rt-codex-m0r2` / `w3:pF`，线程 `01a11569-db4c-7632-91ec-fd9c43e1d8d0`：主会话 Full access，原生插件已安装并信任四 hooks。

M0r2 的 prepare 保留已有计划与配置。确认门原文：`ValueError: plan must be confirmed by the user before a worker starts`。完成文档登记后，只读快照 `<scratch>/M0r2-planning-snapshot.json` 为 phase=awaiting_confirmation，1 project / 2 hypotheses / 1 open 未分配 task / 0 experiment / 0 run。

首次 init 后实际 observed：

```json
{"ts":"2026-10-07T08:11:59Z","agent":"01a11569-db4c-7632-91ec-fd9c43e1d8d0","actor":"rld/main","event":"observed","model":"gpt-6-luna"}
```

测试主控阅读计划后，以明确的临时测试确认消息授权 600 node-seconds、仅根 sanity / Adam 与 momentum seeds 0/1/2 / 冻结，不授权假说实验。原生 confirm 登记 D-0015（instructions/UI-0004.v1.md），配置 D-0014（project/config.v1.yaml）。这些是临时项目的测试输入，不是替真实用户确认研究计划。

根任务 T-0001 指派 worker/root。实际运行 `b1c4442787da459b9d24499199741349`，线程 `01a11577-c6b4-7522-8a2d-328d50ad3035`，exit 0 / completed，但工作在 Git 分支创建处停止，任务未交付或验收：

- `.git/refs/heads` 写入被 workspace-write 后台沙箱拒绝。
- 两次 research_message 参数类型 notice/blocker 非法，分别返回 KeyError。worker 的 post_to_ui 也按角色正确拒绝。
- 确认消息与完成通知投递失败：`no rollout found for thread id 01a11569-db4c-7632-91ec-fd9c43e1d8d0`。消息仍持久化在 inbox，主会话读取并回执，没有盲目重发。
- worker 只有 requested=gpt-6-luna / medium，缺少 observed；不宣称实际模型已验证。
- CODEX_HOME 在原生插件 MCP 进程中缺失，是隔离会话、插件/hooks 与队列脱离的实际证据。

未创建实验或 run，预算为 0；主会话停止恢复，未运行训练。原始事件、state、stderr、answer 位于该 run 目录；项目内审计 `docs/project/reports/worker-attempt.v1.md` 为 D-0016，verify_document=true。主会话创建过一个空的 node/root-harness worktree，未交 worker；保留。此尝试不计为根流程通过。

## 新项目重测

- 当前 `rt-test-M0r3-codex`，Herdr `rt-codex-m0r3` / `w3:pF`，隔离 `codex-home-M0r3`。
- 原生主会话参数：`--model gpt-6-luna -c model_reasoning_effort=medium --sandbox danger-full-access --ask-for-approval never --no-alt-screen`。CLI 显示 permissions: YOLO mode。
- 隔离 config.toml 明确设置 sandbox_mode=danger-full-access，使临时后台 worker 同样采用 Full access。UI 仍只读。
- 安装当前构建包；MCP 传递 CODEX_HOME、worker 原生权限选择、消息类型/提示已修复。prepare 进行中。
- `test-inputs/planning/` 是 M0r2 真实生成的规划文档模板，路径和代码提交已按新项目替换、D-ID 引用改为文档路径。未复制数据库、用户指令/确认、模型日志或运行状态；新会话必须按当前项目重新登记、核验和确认。
- 根 sanity / 基线 / 冻结、配置版本应用、六视图与实际 worker observed/通知均仍待验证。M0 尚未通过。

## M0r3 的实际规划与通知

prepare 已完成并保留输入。主会话重新登记当前项目、D-0003 至 D-0005、D-0007、D-0014，两个直属假说、未指派的 open T-0001；确认前 worker 被拒，phase=awaiting_confirmation，没有确认、训练或 worker run。

实际 config apply 事件 `event-d4620c5e4d984ae6b768afd7eff405ba` 投递为 queued。Stop hook 检测未处理 inbox 并阻止结束，主会话读取并 acknowledge；原生队列随后将同一事件送进真实主线程，主会话读取 config.v1.yaml 与 UI-0004.v1.md 并再次 acknowledge。由此验证主会话 MCP 环境修复后的真实队列、持久化收件箱、Stop 提醒与幂等回执；未将其当作根 worker 成功。

额外 app-server 诊断发现后台显式 MCP 仍缺环境 allowlist。主控要求保持未确认状态，停止此项目，未启动 worker。原生记录保留。

## 当前 M0r4 重测

新目录 `rt-test-M0r4-codex`、隔离 `codex-home-M0r4`，Herdr `rt-codex-m0r4` / `w3:pF`，原生启动参数同 M0r3。新 code HEAD `ad85b8dfcd4560c3d3c3fc46f23eb825ededa243`；600 node-seconds、每次 10 s、discovery off。最新构建补齐后台显式 MCP 环境与 lens 接口，adapter 21 项通过。

`planning-inputs/` 只包含上一轮的规划内容模板，路径和 code HEAD 已适配，不复制数据库、确认、指令、模型观察、运行或 accepted 状态。新的主会话必须重新登记并核验，不沿用旧 D-ID。prepare 正在执行；根 worker 与 M0 仍未记通过。

## M0r4 当前实际证据

prepare 保留全部输入并建立 uv 环境，测试根提交 8ed07fe。主线程 `01a11598-c45f-7fe2-a857-272bb77aa669`，模型 observed=gpt-6-luna。正式规划 D-0014 经核验，当前目标 D-0008、设定 D-0009、指标 D-0002、协议 D-0010、配置 D-0003、两个已核验文献 D-0006/D-0007。确认前 worker 原生门拒绝；`M0r4-planning-snapshot.json` 为 awaiting_confirmation，2 个直属假说，open 未分配 T-0001，0 experiment/run/evaluation。

主控阅读正式计划后发送仅根范围的显式测试确认；登记 D-0015 `instructions/UI-0005.v1.md`，phase=confirmed。实际 root run `d5315e54e3154f3fad9d890b23aa77c5`，thread `01a115a3-51b0-7f63-8db4-dac840942c1f`；原生 session 的权限文本确为 danger-full-access，模型日志 requested/observed 均 gpt-6-luna，effort 请求 medium。证据 `M0r4-live-worker-proof.json`，没有用配置推定 actual 权限。

首次 root 在 update_task 同时传 status=in_progress 和 assignee_id=root，被正确的 RLD 分配权限拒绝，随后停止并记录 D-0016 阻塞文档。检查真实参数及接口证明是模型调用错误，生产角色门保持不变。主控纠正，RLD 记录 D-0017，并由同一身份、同一线程恢复 run `c0946fc9710544a5b896cc5ebef492e6`；status-only 认领成功，T-0001=in_progress。不得把第一次的 completed 当交付成功。

活跃补充消息 `321367e9187f4d98a30e72475ceb6e04` 实际 queued，收据在 cache/codex/followups；没有盲重发。worker 实现并提交 runner、paired stats 和固定配置；RLD 从实际代码发现 manifest 的协议字段、source_counts 缺口，要求在冻结前补齐，新版本仍沿原线程。当前 `M0r4-root-progress.json`：0 科学 experiment/run，预算 0，22 文档；T-0001 仍进行中。根 baseline、冻结和页面验收尚未通过。

## 根 sanity 的 unknown 与明确取消测试

冻结后 code 为 `8dee599ceaacde612f5b73b6ddc5500219488e4f`。RLD 审核修订最小设定到 D-0030：固定 train/runner/stats 和三个配置，排除计划允许改动的 methods.py；未改科学门槛。实际首个 sanity E-0001/s0 attempt 1 使用 nohup，本地启动返回 PID 1775507，随后进程不存在且只有空 launcher.log/submitted.pid，无 metrics/manifest/usage。run=unknown，RS-0001=held_unknown，10 node-seconds 是预留而非实际费用。未盲重提，未结算或填写0。只读 `M0r4-current-snapshot.json` 留存此状态。

测试控制器随后提供明确、仅临时项目的用户取消与释放决定：再次核查无活跃作业后，引用新 current user_instruction 取消原尝试并释放预留，保留原实际用量未知历史；仅允许同 run 下一 attempt 和原六个基线，改用同步前台10秒上限、真实退出码及原始产物。该恢复仍进行中，不记为 sanity/基线通过。

M0r4 新事实：attempt2原始前台产物成功、usage1秒，但worker填写估计timestamp，valid后更正按冻结门拒绝。RLD引用审计文档撤回attempt2，保留已结算1秒；明确授权工程attempt3后实际前台exit0、manifest时间程序读取、valid及1秒结算。首个Adam s0同样真实exit0，但manifest缺protocol错误定义的counts.gate_seeds=3，被PAIRING_MISMATCH拒绝（且top-level match字段也不完整）；失败作业真实1秒已结算，没有生成baseline Evaluation。

查明是规划fixture的per-run观测counts与种子数量混淆，以及wrapper未emit所需实际参数。保持生产检查/现行文档/原产物；测试控制器决定停止M0r4，不视为科学NOTGO，保留unknown/撤回/失败及所有用量，新M0r5用全新项目与一致输入重跑。M0r5只复制代码和规划正文，protocol required_counts改为实际n_train/n_val/epochs/steps，配对数量仍为min_pairs/project.gate_seeds=3，0.5pp和确认seed不变；wrapper按实际配置emit所需参数，未降低科学/预算门。

## M0r5 根流程通过

全新目录 `rt-test-M0r5-codex`、隔离 `codex-home-M0r5`，安装 cp/角色/项目参数修复后的构建；主要五文件源码与原生安装哈希一致（`latest-native-package-consistency.json`）。实际 prepare 保留输入；init本项目重新登记并核验两篇文献，确认前 worker 返回必须用户确认、无运行。正式计划后由已获授权的临时测试控制器明确确认仅根框架/一次sanity/六基线/验收（D-0015）；假说与确认seed未执行。

RLD thread `01a115e0-4a9d-76e0-9bdf-c2b67f6682d9`，root worker thread `01a115e8-64a6-7f90-ba75-4177e3944830`，run `4575193b931a4f5ea1dffd292f57eceb`，observed均gpt-6-luna。原生turn_context两者实际 danger-full-access/approval_policy=never（`M0r5-native-permissions-and-copy.json`），不是只按config推断。真实规划含一次 cp research-tree.yaml 到新文档，执行成功，旧源未改；重新检验了误拒修复。

RLD冻结提交 `66b12ee64652214013d3d04d4319af1344f9d422`，六个 train/runner/stats/config 文件，methods.py 不冻结。真实managed worker执行提供的工程驱动，经安装包public MCP与本机CPU完成E-0001 sanity、E-0002 Adam三个seed、E-0003 Momentum三个seed；原始manifest/metrics/curve/log/usage和MCP全日志保留。驱动没有数据库造数，也不是模型/评审替身；公开API参与登记、导入、统计、实际结算和清理。它的design/delivery路径绑定真实提交，不复用旧commit文本。

RLD于10:32:09接受T-0001，交付D-0021及两版根审计报告可读，inbox已核对并幂等ack。只读快照`M0r5-root-accepted.json`；原生check返回page_version139/db_version139/stale=false；无活跃worker。该共同根流程已通过。配置同族R04和独立UI默认提示等横切补测继续进行；整批未申请完成终审。随后新增的init认证检查不在此安装中，需新项目单独验证。

### R04、配置恢复与独立 UI

临时测试用户将 reviewer 改为同族 openai/gpt-6-luna 并保持 require_cross_family=true，native config apply 登记 config.v3 D-0024。10:43:21实际 research_review proposal_review 返回 REVIEW_UNAVAILABLE，明确 same-family 拒绝，cost_usd=0，没有启动外部 reviewer。随后用户恢复 anthropic/claude-sonnet-5-5，native apply 登记 config.v4 D-0026，最终 effective 配置与原跨族值一致；原错误调用不隐藏。

从真实 human-facing `codex_cli.py ui` 启动独立 UI。进度问题 run6214d21454a441eb8676f2e4d2f6eb70/thread01a115fc-cc24-7f72-89c9-f50ee65e96d3 实际 completed/exit0、observed gpt-6-luna，原生 turn_context 为 read-only。它先误传材料根目录，被固定项目门拒绝，随后省略 project 成功读取当前 status/任务/evaluations/go_candidates；回复准确引用data_version151、T-0001 accepted、两个有效三seed基线与空GO候选，actions=[]，没有确认或新增授权。证明默认 UI 角色提示与真实工具链可完成查询，但保留首次参数错误。

需求草稿 runef81fae7461641e384c3c10b9db03067/thread01a11602-e1b7-7f70-bcdb-98c59e26293b 暴露另外两处提示/schema信息缺口：先使用 authorization/open_questions 未知 fields，被拒后只保存标题；随后把向用户澄清的问题误作为 question 给 RLD，并把 REQ-0001 放 about。实际动作 failed，错误 about: REQ-0001 is not a project in the database；草稿open、用户原话持久化、没有虚假指令/确认或盲重放。证据 `<scratch>/M0r5-ui-and-r04-proof.json`，不将这一需求流程记为通过。

修复明确 fields 合法字符串键、向用户澄清用 reply/actions=[]、暂不提交时禁止 question/submit、REQ只作draft/submit的req；MCP schema列出合法 fields，错误信息可修正。新增失败动作/草稿保留/无重放边界回归，23项adapter与10项打包检查通过；新项目需再测真实草稿、提交与修订。旧安装/原事件保留。实际 UI `/status`、`/pane`、`/config show` 都执行成功，config仍v4，页面再生data_version151。已 `/quit` 关闭UI窗口、正常退出主会话，用户pane w3:pF保留并复用于新M2。
