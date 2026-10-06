---
title: "现状评估、问题清单与目标架构"
stage: "前置"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §1–4；对照文档 §1–3.2"
language: "zh-CN"
---

# 00 现状评估、问题清单与目标架构

本文是整个设计包的前置：审阅基准、证据等级、不变边界，当前实现的评估与优先问题，与 ARIS 及相关研究项目的对照结论，以及目标架构与责任矩阵。各阶段文件引用这里的问题编号 F01–F08。

## 1. 范围、证据等级与设计边界

### 1.1 审阅基准

目标仓库为 [UnbearableFate/research-tree][S01]，基准提交为 [`48b3841d97275b2e9ad010d91d261acc9c7c4f5c`][S02]。主要检查范围包括：

| 范围 | 对应文件 |
|---|---|
| 科研规则与 Stage 1 范围 | `shared/research-tree/rules/research-tree-rules.md` |
| 数据模型 | `shared/research-tree/schema/research_tree.sql` |
| 写入约束、判定、状态、预算 | `shared/research-tree/tools/research_db.py` |
| 数据库测试与夹具 | `shared/research-tree/tests/test_research_db.py` |
| 文档、版本与恢复材料约定 | `shared/research-tree/schema/doc_library.md` |
| Codex 会话生命周期与执行 | `codex-plugin/research-tree/tools/codex_runtime.py`、`codex_agent.py` |
| Claude 适配层 | `claude-mod/research-tree/hooks/register.tsx` |

文件与具体代码区域的固定版本链接列在第 20 节。本次没有对所有路径逐行审计，也没有验证平台特定的锁、信号、队列和调度行为。

### 1.2 四种证据等级

全文区分以下四类陈述：

| 等级 | 含义 | 可据此判断什么 |
|---|---|---|
| 源码事实 | 在固定提交的相应函数、模型或测试中可直接看到 | 实现的结构及局部检查边界 |
| 静态推断 | 根据已读路径推导的可能行为 | 需要回归测试验证的风险，不能称为已复现故障 |
| 外部作者陈述 | 论文、官方项目说明中的设计或实验报告 | 可作为参考；不是对 research-tree 的直接效果证明 |
| 本文设计建议 | 根据目标与风险提出的新机制 | 需要实现、测试和对照评测；没有预先保证的收益 |

### 1.3 保持不变的边界

保持 Stage 1 的低成本方法筛选定位；大规模训练、额外数据权限、新模型规模和 Stage 2 预算仍由用户决定。保留唯一 Leader、节点 worker 的稳定身份、分支/worktree、现有文档库与 LatticeDB。保留用户对停止、暂停、预算和权限变更的决定权。[S01]、[S04]、[S05]

不引入常驻审稿委员会；不把每次实验交付变成多轮签字；不要求每个失败分支都先解释到论文级别。确定性检查自动执行，模型只处理确实需要判断的问题。

### 1.4 安全边界

本文设计首先防止误填、状态漂移、证据错配、重复提交和错误科研结论。它不是针对拥有同一操作系统完整写权限的恶意进程的安全证明。

只有提示词、Git 文件比对或同一用户下的“只读约定”，不能保证 agent 无法改写结果或偷看评测数据。需要更强隔离的部署，应另行采用文件权限、独立评测进程或受限执行环境；这属于部署配置，不要求本轮建设新的容器平台。

## 2. 当前实现评估与问题清单

### 2.1 值得保留的部分

当前实现已经把“研究判断”和“程序可验证条件”分开：Leader 决定研究方向，数据库接口管理权限、状态转换、框架冻结、seed 约束和版本化记录。作业执行状态、有效性和实验结论分开记录，失败尝试保留历史，未知状态不能直接当作失败重新提交。[S03]、[S04]

当前系统也已有文档持久化、节点会话恢复和双宿主适配。因此“增加 memory”“增加树搜索”“增加 durable agent”都不是准确的首要建议；需要加强的是这些机制怎样影响科学判断。[S05]、[S07]、[S08]、[S09]

### 2.2 优先问题

