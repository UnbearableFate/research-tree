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

## 测试会话的 effort

实施文档 §0.1 与 §4.1 写“Claude Haiku 5.5 high”，§2.2 模型矩阵（用户在 `253d50d` 中最后修订）写 `claude-haiku-5-5` medium、
`gpt-6-luna` reasoning medium。以最后修订的 §2.2 为准：两端测试主会话都用 medium，`AGENTS.md` 与 `scripts/scenarios/record.py`
（MATRIX）按此登记，真实场景记录的 observed_effort 须等于它。

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

## 阻塞：Fable 5.1 不可用（2026-10-08 19:3x UTC 起）

S1 第 1 轮评审（`scripts/stage_review.py S1 --round 1`）返回 `is_error=true, terminal_reason=api_error`，原文
“Fable 5.1 requires usage credits. Switch to another model to continue.”（记录 `reviews/S1-r1-invalid-1.md`）；
随后单独探测同样失败（原始输出 `test-logs/blocked/fable-2026-10-08T1938Z.json`），`claude-haiku-5-5` 同时可用。
按实施文档 §2.2，不换模型：所有阶段评审与终审（S0 终审第 4 轮、S1 起各轮）为 **BLOCKED**，恢复条件是账户为
Fable 5.1 补充 usage credits。期间继续不依赖评审的实现、REG 与两端真实场景，评审在恢复后按顺序补做；
未完成终审的阶段不报告 PASS。

## 阶段矩阵

| 阶段 | REG与构建 | Claude真实SC | Codex真实SC | 独立终审 | 阶段状态 |
| --- | --- | --- | --- | --- | --- |
| S0 | PASS | PASS（a03） | PASS（a07；a04 FAIL 已修复，a05/a06 中止） | BLOCKED（Fable 不可用） | IN_PROGRESS |
| S1 | PASS（REG-S1-01..06，`test_identity.py`；已并入 `bug-fix-1008`） | a01 FAIL、a02 FAIL/BLOCKED（用量上限），已修复；a03 进行中 | a01 中止（夹具缺陷） | BLOCKED（Fable 不可用） | IN_PROGRESS |
| S2 | PASS（REG-S2-01..08，`test_confirmation.py`；分支 `s2-dev`） | NOT_STARTED | NOT_STARTED | BLOCKED（Fable 不可用） | IN_PROGRESS |
| S3 | PASS（REG-S3-01..07，`test_units.py`；分支 `s3-dev`） | NOT_STARTED | NOT_STARTED | BLOCKED（Fable 不可用） | IN_PROGRESS |
| S4 | PASS（REG-S4-01..08，`test_reviews_s4.py` 与 `test_review_call.py`；分支 `s4-dev`） | NOT_STARTED | NOT_STARTED | BLOCKED（Fable 不可用） | IN_PROGRESS |
| S5 | PASS（REG-S5-01..07，`test_memory_s5.py`；分支 `s5-dev`） | NOT_STARTED | NOT_STARTED | BLOCKED（Fable 不可用） | IN_PROGRESS |
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

## S1 真实场景记录

- Claude a01（`scenarios/S1/claude/*/a01`）：SC-COMMON-01 PASS；SC-S1-01/02/03 FAIL。原因：ToyOpt runner 不接受动量的
  `beta`、也不把它写进 manifest，导致每个 momentum 导入都被 `METHOD_SPEC_MISMATCH` 拒绝、节点没有评估，主张修订步骤因而
  无可绑定的复核；控制器让 agent 用 `method_config` 登记，故配置漂移故障没有可改的文件；Alpha 在改动之后才评审，未能
  检验“旧 revision 的回执失效”。另发现产品缺陷：`review_basis(candidate_recheck)` 缺 evaluation 时抛 TypeError。
  修复（`5dada4f`）：runner 把优化器选项作为真实设置并记录，未知设置使运行失败；`review_basis` 给出明确错误并加回归测试；
  控制器 v2（Alpha 改动前先评审、阻塞时重启、提交的配置文件、故障事件按 JSON 记录、结束时关闭 pane）。
- Codex a01：在身份步骤之前中止（同一夹具缺陷会使其后续步骤无效，Codex 周额度只剩约 25%），会话原文保存在
  `rt-S1-codex-a01.aborted-fixture.ctl/`，不形成记录。
- Claude a02（`scenarios/S1/claude/*/a02`）：控制器 v2。SC-S1-01 FAIL（Z4）：会话重启后 RLD 找不到发现流程命令（搜索文件系统、
  试用不存在的 `research_db.discovery_gate`），Alpha 新回执之后没有重跑发现门。修复（`523895a`）：每个 Claude 会话注入发现与文献
  命令，Codex 的 `research_control status` 返回同样的命令。21:16:49 起宿主会话达到账户用量上限（原文 “You've hit your session limit
  · resets 11:30pm (UTC)”），之后所有提示无回答：SC-COMMON-01、SC-S1-02、SC-S1-03 记 BLOCKED。控制器现在在宿主报告用量上限时立即停止
  并关闭 pane。注意：测试宿主与本实施会话共用同一账户额度。
- Claude a03：中止，不形成记录（证据在 `rt-S1-claude-a03.ctl/`）。重启后 RLD 仍找不到发现命令：注入行写在“项目已载入”分支里，
  新会话开头项目状态尚未载入，所以没有注入；它在文件系统里找到本实施会话早期 scratchpad 中的旧插件构建并运行了旧的
  `discovery merge`，把 candidates.json 改写成旧格式（编号互换、revision 丢失），随后停在提问对话框。修复：命令行无条件注入；
  删除旧 scratchpad 中的插件构建与登录副本；旧场景构建打包进 `rt-scenarios/archive/`，控制器在每次尝试结束时打包自己的构建；
  控制器遇到 agent 提问时记录并关闭对话框再继续。
- Claude a04（`scenarios/S1/claude/*/a04`）：**SC-COMMON-01 PASS，SC-S1-01 PASS**（Zebra 编号与 revision 不变；Alpha 改动后 revision 2，
  门因旧 revision 回执阻塞、重启并重新 merge 后仍阻塞；Alpha 当前 revision 的真实评审（pi，openai/gpt-6-luna）后门通过）。
  SC-S1-02/03 FAIL：控制器要求把方法配置写在 configs/，而 agent 冻结框架时把 configs/ 列入 harness_paths，它正确地拒绝了
  （会破坏框架核对），于是实验①–③没有登记、配置漂移故障无文件可改。控制器已改为 zebra/（框架之外）；a05 重测 S1-02/03。
