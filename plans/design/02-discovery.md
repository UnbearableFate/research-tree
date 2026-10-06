---
title: "阶段 1：立项前发现（文献 → 候选 → 查新 → 评审）"
stage: "阶段 1"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "discovery 文档 §1–3、§5、§7；ARIS skills/idea-discovery、idea-creator、novelty-check、research-review、research-lit"
language: "zh-CN"
---

# 02 阶段 1：立项前发现

把 ARIS `/idea-discovery` 的链路（文献调研 → 候选想法生成 → 查新 → 外部批判性评审 → 方法精炼与实验规划）接到 research-tree 的**立项规划阶段**。用户只给研究方向时，链路从零生成候选；用户已写好初始假说时，这些假说作为**种子**进入同一链路：文献调研与候选生成围绕它们展开，发现相关、变体、组合或竞争性的新想法，然后用户假说与新发现的候选**一起**送入查新与评审。

跨模型 reviewer 改为**非交互 CLI 执行**：Claude 系模型用 Claude Code CLI（`claude -p --output-format json`），其他 provider 用 `pi`（`pi -p --mode json`），由插件内一个确定性包装脚本按 provider 路由、调用、解析和登记（09）；不引入 ARIS 的 Codex MCP、manual-review 或 MCP 多后端路由。

边界：

- **pilot 实验不单独实现。** ARIS 在 idea-creator Phase 5 用 GPU 跑 2–3 个 pilot。research-tree 里"pilot"就是节点的筛选实验（1 个 seed、冻结框架），且规则规定用户确认立项前不启动 worker。因此 discovery 只做到"纸面验证 + 建节点"，pilot 由现有树流程完成。
- **执行层不变。** 作业提交与唤醒仍由 `platform.skills` 的站点技能负责（05 §1）。
- **不移植** research-wiki、Feishu、HTML 渲染、COMPACT、`REF_PAPER`（后者由 `plan.md` 的"参考资料"节承担）。

## 2. ARIS 各阶段到 research-tree 的映射

| ARIS 阶段 | ARIS 做法 | research-tree 的落点 | 登记为 |
|---|---|---|---|
| Phase 0 Research Brief | 读 `RESEARCH_BRIEF.md` | `plan.md` 的研究目标、实验范围、参考资料 + `research-tree.yaml` 预算 | 已有：`UI-0001` 用户指令、goal 文档 |
| Phase 1 research-lit | 多源检索 + `verify_papers.py` 存在性核验，`[UNVERIFIED]` 不丢弃 | 文献助手任务：抓取脚本 + 存在性核验，原文缓存到 `cache/literature/` | `literature` 文档（front matter 含 `verification: verified/unverified`） |
| Phase 2 idea-creator：lens fan-out | 同族子代理按 5 个 lens 只生成候选，不打分；机械去重 | 只读 `assistant` 子代理按 lens 生成；有用户假说时追加以其为中心的 variant / combination / competing / repair lens；Leader 合并、按 `dedup_key` 去重，用户假说以 `origin: user` 保留 | `docs/project/discovery/candidates.v1.md` + `.json` |
| Phase 2 外部模型 brainstorm | Codex 两个模型各生成一轮，取并集 | 可选：跨模型 reviewer 以"生成者"身份再出一轮，并入候选池（不是判定） | 同上，候选带 `generator` 字段 |
| Phase 3 客观可行性门 | 只按预算事实淘汰（>1 周 GPU、数据不可得）；其余只注记 | 确定性脚本按 `budget.per_run`、`screen_node_h`、平台文本判断"筛选实验能否在单次运行上限内跑完"；其余注记 `prior_work / so_what / effort_note` | 候选 JSON 的 `feasible` 字段与理由 |
| Phase 4 cross-model triage | Codex 对全部候选做 devil's advocate 排序，分配 pilot 名额 | **跨模型评审（kind=triage）**：读候选文件，输出排序与命名风险；排序只决定哪几个新候选进入查新与建节点；用户假说不参与淘汰，但同样得到最强反对意见 | `review` 文档 |
| Phase 3/4 novelty-check | 3–5 核心声明 × ≥3 查询，dossier 交 Codex，verdict limits 原文 | **跨模型评审（kind=novelty_precheck）**：对用户假说和 triage 选出的新候选逐个进行；Leader 写 dossier（方法、声明、候选论文清单），reviewer 自己读文件后给 PROCEED / CAUTION / ABANDON；ABANDON 必须点名论文 | `review` 文档；最接近工作写入 `literature` 引用 |
| Phase 4 research-review | Codex 多轮批判性评审，只给路径不给摘要 | **跨模型评审（kind=critical_review）**：新会话、只给文件路径、要求最强反对意见 + 最便宜的区分实验；多轮用同一会话 ID 续接（09 §2.1） | `review` 文档 |
| Phase 4.5 research-refine | 冻结 Problem Anchor，7 维打分，READY/REVISE/RETHINK，≤5 轮 | Leader 写每个入选想法的假说文档（含 Problem Anchor、方法步骤、可证伪预测、竞争解释、最小实验、成本、停止条件、有意舍弃的复杂度）；可选 1–2 轮 **跨模型评审（kind=proposal_review）** | `hypothesis` 文档（新增必需章节） |
| experiment-plan | claim → 证据块 → 里程碑 | 并入假说文档的"最小实验"与根节点任务请求；不另建 EXPERIMENT_PLAN | 已有：`task_request` |
| Phase 5 IDEA_REPORT + evidence gate | 单一报告；`idea_discovery_gate.py` 校验各阶段证据与评审回执 | `docs/project/reports/discovery.v1.md`（含淘汰想法与理由）；确定性门检查后才允许 `confirm_request` | `report` 文档；门结果写入 `.research-tree.json` |
| Phase 5.6 research_contract | 当前想法的精简合同 | 由 `context_pack`（08 §3）生成，不另存文件 | 无 |

