---
title: "实施协议：阶段末 Fable 评审、Herdr 双宿主真实测试与模型配置"
stage: "实施过程"
status: "binding for the implementing agent"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
verified_on_host: "pi 1.0.4 列出 anthropic/claude-fable-5-1、anthropic/claude-sonnet-5-5、openai/gpt-6-luna；herdr 支持 kind=claude|codex|pi；HERDR_ENV=1；codex-cli 0.160.0；Claude Code 2.1.291"
language: "zh-CN"
---

# 14 实施协议

本文约束**实施本设计包的 agent**（下称实施者）。12 §1 的每个批次 M0–M8 完成后，必须按本文顺序执行：单元测试与构建 → Fable 5.1 评审并修复 → Herdr 双宿主真实测试并修复 → Fable 5.1 终审。未走完协议的批次不得报告为完成。

## 1. 每批次的固定顺序

```text
1. 实现批次内容（按对应阶段文件）
2. 单元测试 + 构建（§2）
3. 阶段末评审：Fable 5.1 新会话、只给路径（§3）→ 修复 CRITICAL/MAJOR → 重评，至多 2 轮
4. Herdr 真实宿主测试：Claude 与 Codex 各一个侧边 pane，加载最新构建的插件（§4）→ 修复 → 重建 → 重测
5. 终审：Fable 5.1 对本批次完整 diff 再评一次；无 CRITICAL/MAJOR 才算完成
6. 写测试记录与评审记录（§6），一批一个提交
```

共享集群上，测试与构建按平台规定在计算节点运行；Herdr 的 pane 继承实施者会话所在节点，重计算的步骤不得在登录节点执行。

## 2. 单元测试与构建

```bash
.venv/bin/python -m unittest discover -s shared/research-tree/tests
.venv/bin/python -m unittest discover -s tests
python3 scripts/build_plugins.py --target all
claude plugin validate dist/claude
claude plugin validate dist/claude/plugins/research-tree
.venv/bin/python -m unittest discover -s dist/codex/plugins/research-tree/tests -p test_codex_adapter.py
.venv/bin/python scripts/check_codex_install.py dist/codex
```

批次新增的测试编号（11 中的 M/E/U/B/K/R/X/O/T 系列）必须在这里全部通过；失败先查原因，不得放松断言。

## 3. 阶段末评审（Fable 5.1）

**调用方式**：新的非交互会话，不继承实施者上下文，只给文件路径：

```bash
pi -p --mode json --model anthropic/claude-fable-5-1 --thinking high \
   --no-session --no-extensions --no-skills --no-context-files --no-mcp \
   --tools read,grep,find,ls \
   --append-system-prompt plans/design/reviews/prompts/stage-review.md \
   "Review batch <Mn>. Design: plans/design/<阶段文件>. Changed files: <git diff --name-only 列表>. Tests: <测试文件>. Read everything yourself; executor notes are not evidence."
```

也可用 `claude -p --model claude-fable-5-1` 执行同一提示。brief 不含实施者的总结、解释或倾向性问题（09 §2 的 reviewer-independence 同样适用于实施评审）。

**评审内容**（系统提示文件固定这些维度）：

| 维度 | 检查 |
|---|---|
| 设计一致性 | 实现与对应阶段文件逐条对照；拟议接口、错误码、文档章节、配置键是否按文写 |
| 两端不漂移 | 共享核心只在 `shared/`；Claude 与 Codex 适配层的工具 schema、只读 allowlist、提示词语义一致 |
| 测试覆盖 | 11 中本批次编号的测试是否存在且真的测到该行为；夹具是否绕过生产入口 |
| 规则与文档同步 | 规则文件、README、配置模板、demo 是否随契约变化更新 |
| 回归 | 已有 109 个测试仍通过；旧项目迁移路径（10 §2） |

**输出**：JSON 列表 `{severity ∈ CRITICAL/MAJOR/MINOR, file, line, claim, evidence, suggested_fix}`。实施者修复 CRITICAL 与 MAJOR，MINOR 记录并说明处理；修复后重评。两轮后仍有 CRITICAL → 向用户报告，不自行降级。

评审原文与 JSON 存 `plans/design/reviews/<Mn>-r<k>.md`。

## 4. Herdr 双宿主真实测试

### 4.1 前置

```bash
test "${HERDR_ENV:-}" = 1 || { echo "not inside Herdr"; exit 1; }
python3 scripts/build_plugins.py --target all          # 最新插件
```

测试项目放在 scratch 目录，每批一个新目录：`<scratch>/rt-test-<Mn>-<host>/`。它包含：

- `plan.md`：一个研究方向 + 一条用户假说（种子）；M6 之前的批次可直接给两条假说；
- 一个秒级、CPU 的假训练框架（可从 `make_demo.py` 的合成指标逻辑改造：按 seed 产生指标文件、曲线、日志，支持 sanity 与多 seed），`platform.experiment` 写"在当前机器上运行"，不提交 PBS 作业；
- `research-tree.yaml`：§5 的模型矩阵；预算设成小值以便触发 alert 场景。

