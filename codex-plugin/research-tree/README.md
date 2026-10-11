# research-tree for Codex CLI

开发者从仓库根目录运行 `python3 scripts/build_plugins.py --target codex`，再安装生成的 marketplace
或 ZIP。仓库中的 `codex-plugin/research-tree` 只存放适配层；发布包还包含构建时加入的共享代码。

## 安装与开始

需要 POSIX 环境、Python 3、uv 和已登录的 Codex CLI。已验证 CLI 0.160.0；需支持插件、
stdio MCP、`codex exec --json` / `exec resume`、`codex queue` 和生命周期 hooks。

解压 `research-tree-codex-0.1.0.zip`，然后：

```bash
codex plugin marketplace add /absolute/path/to/research-tree-codex
codex plugin add research-tree@research-tree
```

在研究项目目录启动 Codex，先输入 `$research-tree prepare`（可加 `--python 3.13`、`--update-uv`）：它用 uv 把
当前目录建成项目环境并安装共享工具所需依赖，再生成研究计划模板 `plan.md` 和默认配置 `research-tree.yaml`，
已有文件不会覆盖。这一步直接调用共享 shell 脚本，不需要 Python、MCP 或项目初始化；也可在终端运行
`sh <安装后的插件目录>/tools/prepare.sh`。

填写 `plan.md`（研究目标与初始假说必填，其余各节可留给 Leader 决定）、按需修改 `research-tree.yaml` 后，
审阅并信任插件 hooks，再输入 `$research-tree init`（计划默认 `plan.md`，配置默认本目录的 `research-tree.yaml`）。

主会话为 Research Leader。新模板显式使用 `workflow.mode: fast_screening` 与
`discovery.mode: incremental`：先写目标、最小设定、协议/指标、资源上限和根节点框架任务，
请用户确认最小范围。确认之前不能启动 Architect/Worker 或提交作业。候选与文献可以继续准备，
无需等完整候选池才能确认和构建公共框架。旧配置未声明新模式时保持 strict/full；显式
`strict`、`full`、`precheck` 保留相应严格/整批门，不会因升级静默放宽。

UI 按需使用，不需要常驻 UI agent。`$research-tree pane` 生成当前研究树、结果对比和项目状态页面；
需要独立对话窗口时执行 `$research-tree ui`，按返回命令在另一个终端打开。窗口中的
普通文本才会临时启动只读 UI agent；`/confirm` 明确确认立项，`/status` 查看摘要，`/pane` 生成进度页面，
`/config show` 查看生效配置，`/config apply` 应用用户修改后的配置，`/quit` 只关闭对话窗口。
也可以在主会话直接下达有效指令，无需在 UI 重复授权。UI 不参与科学决策或实验准入，页面失败不回滚已成功的科学记录。

## 默认快速研究循环

1. 用户确认最小范围后，Experiment Architect 沿用根节点 worker 的身份、会话、任务所有权和锁，
   构建共享 harness、统计、baseline 与统一评测实现。框架 sanity 验收并由 Leader 冻结后开始正式运行
2. Hypothesis Explorer 同时阅读文献、基础假说和负向/不确定发现，提出可证伪候选、变体、组合
3. Leader 逐个接纳就绪候选：`discovery select --candidate CAND-编号`，再
   `discovery gate --candidate CAND-编号`。A 就绪不等 B；最终由数据库按当前候选和范围重新校验
4. Experiment Workers 并行做便宜筛选。Evidence Analyst 对照现行原始证据，建议补 seed、最小对照、
   扩展、暂停或淘汰，并把负向/不确定发现反馈 Explorer。建议不改变状态，Leader 负责决策和登记
5. 只给少数有潜力的方法锁定方法/主张、补足复制与关键对照、使用独立确认材料、做最终五维复核，
   再由 Leader 作项目 GO/NOT GO。刚出现 `positive_signal` 不自动耗用确认材料

轻量候选有五项：`prediction`、`intervention`、`comparator`、
`resource_ceiling: {nodes: 正整数, walltime_s: 正整数}`、`stop_conditions`（字符串）。
必须在已确认范围和预算内；代码或科学配置都可构成干预，输出路径、walltime、seed 等执行字段不算。
思想来源、代码起点、比较参照和投入状态分开：fast 模式的 `parent_id` 为思想祖先，
`code_parent_id` 与 branch `base_commit` 指明代码起点，`comparator_experiment_id` 指明参照；
未获胜基础假说也能提出并行变体。节点/实验设计采用五个精确章节：可证伪预测、干预、匹配对照、
资源上限、停止与继续条件；节点额外复制已批准的问题锚点，资源上限节为 JSON。

