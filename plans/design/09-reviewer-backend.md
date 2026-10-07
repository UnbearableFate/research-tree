---
title: "横切：跨模型非交互评审后端（pi / Claude Code CLI）"
stage: "横切"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "discovery 文档 §4、§10；本机实测 pi 1.0.4、Claude Code 2.1.291"
language: "zh-CN"
---

# 09 横切：跨模型非交互评审后端

所有 Type-B 判定（06 §1）的外部评审都经过同一个确定性包装脚本 `review_call.py`，它按 reviewer 模型的 provider 选择 agent 基座：

| reviewer provider | agent 基座 | 命令 |
|---|---|---|
| `anthropic`（Claude 系模型） | **Claude Code CLI** | `claude -p --output-format json` |
| 其他（`openai`、`google`、`deepseek` 等） | **pi** | `pi -p --mode json` |

路由只由 `models.reviewer.model` 的 provider 前缀决定，不提供手动覆盖，也**不互为降级**：Claude Code CLI 不可用时不改走 pi 的 anthropic provider，pi 不可用时也不改走 Claude，一律返回 `REVIEW_UNAVAILABLE`。这样 review 文档记录的 agent 基座总能从模型推出来。

评审服务于 02（triage、查新、批判性评审、proposal 评审）、03（消融规划、代码审查）与 07（GO 候选复核）。kind、brief、输出 schema、登记与权限对两个后端完全相同（§3–§4），差别只在调用与解析这一层（§2.2–§2.3）。

## 1. 本机实测（2026-10-06）

### 1.1 pi 1.0.4

| 项目 | 结果 |
|---|---|
| 版本 | pi 1.0.4；`pi auth check --provider {anthropic,google,openai,deepseek} --json` 均 `ready` |
| 非交互 | `pi -p --mode json … "<prompt>"` 输出 JSONL；最后的 `turn_end` 事件含 `message.content[].text`、`provider`、`model`、`usage.cost.total`、`stopReason` |
| 失败形态 | 模型不可用时 `stopReason: "error"` 且 `errorMessage` 给出原因，进程仍正常退出；`agent_end.willRetry` 标明是否重试 |
| 文本模式 | `pi -p` 只打印最终回复，适合不需要元数据的场合；本设计一律用 JSON 模式以拿到模型身份与费用 |
| 工具 | `--tools read,grep,find,ls` 可让 reviewer 自己读文件；`--no-tools` 纯文本评审 |
| 隔离 | `--no-session`/`--session-id`、`--no-extensions --no-skills --no-context-files --no-mcp` 可保证评审上下文只含我们给的 brief |
| 多轮 | `--session-id <id> --session-dir <dir>` 固定会话文件位置，`-c` 续接 |

### 1.2 Claude Code CLI 2.1.291

用 `claude-haiku-4-5-20251001` 做了 5 次最小调用（成功、模型 404、读文件 + `--append-system-prompt-file` + `--json-schema`、`--session-id` 后 `--resume` 续接、越界读文件）。

| 项目 | 结果 |
|---|---|
| 登录检查 | `claude auth status` 输出 JSON，`loggedIn: true`、`authMethod`、`apiProvider` |
| 非交互 | `claude -p --output-format json … "<prompt>"` 输出**单个** JSON 对象（`type: "result"`）：`result`（最终文本）、`is_error`、`terminal_reason`、`api_error_status`、`session_id`、`total_cost_usd`、`usage`、`modelUsage`（键为实际使用的模型 ID，含 `costUSD`、`canonicalModel`）、`num_turns`、`permission_denials` |
| 失败形态 | 模型不存在时 `is_error: true`、`terminal_reason: "api_error"`、`api_error_status: 404`，`result` 是错误说明，stderr 有 `[claude-code:unrecognized_model]`；**`subtype` 仍是 `"success"`**，不能据此判成功 |
| 结构化输出 | `--json-schema '<schema>'` 后结果多一个 `structured_output` 字段（已解析的对象），`result` 为同一 JSON 的文本 |
| 工具 | `--tools Read,Grep,Glob` 只开放只读工具；reviewer 能自己读 brief 所列文件（实测 `num_turns: 3`） |
| 隔离 | `--safe-mode` 关闭 CLAUDE.md、skills、已装插件、hooks、MCP、自定义 agent；`--restricted` 去掉 Bash 等执行类工具、忽略 user/project/local settings，并把文件工具限制在工作目录（实测读 `/etc/hostname` 被拒，记入 `permission_denials`）；`--strict-mcp-config` 不加载任何 MCP |
| 权限 | `--permission-mode dontAsk --permission-prompts none`：需要询问的操作直接拒绝，不会卡在交互提示上 |
| 多轮 | `--session-id <uuid>`（须为 UUID）首轮，`--resume <uuid>` 续接，实测能记住上一轮内容；`--no-session-persistence` 不落盘，单轮评审用 |
| 费用 | `total_cost_usd`；`--max-budget-usd <x>` 可在单次调用上硬封顶。claude.ai 订阅登录时 `costBasis: "list"`，是按标价折算的名义费用 |

