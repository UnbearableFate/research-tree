# 研究文档库设计（草案，2026-10-03）

文档库存放研究的全部正文：假说、实验设计与统计结果、新颖性与理论复核、决定理由、用户指令、委派与交付、工作流和报告。LatticeDB（`research_tree.db`，结构见 `research_tree.sql`）只存索引、状态和关系，不存正文。

基本原则：

- **没有落盘的内容不存在。** 影响决策的事实、理由和结论必须写进文档并登记，不能只存在于某个agent的上下文或消息里。
- **消息只发简短说明加文档引用。** 详细内容一律放在文档里。
- **文档一经生效就不再修改。** 要修改就写新版本，因此对某个文档ID的引用始终指向同一份内容。
- **状态只存数据库。** 文档不写“当前状态”，避免文件和数据库各存一份、彼此矛盾。

## 1. 位置与目录结构

每个研究项目一个根目录，数据库和文档库放在一起，文档库路径都相对 `docs/`。`research/<project-id>/` 是一个独立的git仓库，与代码仓库分开（代码仓库在 `.gitignore` 中忽略 `research/`）。这样代码可以按节点开分支，而文档始终只有一份，所有agent都在同一路径读写：

```
<project-root>/research/<project-id>/
├── research_tree.db, research_tree.db-wal   # LatticeDB（不进git，定期导出快照）
├── snapshots/                               # 数据库JSON导出，进git
├── messages/<agent-id>.jsonl                # 每个发送者的消息日志，进git
├── messages/window.jsonl                    # 研究对话窗口的全部对话（w-<编号>），由mod写入，进git
├── cache/literature/                        # 相关研究原文缓存（PDF/HTML），不进git；由literature笔记引用
└── docs/                                    # 文档库根，进git
    ├── project/
    │   ├── goal.v1.md                       # 研究目标
    │   ├── min-setup.v1.md                  # 最小实验设定、主指标、SOTA基线
    │   ├── config.v1.yaml                   # 生效的项目配置（research-tree.yaml 的登记版本）
    │   ├── decisions/go-or-not-go.v1.md     # 项目级决定的理由
    │   └── reports/                         # 阶段报告、GO/NOT GO报告
    ├── instructions/UI-0001.v1.md           # 用户指令，每条指令一个文件
    ├── requirements/REQ-0001.v1.md          # 经UI澄清的需求（需求记录各项与用户原话），每次提交一个新版本
    ├── workflow/                            # 本项目采用的规则版本、模板、约定
    ├── literature/LIT-0004.v1.md            # 相关研究笔记（创建节点时的缓存），可被多个节点引用
    ├── baselines/E-0002/                    # 不属于任何假说的基线实验
    │   ├── design.v1.md
    │   └── result.v1.md
    ├── hypotheses/H-0007/                   # 每个假说节点一个目录（平铺，见下）
    │   ├── hypothesis.v1.md
    │   ├── novelty.v1.md                    # 优于SOTA后RLD的新颖性复核
    │   ├── theory.v1.md                     # 优于SOTA后RLD的理论正确性复核
    │   ├── experiments/E-0031/
    │   │   ├── design.v1.md
    │   │   ├── result.v1.md                 # 冻结统计代码的输出与解读
    │   │   └── stats.v1.json                # 统计代码的结构化输出（逐seed与配对比较），可选
    │   ├── decisions/prune-after-gate.v1.md # 节点决定的理由
    │   └── notes/                           # 补充分析、讨论（经rel_describes关联）
    └── tasks/T-0088/
        ├── request.v1.md
        └── delivery.v1.md
```

**假说目录平铺在 `hypotheses/` 下，不按父子关系嵌套。** 父子关系记录在数据库的 `CHILD_OF` 边和文档头的 `parent` 字段里，树形视图由HTML生成。这样无论树多深，路径都短且稳定，便于在消息里引用。

**大文件不进文档库。** 权重、日志、逐样本预测和原始输出留在实验输出目录，文档只引用其路径。文档库只放文本和小型结构化文件（单个文件不超过1 MB）。

## 2. 文档ID、版本与生命周期

- **一个版本一个ID。** 每个版本文件是数据库里的一条 `document` 记录，有独立ID（`D-0120`）。同一文档的版本之间用 `SUPERSEDES` 边相连。文件名带版本号：`hypothesis.v2.md`。
- **决定记录在数据库里。** 每次状态变更是数据库中一条追加式的 `decision` 记录；详细理由写在普通的带版本文档里（`decisions/<简短名>.v1.md`，doc_type 为 decision 或 report），由决定记录引用。
- **生命周期：**