fast_screening 的普通筛选不等待每次新的模型代码审查，保留同方法 sanity、数据/指标有效性、
原始可追溯结果、身份、匹配对照、预算和防重复；当前真实泄漏/指标错误仍阻断有效比较。
误读路径或协议时保留原异议、补证、复核并明确裁决，不靠反复换 reviewer 清空问题。
有效 baseline 的一个匹配 seed 可支持首轮筛选，其余 seed 继续；部分参照不等于完整 SOTA 或 GO。
只有仍适用的 `positive_signal` 支持上限与授权内的自主补 seed；旧、负向或不确定结果不是自动许可。
目标实验设计的“预声明最小对照”JSON 列出精确代码、配置、资源和 seed 数，Leader 在目标实验提交前
`approve_minimum_controls`；之后用 `ablation_of` + `predeclared_control_id` 执行精确批准的对照可免
单独 `ablation_plan`。新复杂消融、主张扩大和昂贵矩阵仍走适用审查与授权。

Explorer/Analyst 由 `research_control(action="explorer"|"analyst", params={"task":...})` 启动，只读，
不写文件/DB、不运行实验、不宣告 GO；返回真实文献/实验/评估/运行和版本化文件引用。
Leader 保存其交付。Architect 用 `action="architect"` 与根节点 ID 启动，不能与 root worker 别名并发起第二个 writer。

`workflow.mode` 与 `discovery.mode` 分别控制实验路径和发现路径：`incremental + strict` 仍逐候选
检查严格回执/文献；`full`/`precheck` 保留整批发现门，`off` 只跳过发现，不跳过实验有效性或用户授权。

## 与 Claude mod 的功能对应

| Claude mod | Codex 插件 |
|---|---|
| `/research-tree` 命令 | `$research-tree` 技能、MCP `research_control`、独立CLI入口 |
| 主会话RLD | 当前Codex主会话，hooks记录会话ID和实际模型 |
| 按需研究界面 | pane/build 生成页面；可选独立对话窗口每条用户消息启动临时只读 UI 会话 |
| Explorer / Evidence Analyst | 只读建议会话，Leader 保存候选、证据与交付并作决定 |
| Experiment Architect | 根节点 worker 的同一身份/锁，维护共享框架和基线 |
| worker子代理、SendMessage续接 | `codex exec` 独立会话，活跃时queue、空闲时按已绑定ID resume |
| 节点worker绑定与恢复 | 同一共享数据库字段、恢复包和版本化文档；进程锁防重复启动 |
| `research_db` 与权限/预算/科学门槛 | 调用同一份共享Python API；MCP角色由控制器固定 |
| UI发件箱、需求草稿与版本提交 | 结构化UI响应、一次性动作账本、原话记录与共享需求文档 |
| `post_to_ui`、消息日志 | 同一消息校验器；持久化后用 `codex queue` 投递 |
| 进度面板和状态栏 | `status`摘要、独立对话终端、同一六视图离线HTML页面 |
| 写入保护与会话上下文 | Codex SessionStart / PreToolUse / PostToolUse / Stop hooks |

研究规则、配置、LatticeDB结构、文档与消息格式、GO/NOT GO逻辑、预算和页面生成器来自
`shared/research-tree/`，构建时复制进安装包。源码不维护第二份业务实现。

## 运行和恢复

MCP服务从插件目录启动，主会话每次调用需要 `project`（研究项目的绝对目录）。UI、worker、
Architect、Explorer 和 Analyst 由控制器注入固定 project/actor。主会话先 `research_db(method="help")` 查API；`research_control(action="help")`
列控制参数。不要让模型构造actor字段，也不要用原生spawn工具绕过确认或身份检查。
评审以后台任务启动，立即返回 ticket；用 `research_review(ticket=…)` 查询同一任务并取回结果。
Leader 在 pending 期间继续独立工作，不把后台进程的超时上限变成长时间同步等待，也不重复提交同一评审。
观察超时后仍须核对原任务/进程，pending 不代表失败。MCP/后台包装器保留退出和清理余量。

