# 实施状态（证据一致性改进轮 S0–S7）

设计：[`plans/research-tree-implementation-and-real-scenarios.md`](../../research-tree-implementation-and-real-scenarios.md)。
状态取值见其 §1.3：`NOT_STARTED`、`IN_PROGRESS`、`PASS`、`FAIL`、`BLOCKED`。科研效能另记，不与工程验收合并。

## 基线（§0.2）

- 实施分支 `bug-fix-1008`，起点 `253d50d`（= 设计基线 `616d646` 之后的 `8c53648`（友好模型名）、`e0a5f7a`（移除旧设计包与
  `AGENTS.md` 单宿主限制）、`253d50d`（模型矩阵改为 Haiku 5.5））。旧设计包 `plans/design/0*-14*` 已由用户从工作树移除，
  需要时从 `616d646` 读取。
- 2026-10-08 起点测试：共享核心 316 项通过（`shared/research-tree/tests`）。
- 2026-10-08 模型预检（各一次实际调用）：`claude -p --model claude-haiku-5-5` → modelUsage `claude-haiku-5-5`；
  `claude -p --model claude-fable-5-1 --effort high` → `claude-fable-5-1`；`pi --model openai/gpt-6-luna:medium`
  → `gpt-6-luna`；`codex exec -m gpt-6-luna -c model_reasoning_effort=medium` → `gpt-6-luna`。宿主版本：Claude Code
  2.1.294、codex-cli 0.160.1、pi 1.0.4、herdr 0.8.2；机器 fern01（本地，32 核，无 PBS/GPU 使用）。

原始预检证据：[`S0-precheck/`](S0-precheck/)（各宿主 `--version`、`claude -p --help`、`codex exec --help`、
`pi --list-models`，以及四个模型各一次实际调用的原始 JSON / 输出）。

## 冻结的资源与运行边界（§3.4，S0 开发校准后冻结，适用于 S0–S6 每个阶段 × 宿主）

开发校准（[`S0-precheck/calibration/dev-calibration.json`](S0-precheck/calibration/dev-calibration.json)；开发训练
seed 7–9，仅 explore 切分，经 `tools/local_exec.py` 实测）：参考方法单次运行 CPU 0.057–0.062 s、墙钟 0.059–0.064 s，
按整秒记账为 1 node-second；momentum 变体同量级。正式 seed（42–44、1042–1044、2042–2044）与 c1/c2 未参与校准。

| 项目 | 上限 / 口径 |
| --- | --- |
| 单次运行 | `budget.per_run`：1 节点、10 分钟墙钟（实际约 0.06 s） |
| 每宿主每阶段训练次数 | ≤ 150 次实际启动（含 sanity、失败、重试与确认）；本地 CPU，无 PBS、无 GPU |
| 并发 | `max_parallel_workers: 2`；本地适配器同时 ≤ 4 个进程 |
| 阶段墙钟 | 每宿主每阶段场景 ≤ 6 小时会话时间；超过即记录 BLOCKED 原因 |
| 原生 agent 回合 | 控制器以用户身份的输入 ≤ 60 条 / 宿主 / 阶段；agent 内部回合不设上限，按实际记录 |
| 产品 reviewer 调用 | ≤ 40 次 / 宿主 / 阶段；`review_usd_alert` 默认 null（提醒阈值，不是硬封顶），费用按后端回报逐次入账：pi `usage.cost.total`、Claude Code `total_cost_usd` |
| 阶段评审 | Fable 5.1 high：每阶段至多 3 轮评审 + 1 次终审（单次约 6 USD，按 `total_cost_usd` 记） |
| 修复轮数 | 同一问题两轮修复仍复现即按 §2.6 报告 |
| 费用口径 | 已知费用按宿主/后端原始回报；交互式宿主会话本身的费用若无原始回报则记 unknown，不以 token 估算代替 |

S7 的比较预算另列，不占用以上额度。

## 阶段矩阵

| 阶段 | REG与构建 | Claude真实SC | Codex真实SC | 独立终审 | 阶段状态 |
| --- | --- | --- | --- | --- | --- |
| S0 | PASS | PASS（a02） | PASS（a02；a01 FAIL 已修复） | IN_PROGRESS | IN_PROGRESS |
| S1 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S2 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S3 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S4 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S5 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S6 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S7 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |

科研效能：`not_evaluated`。

## S0 REG 映射