| ID | 优先级 | 当前事实或静态风险 | 影响 | 对应设计 |
|---|---|---|---|---|
| F01 | P0 | `record_verdict()` 接受外部提供的均值、标准差和比较差值；相应检查没有从 run 指标重算这些数字 | 数字之间自洽，不等于数字与实验记录一致 | D1 |
| F02 | P0 | GO 候选依据节点缓存字段；更换框架清空 baseline 时，旧节点通过记录可能仍被识别为候选 | 过期证据可能支持新的 GO 决定 | D2 |
| F03 | P1 | 所有指标无正向差值时必须 `no_gain`；达到 `gate_seeds` 后不能 `close` | 将资源上限误用为必须得出结论的依据 | D3、D4 |
| F04 | P1 | 可拓展要求优于父节点或 SOTA；新子节点要求父节点可拓展 | 搜索偏向即时改进，修复与组合关系不够自然 | D5 |
| F05 | P1 | 已有记录与恢复材料，但还需要明确的经验提炼、适用范围和检索策略 | 历史存在，不代表后续工作有效利用历史 | D6 |
| F06 | P1 | 用量提醒基于已记录实际用量，未见对在途作业的总预算预留 | 并发实验可能同时通过预算检查 | D7 |
| F07 | P1 | worker 自审加 Leader 复核是默认安排 | 最终候选仍需要针对方法—代码与数字来源的独立核查 | D8 |
| F08 | P1/P2 | 框架接口测试不能替代科学判定故障测试和整个研究过程的对照实验 | 无法证明额外编排成本换来了实际研究收益 | 第 15、16 节 |

F01、F03 的直接代码位于 [统计判定区域][S11]；F02、F04 位于 [节点/项目决策区域][S12] 与 [GO 候选查询][S13]；F06 位于 [预算与实验创建区域][S14]。F05、F07 是目标层面的改进判断，不应表述为已经证实的运行故障。

### 2.3 两个需要先写回归测试的具体场景

**场景 A：汇总数值与 run 不一致。** 测试夹具中的 `finish_runs()` 将主指标填为 70.0，而 `evaluate()` 可另外提交 70.3 及正向比较差值。这说明现有状态机测试使用了彼此独立的数字替身；需要补充拒绝数字不一致的专门测试，而不是据此宣称真实运行已经产生虚假结果。[S06]、[S11]

**场景 B：旧 GO 资格未随实验依据更新。** `update_project()` 更换框架会清空旧 SOTA 指针；`_is_go_candidate()` 只检查 `beats_sota` 和两项 `pass`。由此推断，存在旧通过字段继续支持候选查询的路径。必须用真实数据库夹具验证，并在修复后回归；本文未执行该场景。[S03]、[S12]、[S13]

### 2.4 对照 ARIS 后补充的缺口

以下缺口由对照 ARIS（`Auto-claude-code-research-in-sleep` @ 3b19a22）逐文件阅读后确认，均已在源码中核对；它们与平台无关，适合放进插件。执行层（调度、轮询、唤醒）是有意留白，见 05 §1。

