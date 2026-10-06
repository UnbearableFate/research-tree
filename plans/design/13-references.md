---
title: "附录：参考文献、代码定位与 ARIS 移植索引"
stage: "附录"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §20；对照文档 §4–5"
language: "zh-CN"
---

# 13 附录：参考文献、代码定位与 ARIS 移植索引

## 1. 参考文献与参考项目

参考范围核验日期为 **2026-10-05**。论文结果均为作者报告，本文未复现外部系统；公开仓库的当前功能也不等同于对应论文版本的全部实现。链接采用原始论文页、官方项目页或仓库，不依赖聊天界面的引用控件。

### 1.1 直接参考研究与项目

#### R01. Auto-RecSys

**Ming Li et al. — Auto-RecSys: Harnessing Autonomous Research Agents for Industry-Scale Recommender System. 2026.**

[论文原始入口][R01] · [PDF 入口](https://arxiv.org/pdf/2609.10922)

参考点：异步实验、持久化恢复、自然语言推理与确定性操作分离、研究想法与运行经验的双回路。对应 D6、D7。

核验范围：arXiv 搜索记录与摘要；直接正文抓取失败。未确认可供审计的官方实现，不将它归类为“已检查开源代码”的项目。

#### R02. OR-Agent

**Qi Liu, Ruochen Hao, Can Li, Wanjing Ma — OR-Agent: Bridging Evolutionary Search and Structured Research for Automated Algorithm Discovery. 2026.**

[论文原始入口][R02] · [公开代码仓库][R02C]

参考点：树式假说组织、演化候选与分层反思。对应 D5、D6。本文不因其使用树搜索就认定优于简单循环。

核验范围：原始 arXiv 页面本次返回 v3 与官方仓库说明。搜索中更高版本的信息未完成原始版本页复核；不据此断言具体最新遍历实现。

#### R03. ScientistOne / Science One Framework

**Rui Meng et al. — ScientistOne: Towards Human-Level Autonomous Research via Chain-of-Evidence. 2026.**

[论文][R03] · [项目主页][R03P] · [Google Research 官方介绍][R03B]

参考点：声明与证据绑定，以及数字、协议、引用、方法—代码的定向核查。对应 D1、D2、D8。本文借鉴可核查性设计，不将其审计通过等同于普适科学正确性，也未假定完整实现已开放。

#### R04. AutoResearchClaw

**Jiaqi Liu et al. — AutoResearchClaw: Self-Reinforcing Autonomous Research with Human-AI Collaboration. 2026.**

[论文][R04] · [官方代码仓库][R04C]

参考点：执行修复、结果验证、跨运行经验和有针对性的人机协作。对应 D6、D8。VerifiedRegistry 的名称和相关报告机制见仓库说明；具体可靠性仍需实际测试，不能照搬宣传性保证。

#### R05. DeepScientist

**Yixuan Weng et al. — DeepScientist: Advancing Frontier-Pushing Scientific Findings Progressively. 2025.**

[论文][R05] · [公开代码仓库][R05C]

参考点：累积 Findings Memory、分层实验验证与长期研究工作区。对应 D3、D6。2025 论文与 2026 仓库的发展阶段不同，本文区分论文机制与当前项目说明，不将其大规模运行投入直接作为本项目预算建议。

#### R06. Karpathy autoresearch

**Andrej Karpathy — autoresearch. 2026，开源项目。**

[代码仓库与 README][R06]

参考点：单一可修改训练文件、固定训练时间、修改—训练—评估循环。用作第 16 节的低开销基线；不将其特定硬件与时间预算套用到所有研究任务。

#### R07. The AI Scientist-v2

**Yutaro Yamada et al. — The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search. 2025.**

[论文][R07] · [官方代码仓库][R07C]

参考点：agentic tree search、实验配置与可视化研究轨迹。对应 D5 与整体工作流基线。完整论文生成能力不作为本次改造目标。

#### R08. 科学探索多样性

**Yixuan Tang, Yi Yang — AI Research Agents Narrow Scientific Exploration. 2026.**

[论文][R08]

参考点：其研究范围内，AI 生成想法相对集中于起始文献附近；支持评测机制多样性与局部重复，而不只统计节点数。不能据此直接断言 research-tree 已有同样表现。

### 1.2 统计与资源分配基础

#### R09. 模型选择偏差

**Gavin C. Cawley, Nicola L. C. Talbot — On Over-fitting in Model Selection and Subsequent Selection Bias in Performance Evaluation. Journal of Machine Learning Research, 11:2079–2107, 2010.**

[JMLR 原文页面][R09]

参考点：在有限样本上选择最佳结果也可能过拟合评价准则。对应搜索/确认分离、确认反馈使用史及固定评测口径。

#### R10. Hyperband

**Lisha Li et al. — Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization. JMLR, 2018；arXiv 首版 2016.**

[论文][R10]

参考点：分层资源分配与提前停止。本文仅借鉴其成本分配思想，不声称其理论保证自动覆盖开放式方法探索或跨模型规模的排名稳定性。

#### R11. 顺序推断

**Steven R. Howard, Aaditya Ramdas, Jon McAuliffe, Jasjeet Sekhon — Time-uniform, nonparametric, nonasymptotic confidence sequences. The Annals of Statistics, 49(2):1055–1080, 2021.**

[论文][R11] · [DOI](https://doi.org/10.1214/20-AOS1991)

参考点：需要在反复观察和自适应停止下保持推断保证时，可研究适用的 confidence sequence。必须满足对应假设；不是增加几个 seed 就自动获得的性质。

### 1.3 本仓库代码与规则定位

以下源码链接固定到审阅提交，便于实施时复核；它们不是执行结果。

| 编号 | 文件或区域 | 相关检查 |
|---|---|---|
| S01 | [仓库 README][S01] | 定位、阶段、安装与工作流 |
| S02 | [基准提交][S02] | 审阅版本 |
| S03 | [research_db.py 全文][S03] | 数据权限、协议、判定、状态与预算 |
| S04 | [工作规则][S04] | Stage 1、角色、恢复、GO/NOT GO、清理 |
| S05 | [research_tree.sql][S05] | 结构规格、实体、字段与关系 |
| S06 | [数据库测试][S06] | Fixture、finish_runs、evaluate 与状态测试 |
| S07 | [codex_runtime.py][S07] | worker/UI 生命周期、消息与控制 |
| S08 | [codex_agent.py][S08] | supervisor 与宿主运行 |
| S09 | [Claude register.tsx][S09] | 宿主工具、guards、UI 和状态展示 |
| S10 | [文档库规则][S10] | 版本、正文/索引分离与恢复材料 |
| S11 | [统计判定区域：L1030–L1170][S11] | record_verdict、配对检查、判定规则 |
| S12 | [节点与项目决策区域：L780–L858][S12] | no_gain 剪枝、GO/NOT GO 条件 |
| S13 | [查询及辅助函数区域：L1630–L1799][S13] | go_candidates、_is_go_candidate、用量统计 |
| S14 | [实验创建与预算区域：L858–L955][S14] | _check_usage_alert、_screen_seeds、extend_seeds |

### 1.4 建议阅读顺序

先读本仓库的 S11、S12、S13，确认 P0 问题边界；再读 R03 的证据框架与 R06 的极简循环，明确“可靠但不臃肿”的目标。随后根据当前瓶颈阅读 R01/R05 的经验复用或 R02/R07 的搜索设计。统计策略由 R09–R11 提供背景，不需要一次实现所有高级方法。


## 结论

research-tree 当前已经具备可用的研究管理骨架。下一步应优先增强“实验事实怎样约束结论”，而不是扩张“自动研究”表面的功能范围。

**第一优先级：从输入重算统计值；把 GO 资格绑定到当前有效证据。**

**第二优先级：允许不确定；分离科学证据与投入处置；为少数候选保留独立确认预算。**

**第三优先级：用确定性执行减少重复与超支，用有适用边界的经验改善后续选择，再通过完整研究对照证明收益。**

本文完成的是设计和来源整理，不包含代码修改、测试运行或任何新的实验授权。

<!-- 原始来源链接：使用标准 Markdown 引用式链接，便于 GitHub、VS Code 和普通 Markdown 阅读器使用。 -->

[S01]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/README.md
[S02]: https://github.com/UnbearableFate/research-tree/commit/48b3841d97275b2e9ad010d91d261acc9c7c4f5c
[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
[S04]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/rules/research-tree-rules.md
[S05]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/research_tree.sql
[S06]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tests/test_research_db.py
[S07]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_runtime.py
[S08]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_agent.py
[S09]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/claude-mod/research-tree/hooks/register.tsx
[S10]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/doc_library.md
[S11]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1030-L1170
[S12]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L780-L858
[S13]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1630-L1799
[S14]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L858-L955
[R01]: https://arxiv.org/abs/2609.10922
[R02]: https://arxiv.org/abs/2602.13769
[R02C]: https://github.com/qiliuchn/OR-Agent
[R03]: https://arxiv.org/abs/2605.26340
[R03P]: https://scientist-one.github.io/
[R03B]: https://research.google/blog/science-one-framework-a-verifiable-autonomous-research-framework-via-chain-of-evidence/
[R04]: https://arxiv.org/abs/2605.20025
[R04C]: https://github.com/aiming-lab/AutoResearchClaw
[R05]: https://arxiv.org/abs/2509.26603
[R05C]: https://github.com/ResearAI/DeepScientist
[R06]: https://github.com/karpathy/autoresearch
[R07]: https://arxiv.org/abs/2504.08066
[R07C]: https://github.com/SakanaAI/AI-Scientist-v2
[R08]: https://arxiv.org/abs/2605.27905
[R09]: https://jmlr.org/papers/v11/cawley10a.html
[R10]: https://arxiv.org/abs/1603.06560
[R11]: https://arxiv.org/abs/1810.08240

## 2. ARIS 移植索引

路径相对 `/work/xg24i002/x10041/Auto-claude-code-research-in-sleep` @ 3b19a22。ARIS 约 95% 的行为是 SKILL.md 提示词；确定性代码集中在 `tools/`、`skills/experiment-queue/scripts/`、`mcp-servers/`。它没有数据库，预算与重试全部是提示词常量；多处 SKILL.md 超前于代码（队列磁盘满处理、monitor 读 `queue_state.json`、环境 spec-hash 账本、meta-apply 完整性校验均未实现）。移植以其代码与测试为准。

### 2.1 直接移植的确定性代码（改接口，不改逻辑）

| ARIS 来源 | 行数 | 做什么 | 放到哪里 / 怎么改 | 优先级 | 对应批次 |
|---|---|---|---|---|---|
| `tools/evidence_check.py` | 212 | 批量检查 `(claim_id, value, source_path)`：值是否精确出现在文件中；状态 verified / value_not_found / path_missing / unparseable；失败即拒绝 | 新增 `shared/research-tree/tools/evidence.py` 的一部分；`record_verdict`、`set_document_current`（experiment_result/report 类型）前调用；与 D1 的记录级重算互补：重算管汇总与 run 一致，这个管文档与文件一致 | P0 | M1 |
| `tools/iteration_log.py` | 143 | 每轮记录 `new_findings` 数；连续 2 轮为 0 → `structural`，4 轮 → `human` | 改为数据库字段：每个节点/子树一个计数，`decide()` 时由 Leader 填 `new_findings`；`structural` 时拒绝再创建与已记录 `direction` 相同的子节点，`human` 时触发 `post_to_ui` 上报 | P1 | M2 |
| `tools/forensics_gate.py` 的账本部分 | ~300 | 只追加的未决问题账本：指纹 = 来源 + 模式 + 证据片段；严重度只升不降；已解决项复现则重开；从报告中消失标 `UNRESOLVED_DISAPPEARANCE`；关闭需 `resolve`（类型化修复 + 证据文件哈希）或人工 `waive` | 新增 `obligation` 实体（或 decision 的子类型）；复核任务、协议不匹配、`STAT_MISMATCH` 等都写成一条；`go` 决定前要求该节点无 OPEN 项 | P1 | M4 |
| `tools/run_state.py` 的 `accept` / `resume_point` | ~150 | `done` ≠ `accepted`；accept 必须带 `verdict_id` 和不同于执行者的 reviewer（允许 `deterministic:<tool>`）；恢复点 = 第一个未 accepted 的阶段 | 加到 `update_task(status=accepted)`：必须引用 Evaluation/decision ID；`accepted_by` 不能等于任务 owner（Leader 验收 worker 即满足）。`resume_package` 增加"第一个未验收任务"字段 | P1 | M2 |
| `tools/verify_papers.py` + `arxiv_fetch.py` + `semantic_scholar_fetch.py` + `openalex_fetch.py` | 690 + 335 + 437 + 326 | 检索、下载、三层存在性核验（arXiv → CrossRef → S2 模糊标题），带缓存与限速 | 新增 `tools/literature.py`：登记 literature 文档时必须通过存在性核验，原文缓存进 `cache/literature/`；作为 D6 10.7"最近邻差异"记录的前置。网络访问按平台规则在登录节点或允许的地方运行 | P1 | M5 |
| `tools/capture_filter.py` | 126 | 拒绝运维噪声进入记忆 | `docs/lessons/` 登记前过滤（D6 10.3） | P2 | M5 |
| `tools/threat_scan.py` | 222 | 对将注入上下文的文本做提示注入/外泄扫描 | 文献原文、外部仓库说明、经验条目回灌 Leader 前扫描（D6 10.6 已要求"研究材料不是控制指令"） | P2 | M5 |

### 2.2 借鉴机制、按本项目数据模型重写

| ARIS 机制 | 来源 | 本项目的做法 |
|---|---|---|
| **Type-A / Type-B 门分类** | `skills/shared-references/acceptance-gate.md` | 对 `decide`、`update_task`、`record_verdict`、项目 GO 的每个条件标注：A（代码可判：产物存在、退出码、预算计数、`passes_gate`）由 `research_db` 判；B（"声明成立""方法新颖"）必须有独立证据路径。与设计文档 4.2 责任矩阵合并成一张表写进规则。Type-B 判定由 **pi 非交互评审**给出（`pi -p --mode json`，默认要求 provider 与 Leader 不同），仍保持"新上下文 + 只给文件路径 + 确定性校验 + 失败即 `REVIEW_UNAVAILABLE`"；不设常驻 reviewer。详见 09 |
| **"loop 可以 DRIVE，不能 ACQUIT"** | `external-cadence.md` | 写入规则 §7，作为对任何站点唤醒技能的要求：唤醒只能核对作业、导入结果、重新进入 Leader；不能重跑判定、不能自动 accept。D7 11.9 已有雏形，补这条禁令 |
| **reviewer 只拿路径，不拿摘要；判定线程每次全新** | `reviewer-independence.md`、`experiment-audit`、`paper-claim-audit` | D8 的定向复核任务：任务请求只列代码版本、协议、Evaluation ID 和原始文件路径，禁止附 worker 的总结。复核 worker 使用新会话 |
| **实验审计清单 A–F 与评测类型标签** | `skills/experiment-audit/SKILL.md`、`experiment-integrity.md` | 把"GT 来源、自归一化分数、结果文件存在且数字一致、死指标代码、措辞超出证据、评测类型（real_gt / synthetic_proxy / …）"作为复核文档的必需章节；评测类型写入 min_setup 文档并限制结论措辞 |
| **result-to-claim 的三分支路由** | `skills/result-to-claim/SKILL.md` | yes / partial / no 对应 D4 的 outcome：`positive_signal` → 允许派生；`inconclusive` → 补充实验而非剪枝；`negative_signal` → 剪枝并写 finding。本项目已有 D4，这里只借它"partial 必须列出缺什么证据、下一步实验是什么"的输出字段 |
| **失败优先的上下文包** | `tools/research_wiki.py` `rebuild_query_pack` | 在 `resume_package` 之外新增 `context_pack(role, node)`：固定上限（如 8000 字），顺序为目标与约束 → 未决 obligation → **已剪枝节点与 verified lesson** → 当前 Evaluation → 最近关系边。确定性生成，不调用模型 |
| **类型化关系边** | `research_wiki.py`：supports / invalidates / tested_by / refutes / depends_on | 与设计文档 9.1 的 `combines / repairs / tests_assumption / competes / shares_control` 合并，补 `supports`、`invalidates`（Evaluation → hypothesis） |
| **幂等配置去重** | `dse-loop`："相同配置永不重跑" | 实验创建时对 (code_ref, 配置快照哈希, seed) 去重，返回已有实验而不是新建；与 D7 `submission_key` 一致 |
| **失败预算** | `experiment-bridge`：2 次补丁 + 2 次重写；同样方式失败两次即归咎计划/环境并上报 | 对应设计文档 9.5 `max_repairs_per_root_cause`；把"同样方式失败两次 → 上报"写成可检查的计数 |
| **成本预估前置** | `serverless-modal` / `vast-gpu`：每次启动前输出成本估算块 | `create_experiment` 已检查上限；增加必填 `estimated_node_h`，与 D7 记账部分对接；实际 > 2× 预估时写 attention。平台无关 |
| **通知桥** | `mcp-servers/feishu-bridge/server.py`：`/send` + `/poll` + 超时回退 | 做成通用 webhook 适配（配置 `notify.url`），只用于 `confirm_request` 和 `alert`；超时**不**视为同意（规则 §1 已定），只记录未答复 |
| **工具事件日志** | `templates/claude-hooks/meta_logging.json` + `tools/meta_opt/log_event.sh` | 两端 hook 已能看到 tool.call；追加 `logs/tool_events.jsonl`（技能/工具名、成功失败、耗时）。只记录，不做 meta-optimize |

### 2.3 借鉴文本与模板

| ARIS 来源 | 用途 |
|---|---|
| `templates/EXPERIMENT_PLAN_TEMPLATE.md` | 假说文档（`hypothesis` 类型）必需章节：claim、最小说服性证据、成功判据、失败时的解释、成本估计、优先级（MUST/NICE）、停止条件。与规则 §4 的任务请求表合并，由 `TASK_SECTIONS` 同样方式检查 |
| `templates/EXPERIMENT_LOG_TEMPLATE.md` | 结果文档必需章节：设定、逐 seed 表、"支持 claim？yes/partial/no"、复现命令、run/attempt/job ID |
| `templates/FINDINGS_TEMPLATE.md` | 研究发现与工程发现分开——与 D6 的 `docs/findings/` 与 `docs/lessons/` 一致，可直接作为模板正文 |
| `docs/SESSION_RECOVERY_GUIDE.md` 的读取顺序 | Leader/worker 恢复时的固定读取顺序：状态 → 当前合同/任务 → findings/lessons → 核对在途作业。写进 worker/planning 提示词 |
| `experiment-plan` 的里程碑顺序 | sanity → baseline → main → ablation，每级有 stop/go 门。本项目根节点即 baseline；"sanity（最小规模能跑通）"可作为每个节点实验前的必经 attempt，不占 seed 计数 |

### 2.4 本包新增引用的 ARIS 材料（02、03、09）

| 来源 | 用于 |
|---|---|
| `skills/idea-discovery/SKILL.md`、`tools/idea_discovery_gate.py`、`tools/run_state.py` | 02 的阶段编排、证据门与可恢复状态 |
| `skills/idea-creator/SKILL.md`、`shared-references/fan-out-pattern.md` | 02 的 lens 生成、机械去重、客观可行性门、triage |
| `skills/novelty-check/SKILL.md`（VERDICT LIMITS 原文块） | 02 / 09 的查新 schema 与正向判定定义 |
| `skills/research-review/SKILL.md`、`shared-references/reviewer-independence.md` | 09 的 brief 规则（只给路径） |
| `skills/research-refine/SKILL.md` | 03 §2–3 问题锚点、技术缺口、路线比较、方法具体化 |
| `skills/experiment-plan/SKILL.md`、`templates/EXPERIMENT_PLAN_TEMPLATE.md` | 03 §4、§6 claim map、实验块、里程碑 |
| `skills/ablation-planner/SKILL.md` | 03 §7 |
| `skills/experiment-bridge/SKILL.md` | 03 §8 代码审查、sanity、失败预算、2× 超时 |
| `skills/result-to-claim/SKILL.md`、`tools/evidence_check.py` | 03 §9、05 §2.4、06 §7 |
| `shared-references/experiment-integrity.md`、`skills/experiment-audit/SKILL.md` | 04 §6、07 §2.1 |
| `shared-references/acceptance-gate.md`、`external-cadence.md` | 06 §1 |
| `tools/iteration_log.py`、`tools/forensics_gate.py` | 06 §5–6 |
| `tools/research_wiki.py`（`rebuild_query_pack`）、`capture_filter.py`、`threat_scan.py` | 08 |
| `templates/RESEARCH_BRIEF_TEMPLATE.md`、`RESEARCH_CONTRACT_TEMPLATE.md` | 01 §2、08 §3 |

## 3. 不建议移植的部分

| 内容 | 原因 |
|---|---|
| 论文/海报/幻灯片/专利/rebuttal/resubmit 全部技能 | 超出阶段 1 范围；设计文档 18.2 明确不做 |
| `idea-discovery` 链路中的 pilot 实验、research-wiki 写回、Feishu、HTML 渲染 | 链路本身**移植**（见 02）：用户给的假说作为种子，与新发现的候选一起查新与评审；pilot 即节点筛选实验，由现有树流程承担 |
| 多 reviewer 后端路由（`auto-review-loop` 1137 行、codex/gemini/claude/llm-chat/minimax/grok MCP） | 复杂度主要来自后端切换；本项目只用一个后端：`pi` 非交互执行，由 `pi_review.py` 包装（09），`--model provider/model` 即可切换模型 |
| `research-wiki` 整体、`CLAUDE.md` Pipeline Status、`research_contract.md` | 它们是为了从 Markdown 重建上下文；本项目有数据库与版本化文档，只借其 query_pack 与边类型 |
| `aris-monitor` | macOS Tkinter，读 Claude 会话文件，不监控实验 |
| `queue_manager.py`、`watchdog.py`、Vast.ai / Modal / screen 启动、任何调度器适配 | 执行层有意留给 `platform.skills` 的站点技能；插件面向大众，不能内置某个调度器或守护进程。`queue_manager.py` 的"完成以产物存在为准""OOM 有限重试""上游失败阻塞下游"可作为写站点技能时的参考，但不进插件 |
| `meta-optimize` / `meta-apply` | 需要跨项目日志积累且修改技能文本；本项目规则改动走人工评审 |
| 安装脚本、Copilot/Antigravity/Trae 适配、`provenance.py` 模型族判断 | 与本项目打包方式和角色模型无关 |
| 提示词层面的预算常量 | 本项目已由代码执行；只借数值作为配置默认值 |

<!-- 引用链接 -->

[R01]: https://arxiv.org/abs/2609.10922
[R02]: https://arxiv.org/abs/2602.13769
[R02C]: https://github.com/qiliuchn/OR-Agent
[R03]: https://arxiv.org/abs/2605.26340
[R03B]: https://research.google/blog/science-one-framework-a-verifiable-autonomous-research-framework-via-chain-of-evidence/
[R03P]: https://scientist-one.github.io/
[R04]: https://arxiv.org/abs/2605.20025
[R04C]: https://github.com/aiming-lab/AutoResearchClaw
[R05]: https://arxiv.org/abs/2509.26603
[R05C]: https://github.com/ResearAI/DeepScientist
[R06]: https://github.com/karpathy/autoresearch
[R07]: https://arxiv.org/abs/2504.08066
[R07C]: https://github.com/SakanaAI/AI-Scientist-v2
[R08]: https://arxiv.org/abs/2605.27905
[R09]: https://jmlr.org/papers/v11/cawley10a.html
[R10]: https://arxiv.org/abs/1603.06560
[R11]: https://arxiv.org/abs/1810.08240
[S01]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/README.md
[S02]: https://github.com/UnbearableFate/research-tree/commit/48b3841d97275b2e9ad010d91d261acc9c7c4f5c
[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
[S04]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/rules/research-tree-rules.md
[S05]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/research_tree.sql
[S06]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tests/test_research_db.py
[S07]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_runtime.py
[S08]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_agent.py
[S09]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/claude-mod/research-tree/hooks/register.tsx
[S10]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/doc_library.md
[S11]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1030-L1170
[S12]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L780-L858
[S13]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1630-L1799
[S14]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L858-L955