| 状态 | 含义 | 文件可否修改 |
|---|---|---|
| `draft` | 已登记、作者仍在编写 | 作者可修改 |
| `current` | 已交付或已采纳，可被引用作为依据 | 不可修改；登记sha256 |
| `superseded` | 已被新版本或新指令取代 | 不可修改 |

- `draft → current` 发生在作者交付时（例如worker提交交付文档或统计结果）。被决定引用的文档必须是 `current`。
- 要修改 `current` 文档：写 `vN+1` 文件，登记为新的 `document`，加 `SUPERSEDES` 边，并把旧版本标为 `superseded`。
- 发现 `current` 文档的sha256与登记值不一致时，按完整性问题报告给RLD，不得静默接受。

## 3. 文档头（front matter）

每个Markdown文档以YAML头开始。文档头只包含创建时就确定、之后不变的字段，因此即使数据库损坏，也可以从文件重建文档索引：

```yaml
---
id: D-0120
doc_type: hypothesis          # 取值同 document.doc_type
version: 2
title: 恢复子批次二阶矩的信息
summary: 未裁剪子批次二阶矩携带完整均值二次型之外的各向异性信息。   # ≤300字
about: [H-0007]               # 本文档描述的对象ID
parent: H-0002                # 仅hypothesis文档：父节点（顶层节点填项目ID）
supersedes: D-0098            # 首版省略
author_role: rld
author_id: research_leader
created_at: 2026-10-03T10:21:00Z
---
```

`status` 和 `sha256` 不写进文档头，只存在数据库里。

## 4. 各类文档的必需内容

各类文档都有模板，存放在 `docs/workflow/templates/`。暂时未知的内容写“未知”，不得留空，也不得编造。

| doc_type | 作者 | 必需内容 |
|---|---|---|
| `goal` | RLD（据用户指令） | 研究问题、目标场景、发表目标、范围与排除项、所依据的用户指令ID |
| `min_setup` | RLD | 模型、数据、训练量、评测；主指标及优劣方向、是否百分比指标；其他比较指标（过程loss、显存、训练时间等）；统一seed顺序；SOTA基线方法与来源；单次运行上限与筛选预算；**冻结的实验框架与统计代码**：版本、文件清单、记录的指标与曲线、配对比较方法、判定规则（无提升/差不多/优于父节点/优于SOTA/需要RLD复核的具体口径） |
| `hypothesis` | RLD | 一句话可证伪假说；**创建理由**：参考了哪些相关研究（列出被引用的literature文档ID）、它们留下的空白、为什么本节点具有基本的新颖性和理论正确性；机制；**计划的代码改动**；可证伪预测与实验计划；竞争解释；与父节点的差异 |
| `novelty` | RLD | 节点优于SOTA后的复核：检索记录（查询词、来源、日期），范围不限于创建时引用的文献；最接近工作的逐项对比表（机制、适用条件、实验设定、已报告结果、差异）；结论 |
| `theory` | RLD | 节点优于SOTA后的复核：推导或论证的逐步核对；关键假设；与实验结果是否一致；结论 |
| `literature` | worker/助手 | 出处（标题、作者、年份、arXiv ID/DOI/URL）、访问日期、本地缓存路径、核心方法、实验设定与结果、与本项目的关系 |
| `experiment_design` | worker | 要验证的代码改动；代码版本（含冻结框架）；配置；seed数（按筛选预算）；单次运行资源（不超过上限）；有效性验收标准 |
| `experiment_result` | worker | 冻结统计代码的输出：逐seed的主指标、其他指标、过程曲线路径、实际节点数与时长；与父节点和SOTA的配对差值及离散度；判定及依据；局限；原始产物路径 |
| `decision` | RLD | 变更字段与前后取值；理由；依据（实验、文档、用户指令ID）；判定为“需要RLD复核”时RLD的判断理由 |
| `user_instruction` | UI | 用户原话（逐字）；UI的理解；类型（指令/偏好/问题/讨论）；生效范围；取代的旧指令ID |
| `task_request` | RLD | 章节（接口检查）：任务与节点、问题与预测、干预与对照、范围与权限、资源与预算、验收与停止条件、交付；各章节的内容见规则第4节 |
| `task_delivery` | worker/助手/web builder | 章节（接口检查）：实际改动与版本、运行与产物、验证结果、资源观测、未完成与未知项；各章节的内容见规则第4节 |
| `workflow` | RLD | 规则版本、模板、项目约定 |
| `report` | RLD | 阶段总结、GO/NOT GO报告（第6、7节要求的内容） |
| `config` | RLD（mod 代用户登记） | 项目目录 `research-tree.yaml` 的原文：开发与实验平台、资源预算、阶段1门槛、子代理模型；立项确认与每次 `/research-tree config apply` 时登记新版本 |