1. **交付与验收的证据绑定不足。** `update_task` 的 delivered → accepted 只检查文档章节存在；没有要求验收引用一个判定/证据 ID，也没有"恢复时回到第一个未验收任务"的规则。ARIS `run_state.py` 的 `accept()` 要求 `verdict_id` 且 reviewer 与执行者不同，`resume_point()` 返回第一个未 accepted 的阶段。
2. **声明的数字不与文件核对。** 结果文档、交付文档里的数字没有任何代码检查它确实出现在所引用的日志或指标文件中。ARIS `evidence_check.py` 做的正是这一步，且失败时拒绝而不是放行。
3. **复核发现没有账本。** 新颖性/理论复核结果只有 `pass/fail` 字段加一份文档；一个被指出的问题可以在下一版文档里消失。ARIS `forensics_gate.py` 的"只追加、只能 resolve/waive 关闭、消失即未解决"账本是直接对策。
4. **没有停滞检测。** 规则要求"不制造假进度"，但没有计数器告诉 Leader 某子树连续几批没有新发现。ARIS `iteration_log.py` 用两个常量就做到了。
5. **文献只是文档类型。** `cache/literature/` 建了空目录，没有抓取、没有存在性核验、`min_related_work` 只是数量门槛（设计文档 10.7 已指出）。ARIS 有现成的 arXiv/Semantic Scholar/OpenAlex 脚本和三层存在性核验。
6. **没有外部通知接口。** 通知只在宿主内（Claude toast/pane、Codex inbox）。过夜运行需要用户决定（预算、权限）时没有推送渠道。这与调度平台无关，可做成可选的通用 webhook；ARIS 的 feishu-bridge 是飞书专用，只借其 `send` + `poll` + 超时记录未答复的形状。
7. **Claude 端消息无回执状态。** UI → RLD 通过 `$.prompt.submit`，"待回执"只在页面上按 `re` 匹配计算；Codex 端有 `acknowledge`。两端语义不对称。
8. **Leader 恢复上下文没有压缩策略。** `resume_package` 返回原始记录；没有像 ARIS `rebuild_query_pack` 那样按优先级（目标 → 未决问题 → **失败节点与教训** → 关键证据 → 最近关系）截断到固定字数。设计文档 D6 的检索策略需要这样一个确定性生成器。
9. **文档模板缺位。** `doc_library.md` 说模板在 `docs/workflow/templates/`，但 init 不生成；front matter 从不校验。ARIS 的 `EXPERIMENT_PLAN_TEMPLATE`（claim → 最小说服性证据 → 成功判据 → 失败解释 → 成本 → 优先级）和 `EXPERIMENT_LOG_TEMPLATE` 可改成假说文档与结果文档的必需章节。
10. **记忆写入无过滤。** 若按 D6 建 `docs/lessons/`，需要防止"command not found""OOM""rate limit"这类运维噪声被登记为研究经验。ARIS `capture_filter.py`（126 行）专门做这件事。

## 3. 与 ARIS 及参考研究项目的对照

### 3.1 与 ARIS 的定位差异

- **保留并加固现有内核。** research-tree 已有的 LatticeDB 状态机、角色权限、冻结框架、seed/预算检查、产物清理是 ARIS 没有的。ARIS 的预算、重试、超时全部写在 SKILL.md 的提示词里，代码不执行。不要为了"更像 ARIS"把这些约束退回提示词。
- **执行层是有意留白，不是缺口。** 作业提交、查询、取消和会话唤醒由 `platform.skills` 加载的站点技能负责（本站点为 `miyabi-pbs-cmd`、`miyabi-pbs-goal-wakeup`），插件只记录结果。插件面向大众发布，不能内置任何调度器。因此 ARIS 的 `queue_manager.py`、`watchdog.py` 和 D7 中的平台适配部分**不移植**；插件侧只保留平台无关的记账与对账约定（§3.3）。
- **ARIS 真正值得搬的是约 3000 行平台无关的确定性 Python**（证据核验、验收/恢复规则、未决问题账本、停滞计数、文献核验、记忆压缩与过滤），而不是它 87 个技能、多模型路由和执行后端。
- **当前项目的缺口集中在"证据与记录"而不是"执行"**：没有数字重算与文件核对、验收不绑定证据、复核发现无账本、无停滞检测、无文献工具、文档模板缺位、恢复上下文无压缩。这些都与平台无关，适合放进插件。

| 维度 | research-tree（本项目） | ARIS |
|---|---|---|
| 目标 | 阶段 1 低成本假说筛选，GO/NOT GO | 全流程：选题 → 实验 → 论文 → 投稿 → rebuttal |
| 状态存储 | LatticeDB 属性图，写事务 + 版本化文档 | Markdown/JSON/JSONL 文件；无数据库 |
| 约束执行 | 权限、状态转换、冻结框架、seed、预算由 `research_db.py` 拒绝 | 全部为提示词常量（`MAX_ROUNDS=4`、`MAX_TOTAL_GPU_HOURS=8` 等） |
| 角色 | 唯一 Leader + 每节点固定 worker + 只读 UI；无常驻 reviewer | 执行者（Claude）+ 异族 reviewer（GPT via codex MCP）；Type-B 判定必须跨模型族 |
| 执行层 | 有意不实现：提交/查询/取消/唤醒由 `platform.skills` 的站点技能负责；插件只记 `job_id`、`exec_status`、用量 | 同样把算力声明放在 `CLAUDE.md`（`compute-env-contract.md`），按提供商分技能（`vast-gpu`、`serverless-modal`、`qzcli`）；另有远端 `queue_manager.py`、`watchdog.py` 守护进程 |
| 文献 | 仅 literature 文档类型 + `rel_references` 边；无检索工具 | `arxiv/semantic_scholar/openalex` 抓取脚本 + `verify_papers.py` 存在性核验 |
| 记忆 | 文档库 + `resume_package` | `research_wiki.py`：类型化边、失败想法优先的 query_pack |
| 测试 | 109 个测试，覆盖数据库/页面/消息/两端适配 | ~700 个测试，只覆盖确定性工具；技能行为不测 |

