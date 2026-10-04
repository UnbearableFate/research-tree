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

主会话为 Research Leader。插件记录计划原文，Leader写目标、最小设定、相关研究、初始假说与根节点
框架任务，再请用户确认。确认之前不能启动研究worker。

让主会话执行 `$research-tree ui`，它会给出独立研究对话终端的命令。在另一个终端运行后，
普通文本由UI agent处理；`/confirm` 明确确认立项，`/status` 查看摘要，`/pane` 生成进度页面，
`/config show` 查看生效配置，`/config apply` 应用用户修改后的配置，`/quit` 只关闭对话窗口。
也可以在主会话直接下达有效指令。

## 与 Claude mod 的功能对应

| Claude mod | Codex 插件 |
|---|---|
| `/research-tree` 命令 | `$research-tree` 技能、MCP `research_control`、独立CLI入口 |
| 主会话RLD | 当前Codex主会话，hooks记录会话ID和实际模型 |
| 研究对话窗口与UI子代理 | 独立终端对话窗口，每条用户消息启动一次只读Codex UI会话 |
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

MCP服务从插件目录启动，主会话每次调用需要 `project`（研究项目的绝对目录）。UI和worker由
控制器注入固定project/actor。主会话先 `research_db(method="help")` 查API；`research_control(action="help")`
列控制参数。不要让模型构造actor字段，也不要用原生spawn工具绕过确认或身份检查。

worker模型与effort来自现行配置。`inherit` 使用hooks记录的主会话模型；无法取得时明确失败，
不擅自更换模型。平台技能名会写入worker指令，worker须实际读取可用技能；不存在时要报告缺失。
worker在登记的checkout/worktree中运行，并允许写研究项目目录；使用workspace-write沙箱。
UI使用read-only沙箱。后台exec不提供交互式权限提升，失败应交Leader处理，不自动关闭沙箱。

`research_control worker` 返回的starting只表示已受理。`agents` 查看活跃锁、线程ID、退出码和运行路径；
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