| REG | 测试 |
| --- | --- |
| REG-S0-01 | `tests/test_scenarios.py::GeneratorTest.test_reg_s0_01_same_inputs_same_project_and_nothing_old` |
| REG-S0-02 | `tests/test_scenarios.py::ScorerTest.test_reg_s0_02_scorer_recounts_and_ignores_reports` |
| REG-S0-03 | `tests/test_scenarios.py::RecordTest.test_reg_s0_03_missing_parts_cannot_pass` |
| REG-S0-04 | `tests/test_scenarios.py::RecordTest.test_reg_s0_04_substitutes_are_not_real_scenarios` |
| REG-S0-05 | `tests/test_scenarios.py::GeneratorTest.test_reg_s0_05_material_identities` |
| 适配器 | `tests/test_scenarios.py::AdapterTest`（同 key 单进程、回执丢失按 key 找回、额外启动计数） |

## S0 §4.4：`plans/real-run-error.md` 缺陷修复

| # | 缺陷 | 处理 | 测试 |
| --- | --- | --- | --- |
| 1 | 配置只接受模型 ID | 已由 `8c53648` 修复（易读名称解析） | `test_project_config`、`test_codex_adapter` 中既有用例 |
| 2, 14 | research_tree.py 必须在项目目录运行 | `find_project` 自当前目录向上找 `.research-tree.json`（research_tree.py、review_call.py） | `test_research_tree.RealRunFixesTest.test_tools_find_the_project_from_a_subdirectory` |
| 3 | 文献服务 429 | 跨进程共享的节流记录（文件锁）、遵守 Retry-After、限流后的冷却对后续进程生效 | `test_literature.…test_rate_limit_pacing_is_shared_between_processes` |
| 4 | platform.skills 名称与已安装技能不符 | init 核对已安装技能，未找到的连同相近名称写入 marker（`skills_check`），两端立项提示要求在计划中指出、由用户决定 | `test_research_tree.…test_unknown_platform_skills_are_reported_with_close_names` |
| 5 | help 不列可选参数 | `OPTIONAL_PARAMS`；`help` 返回 `optional_parameters`，与 `_only_fields` 同源 | `test_research_db.HarnessSanityFirstTest.test_help_lists_optional_parameters` |
| 6, 13 | UI 消息重复投递 | 排队的转交在提交前核对 inbox，已回执则不再投递；提示 RLD 先核对；UI 交回只写“已处理” | `register.test.ts`：“a message the RLD already answered is not delivered a second time” |
| 7, 11 | 缺 pdftotext | `literature.py text` 回退到 pypdf（加入项目依赖），文本仍经注入过滤 | `test_literature.…test_pdf_text_without_pdftotext_uses_pypdf_through_the_filter` |
| 8 | 并行助手共用 scratchpad | 规则：派发时指定各自子目录 | 规则文本（无行为测试） |
| 9 | `--user-hypotheses` 与 `--artifact` 基准不一致 | 统一按研究根目录解析，再试项目目录与调用目录，找不到时报出三处 | `test_research_tree.…test_tools_find_the_project_from_a_subdirectory` |
| 10, 12 | 评审超过宿主 600 s 进程上限 | `review_call.py --background` 以分离作业运行，在上限内等待；超时返回 ticket，`research_review(ticket)` 取回；两端 schema 同步 | `test_review_call.…test_background_review_outlives_the_host_process_limit` |
| 15 | 发现门要求 artifact 而说明未提 | `discovery set … done` 缺 artifact 或文件不存在即拒绝并给出示例；两端提示写明 D5–D7 的 artifact | `test_discovery.StateTest.test_review_stage_acceptance_needs_another_family` |
| 16–18 | config apply 与 RLD 登记的指标规范漂移 | 以项目记录中的现行规范为准：内容一致则接管，不一致则拒绝并逐项列出差异；用户可 `config apply --replace-metric-spec` 决定以文件为准；不再静默回退 | `test_research_tree.…test_config_apply_does_not_revert_the_rlds_metric_specification` |
| 19 | sanity 前必须冻结框架 | 允许根节点框架的 sanity 先于冻结；其他实验仍要求冻结 | `test_research_db.HarnessSanityFirstTest.test_sanity_before_freeze_only` |

## S0 评审遗留与延期

- 私有确认材料（§11.4）的生成边界：S0 生成器只产生非盲功能测试材料（`scenario.json` 记 `blind: false`），私有模式在 S7 实现（S0-r1 MINOR）。
- REG-S0-05 中“同一材料改显示名不能变成未使用材料”在 S0 只验证“身份 = 内容哈希”；经材料使用记录的行为在 S2 的 REG 中验证（S0-r1 MINOR）。