## 5. 写入权限

| 区域 | 写入者 | 说明 |
|---|---|---|
| `project/`、`hypotheses/*/hypothesis.*`、`novelty.*`、`theory.*`、`decisions/`、`workflow/`、`reports/` | RLD | 节点和项目层面的内容、复核与决定 |
| `instructions/` | UI | 只有UI登记用户指令；用户直接在main下达的指令由RLD代为登记 |
| `hypotheses/*/experiments/`、`notes/`、`baselines/`、`literature/` | 被委派的worker或助手 | 只能写自己认领任务范围内的路径 |
| `tasks/*/request.*` / `delivery.*` | RLD / 被委派者 | |
| 任何区域 | web builder不可写 | 只读数据库和文档库 |

所有数据库写入都经过 `tools/research_db.py`（Python接口与同名CLI），它按schema检查字段、取值和引用，并按调用者身份（`<角色>/<agent ID>`）检查权限：

| 写入 | 谁可以 |
|---|---|
| 项目、假说节点、分支创建与处置、任务创建与验收、所有状态决定（`decide`） | 只有RLD |
| 文档登记、修改草稿、`draft → current` | 作者（文档类型须是该角色可写的类型），或RLD |
| 节点worker的指派（`assign_worker`）与会话绑定（`bind_worker_session`） | 只有RLD（mod 在启动worker时自动绑定会话） |
| 节点恢复文档的追加（`add_resume_docs`） | 节点的worker，或RLD |
| 实验、运行、扩展seed（`extend_seeds`）、记录判定（`record_verdict`）、实验依赖 | 实验owner worker，或RLD；节点已指派worker时，只有该worker能为它建实验 |
| 分支交还（`active → returned`） | 分支owner worker，或RLD |
| 任务开始与交付 | 任务的assignee |

每次写入是一个短事务，遇到锁冲突有限次重试。接口同时执行以下规则：

- **冻结框架。** 根节点worker实现实验框架与统计代码，RLD审核后用 `update_project(harness_ref, harness_paths)` 冻结。此后所有实验的代码必须包含该版本，且框架文件与之完全一致（git核对），否则不能记录判定。更换框架会清空SOTA基线，必须用新框架重跑。
- **SOTA基线与seed预算。** SOTA基线在统一seed上跑满 `gate_seeds`（默认3）个seed并记录结果后，才能设为项目的SOTA。节点实验的初始seed数由SOTA第一个seed的成本 c（节点数×时长）决定：满足 n×c < `screen_budget_node_h`（默认10 node·h）的最大n，至少1、至多3。判定为“差不多”或“优于父节点”时，worker可扩展到3个seed；RLD可随时扩展。
- **创建节点**必须引用至少 `project.min_related_work`（默认3）篇现行的literature文档（`rel_references`）。根节点（项目本身）只存放 baselines；不指定父节点时新节点挂在根节点下（初始假说都是如此）；指定父节点时，父节点必须已是可拓展状态。
- **开始验证**要求节点已有代码分支，且 `experiment_status` 为running；节点实验的代码必须是不同于分支基准的提交。
- **运行**按 planned → submitted（→ running）→ succeeded/failed/cancelled 推进；主指标与其他指标只能记在已成功的运行上。设为有效需要主指标、其他指标、实际节点数与时长，以及日志或输出路径；设为无效需要写明原因。重新提交（attempt 加1）只适用于失败、取消，或已成功但被判为无效的运行；之前每次 attempt 的记录保留在运行的 `attempts` 中，其用量计入累计用量。
- **产物清理**：实验登记判定后，其owner用 `run_cleanup` 运行项目目录的 `research-tree-cleanup.py` 清理产物；接口检查清理计划（在运行的输出目录内、不含日志与曲线、不属于保留类别）并把结果记入实验的清理账本。登记实验时可用 `keep` 与 `keep_reason` 声明保留的产物类别。节点任务交付和项目NOT GO都要等相关清理完成。
- **项目结项后**（GO、NOT GO、停止）不能再新建假说、实验、运行、分支或研究类任务（harness、literature、experiment、analysis）；恢复研究需要用户指令。
- **任务文档**：建任务时请求文档、交付时交付文档必须有规定的章节（见第4节文档类型表）。
- **记录判定**（`record_verdict`）要求每个seed的运行都有效且记录了主指标、其他指标、实际节点数与时长；比较对象固定为SOTA，以及父节点最新已判定的实验（顶层节点只比SOTA）。接口核对判定与比较数据一致：“无提升”当且仅当相对父节点的所有指标都不更好；“优于父节点”要求主指标更好；“优于SOTA”要求3个seed全部配对且主指标领先超过 `go_margin`（`passes_gate` 由接口计算），通过该门槛时判定只能是“优于SOTA”或“需要RLD复核”；少于3个seed时不能判“优于SOTA”，3个seed时不能判“差不多”。
- **节点结论**（`experiment_status`）必须等于节点最新已判定实验的判定，并引用该实验；“差不多”须先扩展seed；“需要RLD复核”由RLD附决定文档自行选择（选“优于SOTA”仍须通过门槛）。“无提升”的节点必须同时标为可消灭；可拓展要求优于父节点或优于SOTA。
- **复核**只在节点优于SOTA后进行，判为通过或未通过须引用RLD写的、描述该节点的novelty或theory文档；复核失败可将节点标为可消灭。
- **用户放弃。** 节点在上限或权限内无法实验时，RLD上报用户；用户决定放弃后，UI登记描述该节点（`about`）的用户指令文档，RLD引用它即可把节点标为可消灭，无需实验。
- **节点关键时间戳**由接口自动记录，调用者不能设置：创建（`created_at`）、首次开始验证（`started_at`）、首次实验即第一个运行提交（`first_experiment_at`）、首次统计判定（`first_result_at`）、首次判定优于SOTA（`beats_sota_at`）、完成即最近一次转为可拓展或可消灭（`concluded_at`，重新验证时清空）。首次类时间戳写入后不再改写。
- **GO**要求有节点优于SOTA且两项复核都通过；**NOT GO**要求所有节点都可消灭；项目停止或恢复必须引用用户指令文档。