Codex 使用隔离的 `CODEX_HOME`（复制用户配置后改模型），避免污染日常配置；插件信任与 hooks 审阅按 `codex-plugin/research-tree/README.md`。

### 4.2 开 pane 并启动两个宿主

```bash
# 右侧：Claude Code
P1=$(herdr pane split --current --direction right --cwd "$T/rt-test-M3-claude" --no-focus | jq -r .result.pane.pane_id)
herdr agent start rt-claude --kind claude --pane "$P1" -- \
  --plugin-dir /abs/path/research-agent/dist/claude/plugins/research-tree --model claude-sonnet-5-5
herdr agent prompt rt-claude "/effort medium" --wait

# 下方：Codex
P2=$(herdr pane split --current --direction down --cwd "$T/rt-test-M3-codex" --no-focus | jq -r .result.pane.pane_id)
CODEX_HOME=$T/codex-home herdr agent start rt-codex --kind codex --pane "$P2" -- \
  --model gpt-6-luna -c model_reasoning_effort=medium
```

安装 Codex 插件在该 pane 内先执行 `codex plugin marketplace add /abs/path/dist/codex` 与 `codex plugin add research-tree@research-tree`（用 `herdr pane run` 在启动 agent 之前完成）。实际生效的模型以 `logs/agent_models.jsonl` 的 observed 记录为准，写进测试记录；与配置不符时按规则 §2 报告缺口，不静默换模型。

### 4.3 场景表

每个宿主按批次执行，每步用 `herdr agent prompt <name> "<命令或指令>" --wait --timeout <ms>`，读 `herdr agent read <name> --source recent-unwrapped --lines 200`，再用 `research_db` 的只读方法与 `build_site.py --check` 核对数据库与页面。

| 批次 | 场景（两端都跑） | 通过判据 |
|---|---|---|
| 所有批次 | prepare → init → 立项计划 → confirm → 根节点 worker 跑 sanity 与基线 → 冻结 | 数据库状态与阶段文件一致；页面 `check` 通过 |
| M1 | 结果文档数字与指标文件不符 | `STAT_MISMATCH` / 核验拒绝；无 Evaluation 写入 |
| M2 | 1 个 seed 轻微负向；达到 seed 上限仍接近门槛 | `inconclusive`；不强制剪枝 |
| M3 | 两个 worker 争用最后额度；提交状态 unknown | 只准入一个；不自动重提 |
| M4 | 候选复核：reviewer 可用 / 不可用 / 同族 | review 文档登记；`REVIEW_UNAVAILABLE`；R04 拒绝 |
| M5 | 假说文档缺 claim map；sanity 失败 3 次 | X01 拒绝；X06/X07 上报 |
| M6 | 只给方向 / 给种子假说 | 发现报告分两栏；用户假说进入查新；ABANDON 的用户假说待用户决定 |
| M7 | 运维噪声写入 lesson；经验要求扩权 | 被过滤；权限不变 |
| M8 | 组合节点从两个负向父节点派生 | 允许且记录关系 |

`blocked` 状态（权限提示或提问）先 `herdr agent get` 与 `agent read` 再决定输入；不要盲发回车。两端的会话结束后读取 `messages/`、`logs/` 与数据库快照作为证据。

### 4.4 修复循环

发现问题 → 改源码（只改 `shared/` 或对应适配层）→ 补测试 → 重建 → 在**新的**测试目录重跑受影响场景；不在已污染的项目目录上继续。同一问题修复两次仍复现 → 记入 obligation 式清单并向用户报告。

测试结束不关闭用户的 pane；实施者自己创建的 pane 在记录完成后可关闭。

## 5. 模型配置矩阵（测试阶段）

| 角色 | Claude 宿主 pane | Codex 宿主 pane |
|---|---|---|
| 主会话（RLD） | `claude-sonnet-5-5`，effort medium | `gpt-6-luna`，reasoning medium |
| `models.ui` / `models.worker` / `models.lens_assistant` | `inherit`，effort medium | `inherit`，effort medium |
| `models.reviewer`（pi） | `openai/gpt-6-luna`，thinking medium | `anthropic/claude-sonnet-5-5`，thinking medium |
| 阶段末评审（§3） | `anthropic/claude-fable-5-1`，thinking high | 同左 |

reviewer 与宿主主模型交叉配置是为了满足 `require_cross_family`；每个批次另跑一次"reviewer 与主模型同族"的反例，验证 R04 拒绝。pi 的 `usage.cost.total` 逐次累计进测试记录；`budget.review_usd_alert` 设小值以验证 R14。

## 6. 记录与完成标准

- `plans/design/reviews/<Mn>-r<k>.md`：Fable 评审原文、JSON、修复对照。
- `plans/design/test-logs/<Mn>-<host>.md`：命令、observed 模型、每个场景的判据与结果、失败与修复、pi 费用。
- 批次完成 = §2 全部通过 + §3 终审无 CRITICAL/MAJOR + §4 场景表两端全部通过 + 记录齐全。
- 任一项被跳过或阻塞，报告中明确写出，不得写成已完成。
