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
| `claude-mod/research-agent/` | Claude Code mod：研究对话窗口（UI agent）、进度面板与状态栏、`/research` 命令、`research_db` 等工具、工作流系统提示、文档与框架写入保护 |

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
claude --plugin-dir claude-mod/research-agent      # 项目数据库等在 /config 的 research-agent 选项中设置
claude plugin test claude-mod/research-agent       # mod 自身的测试（Miyabi 上在计算节点运行）
```

主会话即 Research Leader。`/research ui` 打开“研究对话”窗口：输入框里的每条消息交给 mod 定义的 `research-agent:ui` 子代理（主模型不会调用它），回复显示在窗口中；UI 用 `relay_to_rld` 把登记过的指令或问题转交主会话，主会话用 `post_to_ui` 把需要用户决定的事项发回窗口。`/research pane` 打开进度面板，`/research build` 生成离线页面。

## 新项目

```bash
.venv/bin/python schema/create_db.py research/<project-id>/research_tree.db
.venv/bin/python tools/research_db.py --db research/<project-id>/research_tree.db --actor rld/main \
    create_project '{"id": "P-...", "title": "...", "min_setup_doc_id": "D-0001", ...}'
```

之后的流程（冻结框架、SOTA 基线、建节点、实验、判定、决定）见规则第6节与 `schema/doc_library.md` 第5节。