未测：长 brief、`--max-budget-usd` 实际触发时的输出形态、进程退出码（实测时输出经管道，未取到）。包装脚本以 JSON 字段判定，不依赖退出码。

## 2. 调用约定

拟议脚本 `shared/research-tree/tools/review_call.py`（确定性，无模型调用）：

```text
review_call.py --db <db> --actor rld/main --kind <triage|novelty_precheck|critical_review|proposal_review|ablation_plan|code_review|candidate_recheck>
               --brief docs/project/discovery/briefs/<...>.v1.md --about <候选或节点ID> [--session <RV-id>]
```

### 2.1 公共步骤

1. **路由**：解析 `models.reviewer.model`（`provider/model`）；`provider == anthropic` → Claude Code 后端，否则 → pi 后端。
2. **前置检查**（按后端，§2.2 / §2.3）；不通过返回 `REVIEW_UNAVAILABLE`，不降级为 Leader 自评，也不换后端。
3. **身份约束**：从 `logs/agent_models.jsonl` 读 Leader 的 observed 模型，`require_cross_family: true`（默认）时 reviewer 的 provider 必须不同；不能判定时返回 `REVIEW_UNAVAILABLE`。因此 Claude 宿主的 Leader 实际只会用到 pi 后端，Claude Code 后端主要服务 Codex 宿主（以及 14 §3 的实施评审）。
4. **会话**：每次评审一个新会话；多轮（proposal_review、code_review 重审、§2.1 第 6 步的追问）在同一 `RV-id` 下续接。包装脚本为每个 `RV-id` 生成一个 UUID 作为两端共用的会话 ID（Claude Code 要求 UUID）。
5. **brief**：工作目录为 `research/<项目ID>/`。brief 只含角色、目标、文件路径和结构化元数据，**不含 Leader 的摘要、解释或倾向性问题**（ARIS reviewer-independence）。kind 对应的角色与输出格式文件两端共用。
6. **解析与校验**：后端适配层把输出规整成同一条记录：

   ```text
   {backend: pi|claude_code, provider, model_requested, model_observed, session_id,
    ok(bool), error, text, structured(可空), cost_usd, usage, raw_path}
   ```

   `ok=false` → `REVIEW_UNAVAILABLE`（错误原文进 attention）。`structured` 为空时从 `text` 末尾的 ```json 代码块取 JSON。按 kind 的 JSON schema 校验（§3）；失败则在同一会话追问一次"只输出 JSON"，仍失败 → `REVIEW_INVALID`。`model_observed` 与请求的模型不一致时同样 `REVIEW_INVALID`（不让 CLI 的 fallback 或别名解析悄悄换掉 reviewer）。
7. **登记**：写 `docs/reviews/RV-<编号>.v1.md`（front matter：kind、about、`backend`、reviewer provider/model（请求与 observed）/thinking、session id、usage 与费用、终止原因；正文为 reviewer 原文 + JSON），原始输出存 `cache/reviews/RV-<编号>.jsonl`（pi）或 `.json`（Claude Code）；以 `author_role=reviewer` 调 `register_document` 并 `set_document_current`，`rel_describes` 指向候选或节点。
8. **费用**：累计 `cost_usd` 到项目记录；达到 `budget.review_usd_alert` 时写 attention 并暂停新的评审调用。

### 2.2 pi 后端（非 Claude 模型）

- **前置检查**：`pi auth check --provider <p> --json` 退出码 0；`--model` 在 `pi --list-models` 中。
- **调用**：

  ```bash
  pi -p --mode json --model <provider/model> --thinking <level> \
     --no-extensions --no-skills --no-context-files --no-mcp \
     --tools read,grep,find,ls --session-id <uuid> --session-dir research/<id>/cache/review-sessions \
     --append-system-prompt <kind 对应的角色与输出格式文件> \
     "Read the brief at <绝对路径> and follow it. Executor notes are not evidence beyond the files they cite."
  ```

  续接加 `-c`。
- **解析**：从最后一个 `turn_end` 读取终止原因、`text`、`model_observed` 与 `usage`；`stopReason != "stop"` → `ok=false`；`text` = `message.content[].text`；`model_observed` = `message.provider/model`。`cost_usd` 累加本次 CLI 调用所有 `turn_end` 的 `message.usage.cost.total`，包括工具读取回合和失败的终止回合；`message_end` / `agent_end` 中重复的消息不再计费。同会话的 JSON 补正调用另存原始输出，费用亦计入该次评审总额。

### 2.3 Claude Code 后端（Claude 模型）

- **前置检查**：`claude` 在 PATH；`claude auth status` 的 JSON 中 `loggedIn: true`。Claude Code 没有列模型的命令，模型名无效在调用时以 404 暴露（§1.2），按 `ok=false` 处理。
- **参数映射**：`model` 去掉 `anthropic/` 前缀（`anthropic/claude-sonnet-5-5` → `claude-sonnet-5-5`）；`thinking`（pi 的取值 `off/minimal/low/medium/high/xhigh/max`）映射到 `--effort`：`off`/`minimal`/`low` → `low`，`medium`/`high`/`xhigh`/`max` 原样。
- **调用**：

  ```bash
  claude -p --output-format json --model <claude-model> --effort <level> \
     --safe-mode --restricted --strict-mcp-config \
     --tools Read,Grep,Glob --permission-mode dontAsk --permission-prompts none \
     --session-id <uuid> \
     --append-system-prompt-file <kind 对应的角色与输出格式文件> \
     --json-schema '<kind 的 JSON schema>' \
     [--max-budget-usd <距 review_usd_alert 的余额>] \
     "Read the brief at <绝对路径> and follow it. Executor notes are not evidence beyond the files they cite."
  ```

  续接把 `--session-id <uuid>` 换成 `--resume <uuid>`。`--safe-mode` 保证 reviewer 会话不加载 research-tree 插件自身的 hooks 与工具，也不读项目 CLAUDE.md；`--restricted` 让读文件只能落在 `research/<项目ID>/` 内，brief 引用的仓库外路径（如代码审查的代码目录）必须用 `--add-dir` 显式加入。
- **解析**：单个 JSON 对象。`ok` = `is_error == false` 且 `terminal_reason == "completed"`（**不看 `subtype`**）；`text` = `result`；`structured` = `structured_output`；`model_observed` = `modelUsage` 的键，必须恰好一个（`--tools` 未开放 Agent，不应出现子代理模型）；`cost_usd` = `total_cost_usd`；`permission_denials` 非空时原样写进 review 文档的 front matter，供人判断 reviewer 是否因权限漏看文件。

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

每个 kind 的 schema 存成一个 JSON Schema 文件，Claude 后端通过 `--json-schema` 直接使用，pi 后端只在包装脚本里校验；条件约束（如"ABANDON 时 `abandon_paper` 必填且须在 `closest_prior_work` 中"）JSON Schema 表达不全，一律由包装脚本再做确定性检查，`structured_output` 存在也不跳过。

正向判定定义照搬 ARIS：novelty 的 PROCEED 与 CAUTION 都算正向，只有点名论文的 ABANDON 是负向；critical_review 的"列出风险"不是否定，只有 `stance=abandon` 才是。ARIS novelty 的 **VERDICT LIMITS** 原文块放进 `novelty_precheck` 的系统提示文件。

## 4. 与现有角色、权限的关系

- `DOC_AUTHORS` 新增 `review: ("reviewer",)`；Leader 不能以 rld 身份登记 review 文档，只能通过 `review_call.py`。
- 两端各加一个工具入口 `research_review`（Claude 为 hooks 注册的 tool，Codex 为 MCP tool），内部执行 `review_call.py`；Bash guard 把直接调用 `pi` 和非交互调用 `claude`（`claude -p` / `claude --print`）列入拒绝项，避免绕过登记与追踪。
- `models.reviewer` 进入配置（见 01 §3）；与 `models.worker` 一样是三层证据：配置目标、实际请求（命令行）、运行证据（pi 的 `turn_end.model` / Claude Code 的 `modelUsage` 键）。
- 同一包装脚本也服务设计文档 D8（GO 候选的定向复核，kind=`candidate_recheck`），因此 B1 批次独立于 discovery 就有价值。

## 5. 风险与限制

- **跨模型族不是独立证据。** 两个模型同意不等于实验独立；跨模型评审只替代"Leader 自评"，不替代筛选实验。
- **两个基座的行为不完全对等。** 同一 brief 在 pi 与 Claude Code 下的默认系统提示、工具实现、读文件方式不同；review 文档记录 `backend`，比较不同 reviewer 的结论时要把基座当作一个变量。
- **pi 的 read 工具不限制路径。** brief 中只给研究目录路径，但不能把它当作隔离边界；需要更强隔离时按 pi `docs/security.md` 用容器运行。Claude Code 后端由 `--restricted` 限制在工作目录与 `--add-dir` 内。
- **Claude Code 的会话存在用户目录。** 会话文件落在 `~/.claude/projects/` 下，不在研究目录；包装脚本只记录 session id，项目归档时不包含 Claude 后端的会话原文（原始 JSON 结果仍在 `cache/reviews/`）。单轮评审用 `--no-session-persistence`。
- **`--safe-mode` 的范围随 CLI 版本变化。** 它是"关闭所有自定义"的总开关，新版本可能增减覆盖项；冒烟脚本每次升级 Claude Code 后检查 reviewer 会话没有加载插件 hooks（JSON 中无插件工具调用、`permission_denials` 无异常）。
- **两个基座的配置都属于用户环境。** 插件只依赖 `pi` / `claude` 在 PATH 且已登录；不替用户安装或登录。
- **费用口径不同。** pi 的 `usage.cost.total` 与 Claude Code 的 `total_cost_usd` 都按标价计算；订阅登录时后者是名义费用。pi 后端只做累计提醒，Claude 后端可额外用 `--max-budget-usd` 单次封顶；硬性总封顶仍需在 provider 侧设置。
- 实测规模：pi 两次最小调用（一次模型 404、一次成功），未测长 brief、`--tools read` 与多轮会话；Claude Code 五次最小调用（§1.2），未测长 brief 与预算封顶触发。