数据库放在共享文件系统上时，LatticeDB的文件锁能否跨主机生效取决于文件系统的挂载方式（例如Lustre需要flock挂载选项）；生效时，一方以写模式打开会拒绝其他读写，只读可以同时打开。无论能否跨主机加锁，计算节点上的作业都不直接打开数据库：长时间运行的作业一旦持有写锁会阻塞所有agent，而且作业并不是任何记录的owner。作业只把结果写到输出目录，由worker登记。

git提交的分工见第6节。

## 6. 节点分支、worktree与git提交

代码和文档分属两个仓库，提交规则不同：

| 仓库 | 谁提交 | 说明 |
|---|---|---|
| 文档仓库 `research/<project-id>/` | 只有RLD | 文档不开分支。各agent直接在共享路径写自己负责的文件（第5节），写入后立即对所有人可见；RLD在批次节点统一提交。 |
| 代码仓库的节点分支 | 该分支当前的owner worker | 只在自己的worktree内提交自己的分支，以保持并行度。 |
| 代码仓库的 `main` 等共享分支 | 只有RLD | 合并由RLD决定并执行。 |

**分支与worktree的生命周期：**

1. **创建。** 节点第一次需要写代码时，由RLD创建分支 `node/<节点ID>` 及其worktree，并登记 `branch` 记录。基准取父节点分支的当前提交；顶层节点或父节点分支已不存在时取 `main`。只做新颖性或理论验证、不写代码的节点不建分支。
2. **开发。** 同一时刻只有一个owner worker可以提交。实验提交时冻结的提交打标签 `exp/<实验ID>`，写进 `experiment.code_ref`。这样之后即使删除分支，实验所用代码仍可追溯。
3. **交还。** 节点验证完成（可拓展或可消灭）后，worker确认worktree内没有未提交的改动，在交付文档中列出最后提交和主要改动，把分支状态改为 `returned`，owner交还RLD。
4. **处置。** RLD作出决定并写入决定记录，然后执行以下一种处置。三种处置都要移除worktree；只有提交在分支上的代码会保留，worktree里未提交的内容会丢失，所以交还时必须先全部提交。
   - **合并（merged）**：例如GO候选或可复用的基础设施，合并目标由RLD决定。
   - **保留（kept）**：例如可拓展节点的分支，作为子节点的基准。
   - **删除（deleted）**：例如可消灭节点。删除前确认所有实验提交都已打 `exp/` 标签。

子节点分支以父节点分支为基准，因此父节点可拓展时，其分支应保留到子节点都创建分支之后。

## 7. 消息格式

