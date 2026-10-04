# research-tree

多角色研究 agent 的规则与工具：面向 ML 预训练/后训练方法发现，阶段1用最小实验快速验证假说并作出 GO/NOT GO 判断。全部内容打包为一个 Claude Code 插件 `research-tree`（`claude-mod/research-tree/`），本仓库同时是它的 marketplace（同名 `research-tree`）。

## 安装

```bash
claude plugin marketplace add <本仓库的 git 地址或本地路径>
claude plugin install research-tree@research-tree
```

只在一次会话中试用而不安装：`claude --plugin-dir <本仓库>/claude-mod/research-tree`。

前提：机器上有 [uv](https://docs.astral.sh/uv/)。插件自带 Python 工具、数据库结构与规则；每个研究项目的 Python 环境由 `/research-tree init` 用 uv 在项目目录建立。

## 使用

主命令是 `/research-tree`，作用于会话所在目录。

1. `/research-tree init path/to/计划.md [--python 3.13] [--id 项目ID] [--config 配置.yaml] [--update-uv]`：确认有 uv（`--update-uv` 时先运行 `uv self update`）；当前目录还不是 uv 项目时运行 `uv init . --no-workspace --python=<版本>`（默认 3.13，即使位于另一个 uv 项目之内也建成独立项目）；再 `uv add latticedb==0.15.0 "jsonschema>=4.26" "pyyaml>=6.0"` 装好依赖。项目ID默认取 uv 项目名（即目录名）。然后在当前目录展开 `research/<项目ID>/`（docs、messages、snapshots、cache、site 等子目录），新建数据库与通信登记表，把计划原文逐字登记为用户指令，生成项目配置 `research-tree.yaml`（默认配置；`--config` 时从指定文件开始，校验后复制过来；目录里已有 `research-tree.yaml` 而没有用 `--config` 指明时拒绝，避免误用旧文件），写 `.research-tree.json` 标记项目，打开“研究对话”窗口，并让主会话（RLD）开始立项规划。
2. RLD 读计划，写研究目标与最小实验设定，建项目、检索相关研究并建立初始假说节点（都是根节点的子节点；根节点只存放 baselines），为根节点写实现实验框架与基线的任务，然后在研究对话窗口请你确认。
3. 在窗口里回复同意（UI agent 判断你的意思，插件把你的原话登记为确认），或运行 `/research-tree confirm`。确认时项目配置登记为生效版本，预算与门槛写入项目记录。确认之前插件拒绝启动 `research-tree:worker` 子代理；确认后 RLD 为根节点指派 worker 并实现它。每个节点一个 worker，身份、当前会话与恢复文档记录在节点上。

其他子命令：`config`（显示生效的项目配置；`config apply` 让 `research-tree.yaml` 的改动生效）、`status`（默认）、`ui`（研究对话窗口）、`pane`（进度面板）、`refresh`、`build`（生成离线页面）、`check`。

## 项目配置 `research-tree.yaml`

`init` 默认生成带注释的模板（`schema/config.template.yaml`），也可以用 `--config` 从自己的文件开始（例如复用集群设置）。省略的键取默认值，各项含义如下：

| 键 | 含义 | 默认 |
|---|---|---|
| `platform.dev`、`platform.experiment` | 开发（写代码、单元测试）与实验（训练、评测）在哪里、怎么运行；原样交给 RLD 和每个 worker，例如集群的登录节点与计算节点分工、作业提交命令、账户组 | 在当前机器上运行 |
| `platform.skills` | worker 启动时预加载的技能（例如集群调度系统的技能） | 无 |
| `budget.per_run.nodes`、`budget.per_run.walltime` | 单次运行（一个 seed）的节点数与墙钟上限 | 8、1h |
| `budget.screen_node_h` | 筛选预算，按 SOTA 第一个 seed 的成本决定筛选 seed 数 | 10 |
| `budget.max_parallel_workers` | 同时有任务在手的 worker 数上限 | null（不限） |
| `budget.alert_node_h` | 累计用量达到此值后提醒你，新实验和扩展 seed 暂停，直到你调高或取消它 | null（不限） |
| `stage1.gate_seeds`、`stage1.go_margin` | 判定“优于SOTA”的 seed 数与主指标领先幅度；第一个实验登记后不能再改 | 3、0.05 |
| `stage1.min_related_work` | 创建节点时至少引用的相关研究数 | 3 |
| `models.ui`、`models.worker` | 子代理的 `model`（inherit、别名或完整 ID）与 `effort` | inherit、模型默认 |

确认立项之前，文件的改动直接生效；之后改动要运行 `/research-tree config apply`：它把文件登记为新版本（`docs/project/config.vN.yaml`）和一条用户指令，更新项目记录，重新注册 UI 与 worker 子代理，并通知 RLD。RLD 就是主会话，它的模型由你启动 Claude Code 时选择。

## 插件内容（`claude-mod/research-tree/`）

| 路径 | 内容 |
|---|---|
| `.claude-plugin/plugin.json`、`hooks/`、`types/` | Claude Code 插件：`/research-tree`、研究对话窗口（UI agent）、worker 子代理类型、进度面板与状态栏、`research_db` 等工具、工作流系统提示、写入保护 |
| `rules/research-tree-rules.md` | 工作规则（角色、沟通、项目配置、阶段1、生命周期、产物清理） |
| `schema/research_tree.sql`、`schema/create_db.py` | 数据库结构规格（LatticeDB 属性图）与建库 |
| `schema/config.template.yaml`、`schema/config.schema.json` | 项目配置的模板（即默认值）与校验规则 |
| `schema/doc_library.md`、`schema/web_builder.md`、`schema/message.schema.json` | 文档库、页面与消息格式设计 |
| `tools/research_db.py` | 数据库读写接口（Python 与 CLI），执行全部字段、权限与状态规则 |
| `tools/research_tree.py` | `/research-tree` 的确定性部分：初始化项目、登记用户指令、推进立项阶段、显示与应用项目配置 |
| `tools/project_config.py` | 读取、补全与校验 `research-tree.yaml` |
| `tools/send_message.py` | 校验、记录并打印一条消息 |
| `tools/build_site.py` | 生成离线单文件进度页面 |
| `tools/make_demo.py` | 生成虚构示例项目 |
| `tests/` | Python 测试（`test_*.py`）与插件测试（`register.test.ts`） |

仓库根目录另有 `demo/`（`make_demo.py` 生成的虚构示例项目，页面 `demo/research/P-demo-lora-opt/site/index.html`）与开发用的 `pyproject.toml`。

## 开发与验证

在共享集群上，按集群的规定在计算节点运行测试与生成。

```bash
P=claude-mod/research-tree
.venv/bin/python -m unittest discover -s $P/tests        # Python 测试（需要 git；有 node 时检查页面脚本语法）
claude plugin validate . && claude plugin validate $P   # marketplace 与插件清单
claude plugin test $P                                   # 插件测试
.venv/bin/python $P/tools/make_demo.py --dest demo      # 重新生成虚构示例项目
```
