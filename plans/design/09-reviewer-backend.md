---
title: "横切：pi 非交互评审后端"
stage: "横切"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "discovery 文档 §4、§10；本机实测 pi 1.0.4"
language: "zh-CN"
---

# 09 横切：pi 非交互评审后端

所有 Type-B 判定（06 §1）的外部评审只用一个后端：`pi` 非交互执行。它服务于 02（triage、查新、批判性评审、proposal 评审）、03（消融规划、代码审查）与 07（GO 候选复核）。

## 1. 本机实测（2026-10-06）

| 项目 | 结果 |
|---|---|
| 版本 | pi 1.0.4；`pi auth check --provider {anthropic,google,openai,deepseek} --json` 均 `ready` |
| 非交互 | `pi -p --mode json … "<prompt>"` 输出 JSONL；最后的 `turn_end` 事件含 `message.content[].text`、`provider`、`model`、`usage.cost.total`、`stopReason` |
| 失败形态 | 模型不可用时 `stopReason: "error"` 且 `errorMessage` 给出原因，进程仍正常退出；`agent_end.willRetry` 标明是否重试 |
| 文本模式 | `pi -p` 只打印最终回复，适合不需要元数据的场合；本设计一律用 JSON 模式以拿到模型身份与费用 |
| 工具 | `--tools read,grep,find,ls` 可让 reviewer 自己读文件；`--no-tools` 纯文本评审 |
| 隔离 | `--no-session`/`--session-id`、`--no-extensions --no-skills --no-context-files --no-mcp` 可保证评审上下文只含我们给的 brief |
| 多轮 | `--session-id <id> --session-dir <dir>` 固定会话文件位置，`-c` 续接 |

## 2. 调用约定

拟议脚本 `shared/research-tree/tools/pi_review.py`（确定性，无模型调用）：

```text
pi_review.py --db <db> --actor rld/main --kind <triage|novelty_precheck|critical_review|proposal_review|candidate_recheck>
             --brief docs/project/discovery/briefs/<...>.v1.md --about <候选或节点ID> [--session <RV-id>]
```

1. **前置检查**：`pi auth check --provider <p> --json` 退出码 0；`--model` 在 `pi --list-models` 中；否则返回 `REVIEW_UNAVAILABLE`，不降级为 Leader 自评。
2. **身份约束**：从 `logs/agent_models.jsonl` 读 Leader 的 observed 模型，`require_cross_family: true`（默认）时 reviewer 的 provider 必须不同；不能判定时返回 `REVIEW_UNAVAILABLE`。
3. **调用**：

```bash
pi -p --mode json --model <provider/model> --thinking <level> \
   --no-extensions --no-skills --no-context-files --no-mcp \
   --tools read,grep,find,ls --session-id <RV-id> --session-dir research/<id>/cache/pi-sessions \
   --append-system-prompt <kind 对应的角色与输出格式文件> \
   "Read the brief at <绝对路径> and follow it. Executor notes are not evidence beyond the files they cite."
```

   工作目录为 `research/<项目ID>/`。brief 只含角色、目标、文件路径和结构化元数据，**不含 Leader 的摘要、解释或倾向性问题**（ARIS reviewer-independence）。
4. **解析**：取最后一个 `turn_end`；`stopReason != "stop"` → `REVIEW_UNAVAILABLE`。回复末尾必须有一个 ```json 代码块，按 kind 的 JSON schema 校验（见 4.3）；校验失败一次性追问"只输出 JSON"后仍失败 → `REVIEW_INVALID`。
5. **登记**：写 `docs/reviews/RV-<编号>.v1.md`（front matter：kind、about、reviewer provider/model/thinking、session id、usage 与费用、stopReason；正文为 reviewer 原文 + JSON），原始 JSONL 存 `cache/reviews/RV-<编号>.jsonl`；以 `author_role=reviewer` 调 `register_document` 并 `set_document_current`，`rel_describes` 指向候选或节点。
6. **费用**：累计 `usage.cost.total` 到项目记录；达到 `budget.review_usd_alert` 时写 attention 并暂停新的评审调用。

## 3. 输出 schema（按 kind）

| kind | 用于 | 必填字段 |
|---|---|---|
| `triage` | 02 | `ranking[]`：`candidate_id, rank, best_case, strongest_objection, failure_mode, prior_work_is_blocking(bool), pilot_worthy(bool)`；`high_upside_pick` |
| `novelty_precheck` | 02 | `verdict ∈ PROCEED/PROCEED_WITH_CAUTION/ABANDON`，`score 1–10`，`closest_prior_work[]`：`title, id, overlap, difference`，`delta_sentence`，`abandon_paper`（ABANDON 时必填且须在 closest_prior_work 中） |
| `critical_review` | 02 | `stance ∈ proceed/abandon`，`named_risks[]`，`cheapest_discriminating_experiment`，`missing_evidence[]` |
| `proposal_review` | 02 / 03 | `scores{problem_fidelity, method_specificity, contribution_quality, feasibility, validation_focus}`，`overall`，`verdict ∈ READY/REVISE/RETHINK`，`drift_warning`，`action_items[]` |
| `ablation_plan` | 03 §7 | `ablations[]`：`name, what_it_tests, expected_if_component_matters, priority 1–5, config_only(bool)`；`coverage_assessment`，`unnecessary_ablations[]`，`suggested_order[]`，`estimated_compute` |
| `code_review` | 03 §8 | `issues[]`：`severity ∈ CRITICAL/MAJOR/MINOR, file, line, category ∈ gt_source/normalization/dead_metric/seed_config/method_mismatch/other, description`；`method_implemented(bool)` |
| `candidate_recheck` | 07 | `dimension`、`result ∈ pass/fail/uncertain/not_applicable`、`evidence_paths[]`、`reason` |

正向判定定义照搬 ARIS：novelty 的 PROCEED 与 CAUTION 都算正向，只有点名论文的 ABANDON 是负向；critical_review 的"列出风险"不是否定，只有 `stance=abandon` 才是。ARIS novelty 的 **VERDICT LIMITS** 原文块放进 `novelty_precheck` 的系统提示文件。

## 4. 与现有角色、权限的关系

- `DOC_AUTHORS` 新增 `review: ("reviewer",)`；Leader 不能以 rld 身份登记 review 文档，只能通过 `pi_review.py`。
- 两端各加一个工具入口 `research_review`（Claude 为 hooks 注册的 tool，Codex 为 MCP tool），内部执行 `pi_review.py`；Bash guard 把直接调用 `pi` 列入拒绝项，避免绕过登记与追踪。
- `models.reviewer` 进入配置（见 §6）；与 `models.worker` 一样是三层证据：配置目标、实际请求（命令行）、运行证据（`turn_end.model`）。
- 同一包装脚本也服务设计文档 D8（GO 候选的定向复核，kind=`candidate_recheck`），因此 B1 批次独立于 discovery 就有价值。

## 5. 风险与限制

- **跨模型族不是独立证据。** 两个模型同意不等于实验独立；pi 评审只替代"Leader 自评"，不替代筛选实验。
- **pi 的 read 工具不限制路径。** brief 中只给研究目录路径，但不能把它当作隔离边界；需要更强隔离时按 pi `docs/security.md` 用容器运行。
- **pi 配置属于用户环境。** 插件只依赖 `pi` 在 PATH 且 provider 已登录；不替用户安装或登录。
- **费用可见但不封顶。** 插件只做累计提醒；硬封顶需在 provider 侧设置。
- 本机实测仅两次最小调用（一次模型 404、一次成功），未测长 brief、`--tools read` 与多轮会话。