worker模型与effort来自现行配置。`inherit` 使用hooks记录的主会话模型；无法取得时明确失败，
不擅自更换模型。平台技能名会写入worker指令，worker须实际读取可用技能；不存在时要报告缺失。
Explorer/Analyst 的模型与 effort 来自对应角色配置，恢复时沿用其既有身份和会话；它们不继承执行角色的写权限。
full discovery 的规划阶段用 `research_control lens` 启动只读候选助手，模型来自 models.lens_assistant。
助手使用固定 assistant 身份，不写科学记录或文件，也不继承 worker 的 Full access；实际输出由控制器保存，Leader 核验后合并。
worker在登记的checkout/worktree中运行，并允许写研究项目目录；默认使用workspace-write沙箱。
用户在当前 CODEX_HOME/config.toml 明确设置 `sandbox_mode = "danger-full-access"` 时，worker 继承该 Full access 选择。
插件 MCP 传递 CODEX_HOME，确保后台会话、登录、插件/hooks 与消息队列使用同一隔离配置目录。
若启动 Codex 时设置了 `CLAUDE_CONFIG_DIR` 或 `PI_CODING_AGENT_DIR`，插件及后台 MCP 也传递这些配置目录，所选评审后端使用同一登录环境；未设置时保留各 CLI 的默认配置路径。
UI、Explorer、Analyst 和 lens 使用 read-only 沙箱。后台exec不提供交互式权限提升，失败应交Leader处理，不自动关闭沙箱。

`research_control worker/architect/explorer/analyst` 返回的 starting 只表示已受理。`agents` 查看活跃锁、线程ID、退出码和运行路径；
`cache/codex/runs/<id>/` 保存请求、JSONL事件、标准错误、最终回复与状态。
同一身份已有活动轮次时，新任务排入原线程；无法续接时必须先核实原轮次停止，才可 `restart=true`。
会话结束不等于实验作业结束，不因agent重启重复提交原作业。

消息先入共享日志，再持久化为inbox事件，最后通知主会话。queued、acknowledged与落实结果分别记录。
无主会话地址、投递失败或超时不会丢弃事件；主会话恢复后读取inbox并acknowledge。
超时记为unknown，不自动重发；显式resend只会重投确认失败/未投递的原消息。
UI动作执行前写入applying状态，异常或中断后保留账本，核对实际文档后再恢复，不盲目重放。

hooks需要用户信任，文件保护是工作流护栏，不能防御任意shell程序绕过。没有hook上下文时，
可用 `research_control attach` 登记实际主会话ID和模型。已有另一个Leader时不自动覆盖地址，
交接前核对原会话与科研作业。此版本用终端窗口和HTML提供界面，不修改Codex的TUI源码。
attach 支持地址与 inherit 模型登记，不构成 observed 模型证据；跨族评审仍需要可信 hooks 的实际观察记录，否则返回 REVIEW_UNAVAILABLE。

`status`/`refresh` 读取轻量摘要，不全量遍历文档和曲线。摘要里的 GO 为 `null` 表示尚未核验，
不是不合格；真正判断资格时显式调用 `get_eligibility`。需要完整页面时再 `pane`/`build`，查看其数据版本。

## 验证

从源码仓库执行，集群上放在计算节点：

```bash
python3 scripts/build_plugins.py --target all
.venv/bin/python -m unittest discover -s dist/codex/plugins/research-tree/tests
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/check_codex_install.py dist/codex
.venv/bin/python scripts/check_codex_sessions.py dist/codex/plugins/research-tree --evidence /tmp/new-session-check
```

安装检查使用隔离CODEX_HOME，验证原生插件安装、技能发现、MCP握手、初始化、文档/项目/确认与页面。
会话检查使用真实Codex CLI和本地确定性Responses服务，验证exec、活跃消息排队、resume、独立UI及线程绑定；
不调用付费模型，不能替代对实际模型研究质量的评估。

接口依据：[OpenAI插件打包文档](https://developers.openai.com/plugins/build/plugins)、
[MCP配置](https://developers.openai.com/codex/mcp)、
[hooks文档](https://learn.chatgpt.com/docs/hooks)。


发布包内的 `RELEASE.md` 区分模拟/传输夹具、真实宿主 CPU toy training 与未执行的 GPU/调度器科研训练，并保留完整 A/B/C benchmark 开放项。