## 3. 在 research-tree 中的流程

```text
prepare → init（plan.md 的"初始假说"可以是用户的假说，也可写"由发现流程产生。"）
  → phase=planning
      D0 立项简报：goal 文档、约束、预算；用户假说登记为 origin=user 的种子候选（Leader）
      D1 文献：literature 助手任务，围绕方向与种子检索，抓取 + 存在性核验 + 缓存
      D2 候选生成：lens 只读子代理 ×N（通用 lens + 以种子为中心的 lens；可选跨模型 reviewer 生成一轮）→ 合并去重
      D3 可行性门：确定性脚本，只按预算与平台事实淘汰；种子只注记
      D4 triage：跨模型评审，排序 + 命名风险 → 从新候选中选 top-N；种子直接进入 D5
      D5 查新：种子 ∪ top-N，每个一次跨模型评审（novelty_precheck）；ABANDON 需点名论文
      D6 批判性评审：每个幸存想法一次跨模型评审（critical_review）；种子的否定结论留给用户决定
      D7 精炼：Leader 写假说文档；可选 proposal_review 1–2 轮
      D8 发现门：确定性检查 → discovery 报告 → create_hypothesis 建初始节点
  → 立项计划 confirm_request（现有流程）
  → 用户确认 → 根节点框架与基线 → 各节点筛选实验（= pilot）
```

关键约定：

- **用户假说是种子，不是终点。** `plan.md` 里的初始假说以 `origin: user` 进入候选池：D1 的检索围绕它们展开；D2 的 lens 除通用五个外，对每个用户假说再加 `variant`（同机制的不同实现）、`combination`（与其他候选组合）、`competing`（更便宜的替代解释）、`repair`（修正其明显弱点）四个 lens；D3、D4 对它们只注记、不淘汰，triage 的排序也不影响它们进入 D5。于是 D5 查新和 D6 评审的对象 = 用户假说 ∪ triage 选出的 top-N 新候选。
- **用户假说的否定结论交给用户。** 查新得到点名论文的 ABANDON，或评审 `stance=abandon`，不自动淘汰用户假说；写入 discovery 报告并在立项计划里标为"建议放弃，待用户决定"。这与规则 §6"尚未做实验的节点只有在用户决定放弃后才能被消灭"一致。
- **`discovery.mode`**：`off` 完全沿用现状；`full`（默认）按上面执行，无论用户是否给了假说；`precheck` 不做 D2–D4，只对用户假说做文献、查新、评审与精炼。
- **D8 门通过前不能建节点。** 配置 `discovery.require_precheck: true` 时，`create_hypothesis` 要求节点被一份 verdict 为 PROCEED/CAUTION 的 `novelty_precheck` 和一份结论不主张放弃的 `critical_review` 描述，且两者的 reviewer 身份有效。这与现有"创建节点须引用 ≥ `min_related_work` 篇文献"并列检查；`[UNVERIFIED]` 文献不计入数量门槛。
- **淘汰的想法不丢。** 每个被淘汰的候选记入 discovery 报告的"淘汰想法"表（阶段、理由、点名论文），并作为后续再生成的禁止列表（context pack 的"失败优先"顺序）。报告分两栏：用户假说（逐条给查新与评审结论）和新发现候选（排序）。
- **AUTO_PROCEED 对应现有规则：** 立项确认是唯一阻塞点；D1–D8 之间的 checkpoint 只写进度到研究对话窗口，不等待用户。

