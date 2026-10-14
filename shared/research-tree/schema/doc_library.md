# 研究文档库与消息契约（version 3 / schema 23）

文档库存放研究的全部正文：假说、实验设计与统计结果、新颖性与理论复核、决定理由、用户指令、委派与交付、工作流和报告。LatticeDB（`research_tree.db`，结构见 `research_tree.sql`）只存索引、状态和关系，不存正文。

本契约仅用于 version 3 配置与 schema 23 数据库，工作流固定为快速筛选和增量发现。旧项目、配置、数据库拒绝打开并给出迁移说明；不升级、不补写缺失身份或把历史回执重新解释为当前证据。迁移应保留旧项目档案，在新目录用当前模板显式重建计划、配置及所需证据登记，重新确认范围；不得通过新项目重置已使用确认材料或已发生的费用。

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
├── messages/<role>--<agent-id>.jsonl                # 每个发送者的消息日志，进git
├── messages/window.jsonl                    # 研究对话窗口的全部对话（w-<编号>），由mod写入，进git
├── cache/discovery/proposals/*.json        # Explorer 实际提案：{source, candidates}，source 标明真实来源
├── cache/literature/                        # 相关研究原文缓存（PDF/HTML），不进git；由literature笔记引用
└── docs/                                    # 文档库根，进git
    ├── project/
    │   ├── goal.v1.md                       # 研究目标
    │   ├── min-setup.v1.md                  # 最小实验设定、主指标、SOTA基线
    │   ├── config.v1.yaml                   # 生效的项目配置（research-tree.yaml 的登记版本）
    │   ├── metric-spec.v1.json              # 指标规范：每个指标的方向、单位、效应、最小实际收益、保护阈值
    │   ├── protocol.v1.json                 # 实验协议：评测类型、配对字段、必须一致的设定与计数
    │   ├── decisions/go-or-not-go.v1.md     # 项目级决定的理由
    │   └── reports/                         # 阶段报告、GO/NOT GO报告
    ├── instructions/UI-0001.v1.md           # 用户指令，每条指令一个文件
    ├── requirements/REQ-0001.v1.md          # 经主会话或按需UI澄清的需求（需求记录各项与用户原话），每次提交一个新版本
    ├── workflow/                            # 本项目采用的规则版本、模板、约定
    ├── literature/LIT-0004.v1.md            # 相关研究笔记（创建节点时的缓存），可被多个节点引用
    ├── baselines/E-0002/                    # 不属于任何假说的基线实验
    │   ├── design.v1.md
    │   └── result.v1.md
    ├── hypotheses/H-0007/                   # 每个假说节点一个目录（平铺，见下）
    │   ├── hypothesis.v1.md
    │   ├── novelty.v1.md                    # RLD 的新颖性论证，独立复核另存 reviews/
    │   ├── theory.v1.md                     # RLD 的理论论证，独立复核另存 reviews/
    │   ├── experiments/E-0031/
    │   │   ├── design.v1.md
    │   │   ├── result.v1.md                 # 冻结统计代码的输出与解读
    │   │   └── stats.v1.json                # 统计代码的结构化输出（逐seed与配对比较），可选
    │   ├── decisions/prune-after-gate.v1.md # 节点决定的理由
    │   └── notes/                           # 补充分析、讨论（经rel_describes关联）
    ├── project/discovery/                   # 增量发现：user-hypotheses.json、candidates.json（CAND-编号及 revision）
    ├── findings/                            # 研究发现（finding，08 §1.1）
    ├── lessons/                             # 运行经验（lesson，08 §1.2；front matter kind: execution_lesson）
    ├── reviews/                             # 跨模型非交互评审（review_call.py，作者 reviewer）
    │   ├── RV-0003.v1.md                    # 一次评审；同一会话的追问写 v2
    │   └── briefs/H-0007-numbers.v1.md      # RLD 写的 brief：只列路径与结构化元数据
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

各类文档都有模板，存放在 `docs/workflow/templates/`。暂时未知的内容写“未知”，不得留空，也不得编造。 Explorer 与 Analyst 提交只读建议，由 Leader 核验后按下面的作者权限登记；不另建可自批评估或决定的写入角色。廉价筛选使用最小设计，最终确认与强主张仍补齐适用论证和独立复核。

| doc_type | 作者 | 必需内容 |
|---|---|---|
| `goal` | RLD（据用户指令） | 研究问题、目标场景、发表目标、范围与排除项、所依据的用户指令ID；**`## 问题锚点`**：底线问题、必须解决的瓶颈、非目标、约束、成功条件（假说文档逐字复制，接口核对） |
| `min_setup` | RLD | 模型、数据、训练量、评测（模型与数据集写 Hugging Face Hub 正式 ID，数据集含 config 与 split）；主指标及优劣方向、是否百分比指标；其他比较指标（过程loss、显存、训练时间等）；统一seed顺序；评测类型（与协议的 eval_type 相同）及它限制的结论措辞；SOTA基线方法与来源，以及每个基线家族的合理调参机会、训练量与数据处理（不能以一个未调好的单一配置代表现有方法）；单次运行上限与筛选预算；**冻结的实验框架与统计代码**：版本、文件清单、记录的指标与曲线、配对比较方法、确定性 outcome 规则、比较门槛、保护指标和确认要求 |
| `hypothesis` | RLD | 问题锚点（与获准 goal 逐字一致）、可证伪预测、干预、匹配对照、资源上限、停止与继续条件六个 `## ` 章节；资源上限含 JSON `{nodes, walltime_s, n_seeds?}`，正数且不超授权。方法变化可为代码或科学配置；明确思想来源、代码起点、比较参照与已引用文献。候选准入绑定当前 candidate ID、revision、内容哈希与范围，文档更新不能丢掉这些边界 |
| `novelty` | RLD | 晋级与最终主张的论证材料：检索记录（查询词、来源、日期），范围不限于创建时引用的文献；最接近工作的逐项对比表（机制、适用条件、实验设定、已报告结果、差异）；结论 |
| `theory` | RLD | 晋级与最终主张的论证材料：推导或论证的逐步核对；关键假设；与实验结果是否一致；结论 |
| `literature` | RLD/Architect/Worker（限任务范围） | 由 `literature.py note` 生成：front matter 含标题、作者、年份、arXiv ID/DOI/URL、访问日期、`verification`（verified/unverified，不手改）、核验方法、缓存路径与 sha256；正文章节：出处、核心方法、实验设定与结果、与本项目的关系、最近邻差异（机制是否相同、改变了什么假设、已有结果是否覆盖本项目声明） |
| `experiment_design` | RLD/Architect/Worker（限任务范围） | 方法与消融筛选使用五个 `## ` 章节：可证伪预测、干预、匹配对照、资源上限、停止与继续条件；另列代码版本、不可变科学配置、协议/数据/切分、seed 数、有效性验收标准和原始输出位置。资源上限节为 JSON `{nodes, walltime_s, n_seeds?}`。精确最小对照先写入 `## 预声明最小对照` JSON 并由 Leader 在目标提交前批准；超范围控制另走适用审查。晋级与确认补齐主张、竞争解释和必要的论证 |
| `experiment_result` | RLD/Architect/Worker | 逐seed的主指标、其他指标、过程曲线路径、实际节点数与时长；与已绑定比较参照和SOTA的配对差值及离散度（取自冻结统计代码写出的统计文件或 `preview_evaluation` 的只读预览，`evaluate_experiment` 再与接口重算值核对；不手算）；判定及依据；局限；原始产物路径。文中每个数字在一个 ` ```evidence ` 代码块里列出来源：`[{"id", "value", "source"}]`，`source` 相对研究根目录（如 `outputs/E-0002/s42/metrics.json`）；设为现行时接口逐项核对数值以精确十进制出现在来源文件中，找不到即拒绝（STAT_MISMATCH）。来源文件用常规 JSON（`"acc": 0.9` 或紧凑的 `"acc":0.9`）或以空格分隔的文本；CSV 的 `0.1,0.2` 这类逗号紧接的数字不会被识别（防止与千位分隔混淆）。汇总数字用保留编号：`mean:<指标>`（主指标均值必填）、`sd:<指标>`、`delta:<sota\|parent>:<指标>`，计算时按写出的小数位与重算值核对；每个已导入运行的指标文件都要引用 |
| `decision` | RLD | 变更字段与前后取值；理由；依据（实验、evaluation、文档、用户指令 ID）；投入处置与科学结论分开，暂停或不再投入须有复议条件 |
| `user_instruction` | UI 或 RLD（代用户登记） | 用户原话（逐字）；理解与来源；类型（指令/偏好/问题/讨论）；生效范围；取代的旧指令 ID。主会话授权无须在 UI 重复 |
| `task_request` | RLD | 章节（接口检查）：任务与节点、问题与预测、干预与对照、范围与权限、资源与预算、验收与停止条件、交付；各章节的内容见规则第4节 |
| `task_delivery` | Architect/Worker；只读建议任务由 RLD 代记 | 章节：实际改动与版本、运行与产物、验证结果、资源观测、未完成与未知项。Explorer/Analyst 的交付保持 RLD 作者并用 about=[task_id] 绑定任务，引用真实 advisor 会话/报告与来源；不得冒充只读角色直接写库 |
| `workflow` | RLD | 规则版本、模板、项目约定 |
| `report` | RLD | 阶段总结、GO/NOT GO报告（工作规则第6、7节要求的内容） |
| `metric_spec` | RLD | JSON：`{"version": 1, "primary": <主指标>, "metrics": [...]}`，每个指标 `name`、`direction`（higher/lower）、`input_unit`（run 报告的单位，如 fraction、percentage、seconds、gib）、`canonical_unit`（比较单位，如 percentage_point）、`effect_mode`（absolute 或 relative_to_reference_mean）、`minimum_practical_gain`、`aggregation`（paired_run_mean），可选 `allowed_regression`（保护指标允许的最大退化）、`valid_range`（输入单位的合法范围；fraction 默认 [0,1]、percentage 默认 [0,100]。百分数指标收到 0–1 的比例时默认范围查不出，需要时把 valid_range 收紧到实际可能的区间）、`relative_min_denominator`（相对效应必填）；指标恰为项目的主指标与其他比较指标。设为现行时接口校验 |
| `protocol` | RLD | JSON：`{"version":1,"eval_type":real_gt/synthetic_proxy/self_supervised_proxy/simulation_only/human_eval,"pair_fields":["seed",...],"match":{必须一致的设定},"required_counts":{计数:值}}`，可选 `gate_comparison`、`min_pairs`、`require_artifact_import`、`description`。独立确认是固定要求：声明与搜索不重叠的 `confirmation_seeds`、`min_confirmation_pairs`、`max_confirmation_candidates` 及命名的确认材料。`independence_fields` 声明独立单元字段，共享独立单元不得重复计数；`repetition` 控制有界搜索复制建议。没有 screening-only GO 或关闭独立确认的配置 |
| `review` | reviewer（只经 `review_call.py`） | front matter：kind、about、dimension 与 evaluation_id（candidate_recheck）、code_ref（code_review：所读提交，提交作业时核对同一提交）、result、backend（pi/claude_code）、provider、请求与 observed 的模型、thinking、会话、brief 路径、终止原因、费用与用量、permission_denials、原始输出路径（`cache/reviews/`）；正文为 reviewer 原文与结构化 JSON。Leader 不能登记或替换 review 文档 |
| `finding` | RLD/Architect/Worker | docs/findings/；YAML front matter：kind finding、claim（事实）、scope、evidence_ids（存在的 evaluation/实验/文档）、interpretation（与 claim 分开）、limitations、status（observed/supported/contradicted/stale）、supersedes |
| `lesson` | RLD/Architect/Worker | docs/lessons/；YAML front matter：kind execution_lesson、symptom（如实写报错、OOM、ImportError、路径错误等事实）、root_cause、root_cause_status（verified/proposed/unknown）、fix（怎么修）、applicability（harness_ref、config_doc_id、平台、依赖版本等适用范围；不写则显示“范围未写明，待核对”）、counterexamples、status（proposed/observed/verified/contradicted/stale）。status verified 表示“修复已验证”，须给 `fix_verification`：failure_attempt_ref（失败的 attempt，E-…/s…@n，有日志）、criterion_doc_id（验证开始前冻结的 task_request 或 experiment_design，含 `## 检查项` JSON 块 {"checks": [{id, type, field?, expected?}]}，type 只能是 exit_status、import_valid、launch_config、read_count、artifacts_match_manifest）、run_attempt_refs（验证用的成功、已导入、valid 的 attempt）、applied_fix_ref（{kind: execution_config, field, expected} 或 {kind: code, commit}）、check_evidence_refs（[{check, run}]）。系统用固定检查器从 run 记录与产物判定，结果记为只读的 memory_basis；自填的 fix_applied、checks_passed 被忽略。根因未确定（unknown/proposed）时也可登记已验证的修复，根因状态不变。root_cause 与 fix 拒绝“永远不要用某工具”“某工具坏了”一类永久否定；全文过滤注入/扩权内容（MEMORY_REJECTED） |
| `config` | RLD（mod 代用户登记） | 项目目录 `research-tree.yaml` 的原文：开发与实验平台、资源预算、阶段1门槛、子代理模型；立项确认与每次 `/research-tree config apply` 时登记新版本 |

## 5. 身份、写入权限与证据边界

所有数据库操作经过 `tools/research_db.py`，以明确的 `<角色>/<ID>` 校验权限。会话角色只包括 `rld`、按需 `ui`、根节点 `architect`、假说 `worker`、`explorer`、`analyst`；`reviewer` 仅经独立评审包装器登记回执。未知或缺失角色不能回退成 Worker。

| 区域或操作 | 权限 |
|---|---|
| 项目、假说、分支创建与处置、任务创建与验收、研究和投入决定 | RLD |
| 根节点执行身份和会话 | RLD 用 `assign_architect(architect_id="root")`、`bind_architect_session(agent_id)`；字段为 `architect_id`、`architect_agent_id`、`architect_session_at` |
| 假说执行身份和会话 | RLD 用 `assign_worker`、`bind_worker_session`；只接受假说节点，不是根节点别名 |
| `project/`、假说正文、`novelty.*`、`theory.*`、决定与报告 | RLD |
| 共享框架、根节点 sanity、baseline 与对应实验文档 | 分配给根节点的 Architect；不接管假说任务 |
| 假说实验、运行、导入、评价和交付 | 固定的假说 Worker，限已分配任务；不接管根节点 |
| 用户指令 | 按需 UI 或 RLD 代用户记录原话；代理建议不构成授权 |
| Explorer/Analyst 建议 | 只读；Leader 登记任务进度和版本化交付并按证据验收 |
| `reviews/RV-*` | 仅 reviewer 包装器；RLD 可写中立的 `reviews/briefs/`，不能伪造或替换回执 |
| 恢复资料、findings、lessons | RLD 或相应执行 owner，按文档类型和任务范围检查 |
| 页面与摘要 | 确定性生成器只读研究记录；按需 UI 不写科学决定 |

生效文档只增加新版本，不原地改写；每次数据库写入是短事务，锁冲突只有限重试。以下保护始终适用：

- **确认与范围。** 先登记最小目标、协议、指标和预算，再由用户确认。候选准入不改变确认阶段，不能授权新目标、资源或权限；配置由用户修改，或由 Leader 按用户指示只改用户要求的项（子代理不能写），并显式应用（Leader 代为应用时登记用户原话）。
- **冻结框架。** Architect 实现训练、评测、统计与 manifest；Leader 检查后用 `update_project(harness_ref, harness_paths)` 冻结。实验代码必须包含且保持框架文件一致；换框架使依赖证据失效并需重建参照。
- **增量候选。** 候选 JSON 必须含 prediction、intervention、comparator、resource_ceiling、stop_conditions。Leader 合并实际提案，逐候选 select/gate，`create_hypothesis` 再核验当前 revision/hash 与范围。候选 A 的通过不能放行 B；没有全池报告或固定篇数文献门。
- **独立关系。** `parent_id`/typed relations 是思想来源；`code_parent_id` 与 branch `base_commit` 是代码起点；`comparator_experiment_id` 是实验比较参照；投入处置另记。思想父节点无需胜出，不允许循环，也不能把对照的相同科学方法改名作为新干预。
- **方法与主张身份。** 实验登记 `method_config` 或 `config_path`，固定代码、科学配置、数据/协议和框架的身份。执行字段如输出路径、walltime、seed 不构成新方法；科学配置变更可以构成干预。导入配置须匹配。主张变化形成新 revision，旧回执和争议裁决只有依据仍适用时才有效。
- **baseline 与复制。** 有效且匹配的 baseline seed 可先支持搜索，其余 baseline 继续。reserve、claim、提交前都检查对应参照；缺失或撤回的 seed 不能先提交后补对照。部分配对不构成完整 SOTA 或晋级。自主追加复制要求当前适用的 positive_signal、匹配身份与协议、种子上限和已授权预算；负向、不确定和过期结果不自动放行扩量。
- **运行与重试。** planned → submitted（→ running）→ succeeded/failed/cancelled；只有成功且通过有效性验收的运行支持科学结论。每次 attempt 保留原作业、结果、失败理由和实际用量；只重试允许重试的执行失败，不能撤回有效结果来挑选更好结果。查询失败和提交超时维持 unknown，核对原 submission_key，不盲目重提。
- **原始导入。** `import_run_result(run_id, attempt, manifest_path)` 校验代码、配置、seed、attempt、数据/协议、实际计数、指标单位和原始路径。相同 attempt 同文件重复导入幂等，换文件或事后改导入数值被拒绝。manifest、哈希、原始指标与单位保留；缺失 provenance 不由当前配置倒填。
- **程序计算。** `evaluate_experiment` 从有效 run 重算均值、样本 SD、配对效应、门槛和保护指标，产生 positive_signal/negative_signal/inconclusive。n=1 的 SD 为空并解释，不写成 0。调用者不提交 verdict 或权威统计数字；结果文档须引用每个已导入指标文件及可核验的汇总来源。相同输入幂等；计算中依据变化拒绝写入。
- **证据时效。** evaluation 绑定实际用到的 run/attempt、代码、科学配置、框架、协议、指标与参照。增加未使用的 baseline seed 不改旧结果；更改或撤回实际使用的 run 则使其失效。指标规范的新版本、只差 research-tree.yaml 规定字段（profile、确认设置、require_artifact_import、independence_fields、repetition）或描述的协议版本只约束之后的评估，不使已有 evaluation、方法身份、审查裁决、最小对照批准与研究发现失效，参照在同一 run 上重评也不算换参照；例外是收紧的证据规则不再接受的评估（新增 independence_fields，或新要求工件导入而评估只是记录级：PROTOCOL_CHANGED）与所比较指标的判定字段变化（方向、规范单位、效应方式、聚合、allowed_regression、valid_range、relative_min_denominator：METRIC_SPEC_CHANGED）。框架或比较协议本身（评测类型、配对字段、必须一致的设定、计数等）变化使依赖证据待重评。独立单元、单位、配对字段和 required_counts 必须可核验，重复 attempt 不增加样本数。
- **代码审查与最小对照。** 普通廉价搜索不逐次等待模型审查，但同方法 sanity、原始证据、数据/指标有效性、匹配、授权与预算仍检查。精确预声明的最小对照经 Leader 在目标提交前 `approve_minimum_controls` 批准后，只免除重复 ablation_plan；超范围实验保留适用审查。已验证的有效性缺陷不能绕过。
- **争议。** `dispute_code_review` 保留原阻塞回执、具体问题和证据；独立 recheck 后 Leader 用 `adjudicate_code_review` 记录 upheld/overturned/fixed。真实缺陷不能 overturned 豁免。fixed 需要新方法身份、实际修复证据与独立 clear，只放行精确绑定的新实验；旧方法仍阻塞。换配置、节点、后代提交或沿用缺陷源码不能洗掉未解决问题。
- **独立确认。** Leader 在充分搜索复制与关键控制后 `freeze_candidate` 冻结方法、主张、搜索依据和参照，再 `create_confirmation_batch` 固定名单与未使用的声明材料。Architect 运行冻结参照的确认 baseline，Worker 运行对应候选；身份、批次、比较和材料端到端绑定。确认材料从首次提交计入使用史，不因撤回、改名或重启清除，后续经反馈修改的方法须用另一份预声明材料或保持未确认。
- **最终复核与 GO。** `get_eligibility`/`go_candidates` 从当前 evaluation 计算，检查足量配对、门槛、保护指标、独立确认、五维独立复核及未决问题；不读缓存标签。numbers/protocol 绑定最终确认 evaluation，其余维度也须与当前方法/主张/证据依据一致。Leader 的 GO 在写事务中重查，历史 GO 不被后来的失效改写，也不自动重开研究。
- **未决问题。** 有 OPEN obligation 不能 GO；在 API 允许的有限范围内，reviewer 不可用的代码审查豁免或 obligation 豁免均须明确用户指令与对应决定记录，不能豁免已验证的有效性缺陷；新的整体 pass 不自动关闭旧问题，必须按相应证据解决流程处理。新颖性/理论整维豁免只按冻结协议与现行主张的明确适用性检查，不能把未知问题标作不适用。
- **投入与 NOT GO。** 科学 outcome、节点生命周期、active/paused/retired 处置和项目 GO/NOT GO 分开。NOT GO 要求没有仍在投入的节点，Leader 无值得验证的新方向，报告覆盖未探索、工程失败、不确定、重复方向、明确反证与投入价值判断；预算不足或工程失败本身不构成 NOT GO。
- **预算与防重复。** reserve → claim → 使用 submission_key 提交 → attach_job → 以真实调度用量 settle。预留须等于登记的总 node-seconds 并符合组合资源边界；开销预先声明。search/confirmation/repair 分池按实验依据固定，同 key 不能换 run、资源形状、池或平台；未知请求保留预留并对账。实际失败费用也入账，超额暂停准入，不静默取消作业或放宽预算。
- **任务与恢复。** 请求和交付须具备规定章节；验收 `update_task(status=accepted, evidence_ids)` 引用真实依据，验收者不是执行者。`resume_package` 返回角色限定的 actor 和 first_unaccepted_task，沿用原会话与作业身份，不因 agent 一轮结束就宣告实验结束。
- **指标变更。** 主指标的收益门槛和统一种子在开始实验后冻结；其他允许的协议/规范变更必须引用当前用户指令，只使按上面“证据时效”不再适用的证据失效。改单位必须与保留的原始单位一致且等价换算，不重新解释已导入值。
- **清理与结项。** evaluation 登记后由实验 owner 按项目清理脚本清理非证据产物；保留日志、曲线、manifest、导入证据和声明仍需复用的产物，记录释放量与失败项。清理不是科学结论。GO/NOT GO/停止后不接受新的研究工作；重开须新的用户指令和范围记录。

数据库位于共享文件系统时，跨主机锁是否有效取决于挂载方式。计算作业不直接打开数据库，只写输出目录；由固定执行 owner 导入。长作业不能持有数据库锁，文件锁也不替代角色或单 writer 检查。

## 6. 节点分支、worktree与git提交

代码和文档分属两个仓库，提交规则不同：

| 仓库 | 谁提交 | 说明 |
|---|---|---|
| 文档仓库 `research/<project-id>/` | 只有RLD | 文档不开分支。各agent直接在共享路径写自己负责的文件（第5节），写入后立即对所有人可见；RLD在批次节点统一提交。 |
| 代码仓库的节点分支 | 该分支当前的 Architect 或 Worker owner | 只在自己的worktree内提交自己的分支，以保持并行度。 |
| 代码仓库的 `main` 等共享分支 | 只有RLD | 合并由RLD决定并执行。 |

**分支与worktree的生命周期：**

1. **创建。** 节点第一次需要写代码时，由RLD创建分支 `node/<节点ID>` 及其worktree，并登记 `branch` 记录。按登记的 `code_parent_id` 选择代码来源并固定 `base_commit`；思想 `parent_id` 不隐含代码起点。只做新颖性或理论验证、不写代码的节点不建分支。
2. **开发。** 同一时刻只有一个已绑定的执行 owner 可以提交。实验提交时冻结的提交打标签 `exp/<实验ID>`，写进 `experiment.code_ref`。这样之后即使删除分支，实验所用代码仍可追溯。
3. **交还。** 本轮分支任务完成并交还时，执行 owner 确认worktree内没有未提交的改动，在交付文档中列出最后提交和主要改动，把分支状态改为 `returned`，owner交还RLD。
4. **处置。** RLD作出决定并写入决定记录，然后执行以下一种处置。三种处置都要移除worktree；只有提交在分支上的代码会保留，worktree里未提交的内容会丢失，所以交还时必须先全部提交。
   - **合并（merged）**：例如GO候选或可复用的基础设施，合并目标由RLD决定。
   - **保留（kept）**：例如可拓展节点的分支，作为子节点的基准。
   - **删除（deleted）**：例如可消灭节点。删除前确认所有实验提交都已打 `exp/` 标签。

代码来源若仍被待建分支使用，按已登记依赖保留到所需 checkout 建立；思想祖先与代码依赖分开，不因思想父节点未胜出而禁止变体。

## 7. 消息格式

agent之间的消息是一行紧凑的JSON，只包含简短说明和引用，不复制文档内容。格式由 `message.schema.json` 定义：

```json
{"v":1,"id":"worker--w3-0042","ts":"2026-10-03T10:21:00Z","project":"P-online-polora","from":"worker/w3","to":"rld/main","type":"delivery","re":"rld--main-0040","about":["T-0088","E-0031"],"text":"T-0088完成：E-0031得到正向信号；当前证据见交付。","docs":["hypotheses/H-0007/experiments/E-0031/result.v1.md","tasks/T-0088/delivery.v1.md"],"need":"ack"}
```

| 字段 | 含义 |
|---|---|
| `id` | `<角色>--<发送者ID>-<序号>`，由发送工具在角色限定日志锁内分配 |
| `from` / `to` | `<角色>/<agent ID>`，会话角色为 ui、rld、architect、worker、explorer、analyst；reviewer 仅供评审包装器 |
| `type` | instruction（UI→RLD，已登记的用户指令）、task（RLD→被委派者）、delivery（任务交付）、question、reply、confirm_request（RLD→UI，需要用户决定）、ack（仅确认收到）、alert（故障、阻塞、完整性问题） |
| `re` | 所回复消息的ID；reply和ack必填 |
| `about` | 相关的数据库实体ID（项目、节点、实验、分支、决定、任务），最多5个；指令和文献等文档放在 `docs` |
| `text` | 简短说明，最多200字 |
| `docs` | 相对 `docs/` 的文档路径，必须带版本号且已登记，最多5个；instruction、task、delivery、confirm_request必填 |
| `need` | 期望对方的回应：none、ack、answer、decision；decision只用于confirm_request |

规则：

- **序列化与大小。** 用UTF-8紧凑格式（`ensure_ascii=False`、无空格），整行不超过1000字节：消息只是短说明加引用，细节一律写进文档。JSON Schema无法检查字节数，由发送工具检查。角色限定的地址与编号不可省略或回退。
- **先记录后发送。** 发送者先把完全相同的一行追加到 `messages/<角色>--<发送者ID>.jsonl`（位于文档仓库，每个发送者一个文件，避免并发追加冲突），再交给收件方。消息丢失时以日志为准对账。
- **内容在文档里。** 凡是会影响决定的信息都必须在被引用的文档里；不带 `docs` 的消息只用于确认、提问、催办和告警。接收方据此行动前，必须读取被引用的文档。
- **用户指令先登记。** 用户的话由主会话 RLD 或按需 UI 先登记为 `user_instruction` 文档，再发送引用该文档的instruction消息；不得在消息里转述后直接执行。
- **不回确认的确认。** 收到ack不再回复，避免两个session相互唤醒。

### 发送工具

`tools/send_message.py` 依次完成：补全 `v`、`id`、`ts`、`project` → 按schema校验 → 检查引用（`about` 中的实体在库中存在；`docs` 已登记、未被取代且文件存在；`re` 在消息日志中）→ 在发送者日志锁内分配序号、检查1000字节上限并追加日志 → 打印这一行。任何检查失败都不写日志（退出码2）。打印出的一行由发送者用宿主的手段交给收件方：Claude Code中，RLD给worker的消息用SendMessage发送；UI与RLD之间的消息由插件调用本工具并直接投递（UI的发件箱动作，以及RLD的 `post_to_ui`）。需要再次交付同一条消息时用 `--resend <id>` 打印日志中的原行，不另编新消息。

```bash
.venv/bin/python tools/send_message.py --root research/P-xxx \
  --from worker/w3 --to rld/main --type delivery --re rld--main-0040 \
  --text "T-0088完成：E-0031得到正向信号，待进一步确认。" --about T-0088 E-0031 \
  --docs tasks/T-0088/delivery.v1.md
```

可收发消息的身份登记在 `research/<project-id>/agents.json`（地址列表，由 `/research-tree init` 写入）：

```json
["ui/ui", "rld/main", "architect/root", "explorer/main", "analyst/main"]
```

节点worker以节点命名（`worker/h0007`），无需登记即可发送；收件人必须已登记。

## 8. 契约维护

文档与 `research_tree.sql`、配置 schema、消息 schema、数据库 API 和两端适配器保持一致。更新公共角色、字段、消息或准入时同时更新对应回归，不把历史实施计划当作当前 API 文档。只读页面、摘要、恢复与消息路径同样检查版本；版本拒绝不得触发旧项目的静默重写。