ARIS 的文档多处超前于代码（队列"磁盘满"处理、monitor 读 `queue_state.json`、环境 spec-hash 账本、meta-apply 完整性校验均未实现）。移植时以其代码和测试为准，不以 SKILL.md 为准。

### 3.2 直接参考

| 研究/项目 | 已核对的参考机制 | 适合采用的部分 | 不直接复制的部分 |
|---|---|---|---|
| Auto-RecSys，2026-09 | 异步实验、跨会话记忆、认知/过程分离、执行与想法双回路 | 操作交给脚本；分别提炼研究发现和运行经验 | 工业推荐系统的全部基础设施；未核实的具体收益外推 |
| OR-Agent，2026 | 树式研究、演化搜索、分层反思 | 明确候选关系、跨实验经验、搜索深度/宽度约束 | 把“树搜索”当作独有优势；未经验证的搜索策略照搬 |
| ScientistOne / Science One Framework，2026 | Chain-of-Evidence 与数字、规格、引用、方法—代码核验 | 轻量证据绑定与最终候选审计 | 完整自动论文生成链路 |
| AutoResearchClaw，2026 | 执行修复、Pivot/Refine、可验证报告、跨运行经验、人机协作 | 失败不直接变为科学否定；验证过的经验复用 | 固定的大量研究/写作阶段和每轮多 agent 辩论 |
| DeepScientist，2025 论文、2026 项目 | Findings Memory、分层验证、长期研究工作区 | 高价值候选升级验证；失败路径与基线复用 | 月级大规模探索作为 Stage 1 的默认规模 |
| Karpathy autoresearch，2026 | 极简修改—训练—评估循环，固定训练时间，限制可修改文件 | 作为低开销基线；压缩循环外的管理成本 | 将单任务单 GPU 设定当作所有 ML 研究的通用协议 |
| AI Scientist-v2，2025 | agentic tree search 与公开实验配置 | 显式搜索与调试预算 | 论文成品质量作为唯一成功指标 |

本表分别依据 [R01]、[R02]、[R02C]、[R03]、[R03B]、[R04]、[R04C]、[R05]、[R05C]、[R06]、[R07]、[R07C]。它比较架构，不给未经共同实验测量的系统排名。

### 3.3 对本项目的判断

树、多角色、持久化和多宿主支持已在这些项目中出现。research-tree 更适合建立的差异是：在相同模型、相近计算预算和相同研究任务下，减少错误 GO、重复失败及无效实验，同时提高有效发现的确认率。[R02]、[R05C]、[R07C]

另一项研究在其测试的 agent 与模型组合中观察到，生成想法容易集中在起始文献附近。它不证明 research-tree 存在同样问题，但支持将机制多样性、重复探索与跳出局部方向的能力纳入评测。[R08]

### 3.4 文献核验的限制

本次核验了参考条目的原始论文记录或官方仓库/说明。Auto-RecSys 的 arXiv 检索结果提供了完整摘要，但直接网页/HTML 全文抓取失败，因此本文只使用摘要明确列出的架构，不引用其具体运行数字，也不声称已检查开源实现。

OR-Agent 的原始 arXiv 页面本次返回 v3，搜索中另有 v4 信息但对应原始版本页未成功抓取。因此本文不沿用上一轮关于“已审阅 v4 具体遍历规则”的确定表述，也不把某个缓存版本称为已确认的最新版本。第 20 节给出原始入口和本次核验范围。

## 4. 目标架构与职责划分

### 4.1 保留四层，不引入新的编排框架