本阶段的输出进入 03：每个幸存想法（用户假说 ∪ 入选新候选）带着文献引用、查新与评审文档，由 Leader 写成假说文档与实验设计。

## 4. 确定性部分

| 组件 | 来源 | 说明 |
|---|---|---|
| `review_call.py` | 新写；借鉴 ARIS `review_gate.py` 的"模型输出 → 校验枚举 → 确定性转换"和 `save_trace.sh` 的追踪字段 | §4 |
| `discovery_state.py` | 移植 ARIS `tools/run_state.py`（399 行，20 个测试）的 `start/set/accept/resume_point/record_gate_result`；去掉 provisional 与模型族逻辑，改为"accept 需要 review 文档 ID 且 reviewer provider ≠ executor" | 状态存 `cache/discovery/<run>.json`；`resume` 返回第一个未 accepted 阶段 |
| `discovery_gate.py` | 移植 ARIS `tools/idea_discovery_gate.py`（256 行，16 个测试）：检查各阶段状态、artifact 存在、报告锚点章节非空、评审回执有效 | 新增检查：每个拟建节点有 ≥ `min_related_work` 篇 verified 文献 |
| `literature.py` | 移植 ARIS `arxiv_fetch.py`、`semantic_scholar_fetch.py`、`openalex_fetch.py`、`verify_papers.py`（合计约 1800 行） | 存在性核验三层回退；不可用时标 `unverified` 而不是丢弃；网络调用按平台规则在允许的节点运行 |
| `candidates.py` | 新写；按 ARIS `fan-out-pattern.md` 的 shard schema 合并、`dedup_key` 去重、可行性门 | 去重只做机械聚类，不按质量淘汰 |
| `threat_scan.py` | 移植 ARIS（222 行） | 文献原文、外部仓库说明回灌 Leader 前扫描 |

## 5. 规则与提示词改动

- 规则 §1：新增角色 `reviewer`（pi 或 Claude Code CLI 非交互会话；只读；产出 review 文档；不作研究决定）和 `lens 助手`（只读；只生成候选，不排序、不断言新颖性）。
- 规则 §6"创建节点"：引用的文献须经存在性核验；`discovery.require_precheck` 开启时附评审回执；"复核只在优于 SOTA 后进行"保持不变，立项前的 `novelty_precheck` 不替代它。
- 规则 §6 新增一条：**loop 可以 DRIVE，不能 ACQUIT**——Leader 可以组织生成与去重，但"是否新颖""是否值得做"由 reviewer 文档或确定性门给出；reviewer 不可用时记 `REVIEW_UNAVAILABLE`，不得自评代替。
- `planningPrompt`（Claude）与 `codex_prompts.planning`（Codex）：当 `discovery.mode != off` 时，先走 D0–D8（用户假说作为种子）再写立项计划；立项计划把用户假说与新发现候选分列，并注明各自的查新与评审结论。
- 假说文档必需章节改为：问题锚点、方法步骤（白话）、可证伪预测、竞争解释、最接近工作与差异、最小实验、成本估计、停止条件、有意舍弃的复杂度；由接口像 `TASK_SECTIONS` 一样检查。

## 6. 本阶段不移植的 ARIS 内容

pilot 实验（对应本项目的节点筛选实验，见 06）、research-wiki 写回（08 以文档库与关系边替代）、Feishu 通知、HTML 渲染、`COMPACT`、`REF_PAPER`（由 `plan.md` 参考资料承担）。
