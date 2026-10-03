# research-agent

多角色研究 agent 的规则与工具：面向 ML 预训练/后训练方法发现，阶段1用最小实验快速验证假说并作出 GO/NOT GO 判断。

| 路径 | 内容 |
|---|---|
| `reusable-research-agent-rules-20261003.md` | 工作规则（角色、沟通、阶段1、生命周期、产物清理） |
| `schema/research_tree.sql` | 数据库结构规格（LatticeDB 属性图；每张表 = 一个节点 label） |
| `schema/create_db.py` | 建空库：Meta 节点与索引 |
| `schema/doc_library.md` | 文档库、版本、权限、分支与消息设计 |
| `schema/message.schema.json` | agent 间消息格式 |
| `schema/web_builder.md` | 进度与发现页面设计 |
| `tools/research_db.py` | 数据库读写接口（Python 与 CLI），执行全部字段、权限与状态规则 |
| `tools/send_message.py` | 校验、记录并发送一条消息 |
| `tools/build_site.py` | 生成离线单文件进度页面 |
| `tools/make_demo.py` | 生成虚构示例项目（代码仓库、数据库、文档库、消息、页面） |
| `tests/` | 单元与端到端测试 |
| `demo/` | `make_demo.py` 生成的虚构示例项目 |
| `tools/research_tree.py` | `/research-tree` 的确定性部分：在当前目录初始化项目、登记用户指令、推进立项阶段 |
| `claude-mod/research-agent/` | Claude Code mod：`/research-tree` 命令、研究对话窗口（UI agent）、worker 子代理类型、进度面板与状态栏、`research_db` 等工具、工作流系统提示、写入保护 |

## 构建与验证

依赖由 uv 管理（`pyproject.toml`）。在 Miyabi 上，测试与生成属于计算类工作，须在计算节点上运行（见 `miyabi-pbs-cmd`）：

```bash
qsub -I -q interact-g -W group_list=<group> -l select=1 -l walltime=00:30:00
cd research-agent
.venv/bin/python -m unittest discover -s tests          # 全部测试（需要 git；有 node 时检查页面脚本语法）
.venv/bin/python tools/make_demo.py --dest demo          # 生成虚构示例项目
.venv/bin/python tools/build_site.py --db demo/research/P-demo-lora-opt/research_tree.db
```

示例页面：`demo/research/P-demo-lora-opt/site/index.html`（离线打开；`#tree/H-0003` 直接打开节点详情）。示例中的方法、文献与数字全部是虚构的。

## Claude Code mod

```bash
claude --plugin-dir /work/xg24i002/x10041/research-agent/claude-mod/research-agent   # 在任意目录启动
claude plugin test claude-mod/research-agent                                          # mod 自身的测试（Miyabi 上在计算节点运行）
```

主命令是 `/research-tree`，它总是作用于会话所在目录。前提是机器上有 [uv](https://docs.astral.sh/uv/)；项目环境由 init 用 uv 建立，之后各子命令使用该目录的 `.venv`。`toolsDir` 选项指向本仓库，默认即本仓库路径。

1. `/research-tree init path/to/计划.md [--python 3.13] [--id 项目ID]`：确认有 uv 后运行 `uv self update`；当前目录还不是 uv 项目时运行 `uv init . --no-workspace --python=<版本>`（默认 3.13，即使位于另一个 uv 项目之内也建成独立项目）；再 `uv add latticedb==0.15.0 "jsonschema>=4.26"` 装好依赖。项目ID默认取 uv 项目名（即目录名）。然后在当前目录展开 `research/<项目ID>/`（docs、messages、snapshots、cache、site 等子目录），新建数据库与通信登记表，把计划原文逐字登记为用户指令，写 `.research-tree.json` 标记项目，打开“研究对话”窗口，并让主会话（RLD）开始立项规划。
2. RLD 读计划，写研究目标与最小实验设定，建项目、检索相关研究并建立初始假说节点，为根节点写实现实验框架与基线（baselines）的任务，然后在研究对话窗口请你确认。
3. 在窗口里回复同意（UI agent 登记你的原话并确认），或运行 `/research-tree confirm`。确认之前 mod 会拒绝启动 `research-agent:worker` 子代理；确认后 RLD 指派 worker 实现根节点。

其他子命令：`status`（默认）、`ui`（研究对话窗口）、`pane`（进度面板）、`refresh`、`build`（生成离线页面）、`check`。研究对话窗口里的每条消息交给 mod 定义的 `research-agent:ui` 子代理（主模型不会调用它）；UI 用 `relay_to_rld` 把登记过的指令或问题转交 RLD，RLD 用 `post_to_ui` 把需要你决定的事项发回窗口。

## 新项目

```bash
.venv/bin/python schema/create_db.py research/<project-id>/research_tree.db
.venv/bin/python tools/research_db.py --db research/<project-id>/research_tree.db --actor rld/main \
    create_project '{"id": "P-...", "title": "...", "min_setup_doc_id": "D-0001", ...}'
```

之后的流程（冻结框架、SOTA 基线、建节点、实验、判定、决定）见规则第6节与 `schema/doc_library.md` 第5节。