```text
用户与宿主入口
    │  明确目标、授权、预算；停止与变更
    ▼
Leader：研究决策层
    │  假说、实验选择、竞争解释、投入判断
    ▼
共享内核：确定性控制层
    │  状态、指标、证据有效性、预算、提交身份、恢复
    ▼
worker / runner：执行层
       实现方法；执行实验；提交原始材料
```

Claude 与 Codex 适配层只负责宿主调用、权限映射、会话状态、事件通知与展示。统计规则和 GO 资格不能在两个适配层各实现一份。

### 4.2 责任矩阵

| 事项 | 主要负责人 | 不能委托给什么 |
|---|---|---|
| 假说、竞争解释和下一次实验价值 | Leader | 单一指标自动排序不能代替全部判断 |
| 实验代码实现与自审 | 节点 worker | 不能靠报告文字声称代码已实现 |
| 原始指标导入、配对与汇总 | 冻结解析器与共享内核 | 不能由 LLM 手算填入作为权威值 |
| GO 资格查询 | 共享内核 | 不能仅读取 Leader 写下的通过标签 |
| 预算准入、作业身份和对账 | 共享内核与平台适配器 | 不能靠提示词防止重复或超额提交 |
| 新颖性、推导、方法—代码复核 | 定向复核任务与 Leader | 不能把字段完整等同于科学正确 |
| 用户指令与范围变化 | 用户、UI、Leader | 不能由记忆条目或超时自动授权 |

### 4.3 最小模块拆分

建议在共享工具中逐步提取以下模块；名称是拟议名称，不是当前已有文件：

```text
metrics.py              # MetricSpec、配对、效应量与汇总
protocol.py             # 实验协议及配置匹配规则
evidence.py             # Evaluation、证据有效性、GO eligibility
budget.py               # 预算预留与结算
scheduler.py            # 提交身份、查询、对账；平台最薄适配
memory.py               # 文档型经验检索；可后置
```

`research_db.py` 继续作为事务、权限和公共接口入口。不要为了这次改进先做全仓库大规模重构。P0 可先用少量辅助函数实现，接口稳定后再拆分。

### 4.4 本设计包新增的角色与模块

| 角色 / 模块 | 职责 | 所在文件 |
|---|---|---|
| `reviewer`（pi 非交互会话） | 只读；按 kind 产出 `review` 文档；不作研究决定 | 09 |
| lens 助手（只读子代理） | 只生成候选，不排序、不断言新颖性 | 02 |
| `pi_review.py`、`discovery_state.py`、`discovery_gate.py`、`candidates.py`、`literature.py` | 确定性脚本；无模型调用 | 02、08、09 |
| `evidence.py` 中的数字核验（`evidence_check` 式） | 文档引用的数字必须出现在所引文件中 | 05 |
| obligation 账本、停滞计数 | 复核发现只能 resolve/waive 关闭；连续无新发现强制换向 | 06 |

<!-- 引用链接 -->

[R01]: https://arxiv.org/abs/2609.10922
[R02]: https://arxiv.org/abs/2602.13769
[R02C]: https://github.com/qiliuchn/OR-Agent
[R03]: https://arxiv.org/abs/2605.26340
[R03B]: https://research.google/blog/science-one-framework-a-verifiable-autonomous-research-framework-via-chain-of-evidence/
[R04]: https://arxiv.org/abs/2605.20025
[R04C]: https://github.com/aiming-lab/AutoResearchClaw
[R05]: https://arxiv.org/abs/2509.26603
[R05C]: https://github.com/ResearAI/DeepScientist
[R06]: https://github.com/karpathy/autoresearch
[R07]: https://arxiv.org/abs/2504.08066
[R07C]: https://github.com/SakanaAI/AI-Scientist-v2
[R08]: https://arxiv.org/abs/2605.27905
[S01]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/README.md
[S02]: https://github.com/UnbearableFate/research-tree/commit/48b3841d97275b2e9ad010d91d261acc9c7c4f5c
[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
[S04]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/rules/research-tree-rules.md
[S05]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/research_tree.sql
[S06]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tests/test_research_db.py
[S07]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_runtime.py
[S08]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_agent.py
[S09]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/claude-mod/research-tree/hooks/register.tsx
[S11]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1030-L1170
[S12]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L780-L858
[S13]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1630-L1799
[S14]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L858-L955