agent之间的消息是一行紧凑的JSON，只包含简短说明和引用，不复制文档内容。格式由 `message.schema.json` 定义：

```json
{"v":1,"id":"w3-0042","ts":"2026-10-03T10:21:00Z","project":"P-online-polora","from":"worker/w3","to":"rld/main","type":"delivery","re":"main-0040","about":["T-0088","E-0031"],"text":"T-0088完成：E-0031判定优于SOTA，3 seeds配对差+0.21pt。","docs":["hypotheses/H-0007/experiments/E-0031/result.v1.md","tasks/T-0088/delivery.v1.md"],"need":"ack"}
```

| 字段 | 含义 |
|---|---|
| `id` | `<发送者ID>-<序号>`，由发送者自己编号，无需中心计数器 |
| `from` / `to` | `<角色>/<agent ID>`，角色为 ui、rld、worker、assistant、web_builder |
| `type` | instruction（UI→RLD，已登记的用户指令）、task（RLD→被委派者）、delivery（任务交付）、question、reply、confirm_request（RLD→UI，需要用户决定）、ack（仅确认收到）、alert（故障、阻塞、完整性问题） |
| `re` | 所回复消息的ID；reply和ack必填 |
| `about` | 相关的数据库实体ID（项目、节点、实验、分支、决定、任务），最多5个；指令和文献等文档放在 `docs` |
| `text` | 简短说明，最多200字 |
| `docs` | 相对 `docs/` 的文档路径，必须带版本号且已登记，最多5个；instruction、task、delivery、confirm_request必填 |
| `need` | 期望对方的回应：none、ack、answer、decision；decision只用于confirm_request |

规则：

- **序列化与大小。** 用UTF-8紧凑格式（`ensure_ascii=False`、无空格），整行不超过1000字节：消息只是短说明加引用，细节一律写进文档。JSON Schema无法检查字节数，由发送工具检查。上例为358字节。
- **先记录后发送。** 发送者先把完全相同的一行追加到 `messages/<发送者ID>.jsonl`（位于文档仓库，每个发送者一个文件，避免并发追加冲突），再交给收件方。消息丢失时以日志为准对账。
- **内容在文档里。** 凡是会影响决定的信息都必须在被引用的文档里；不带 `docs` 的消息只用于确认、提问、催办和告警。接收方据此行动前，必须读取被引用的文档。
- **用户指令先登记。** 用户的话由UI先登记为 `user_instruction` 文档，再发送引用该文档的instruction消息；不得在消息里转述后直接执行。
- **不回确认的确认。** 收到ack不再回复，避免两个session相互唤醒。

### 发送工具

`tools/send_message.py` 依次完成：补全 `v`、`id`、`ts`、`project` → 按schema校验 → 检查引用（`about` 中的实体在库中存在；`docs` 已登记、未被取代且文件存在；`re` 在消息日志中）→ 在发送者日志锁内分配序号、检查1000字节上限并追加日志 → 打印这一行。任何检查失败都不写日志（退出码2）。打印出的一行由发送者用宿主的手段交给收件方：Claude Code中，RLD给worker的消息用SendMessage发送；UI与RLD之间的消息由插件调用本工具并直接投递（UI的发件箱动作，以及RLD的 `post_to_ui`）。需要再次交付同一条消息时用 `--resend <id>` 打印日志中的原行，不另编新消息。

```bash
.venv/bin/python tools/send_message.py --root research/P-xxx \
  --from worker/w3 --to rld/main --type delivery --re main-0040 \
  --text "T-0088完成：E-0031判定优于SOTA。" --about T-0088 E-0031 \
  --docs tasks/T-0088/delivery.v1.md
```

可收发消息的身份登记在 `research/<project-id>/agents.json`（地址列表，由 `/research-tree init` 写入）：

```json
["ui/ui", "rld/main", "worker/root", "assistant/a1", "web_builder/site"]
```

节点worker以节点命名（`worker/h0007`），无需登记即可发送；收件人必须已登记。

## 8. 需同步修改的地方

- `research_tree.sql`：`document.doc_type` 增加 `task_request`、`task_delivery`；新增 `branch` 表，`decision.field` 增加 `branch_status`（均已改）。
- 新增 `message.schema.json` 与发送工具 `tools/send_message.py`（均已加，测试见 `tests/test_send_message.py`）。
- 新增数据库读写接口 `tools/research_db.py`（已加，测试见 `tests/test_research_db.py`）。
- 规则文件第3、4节的需求记录、交接表和消息格式，改为引用本设计（待做）。
