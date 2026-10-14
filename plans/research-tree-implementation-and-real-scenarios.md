---
title: "research-tree 改进实施设计与双宿主真实场景验收"
prepared_on: "2026-10-08"
language: "zh-CN"
status: "待实施，场景尚未执行"
source_branch: "new_feature/from_ARIS"
source_commit: "616d6463eb397a8cfbbf88262d46b0d0e4a7c964"
pre_upgrade_commit: "48b3841d97275b2e9ad010d91d261acc9c7c4f5c"
suggested_repository_path: "plans/design/15-evidence-integrity-and-real-scenarios.md"
---

# research-tree 改进实施设计与双宿主真实场景验收

本文交给负责实现 research-tree 的 agent 执行。目标是修复候选、证据、评审、记忆和预算之间的一致性缺口，并用真实宿主工作流验证修复。实施分为 S0–S7；每个阶段完成前，都必须在全新的虚构项目中，分别使用 Claude Code 和 Codex 运行该阶段的真实场景。

虚构的是研究项目及其合成数据；宿主模型调用、插件加载、CPU 训练、文件产物、评审、资源记账及会话恢复必须实际发生。预设数值、模型替身和回执注入用于确定性测试，单独标注，不代替真实场景验收。

本文件提供设计、实现入口、迁移规则、场景步骤和验收条件。所有新增接口名、配置项及错误码均为待实施契约，不表示基线代码已提供这些能力。实施时优先复用等义接口，并同步工具 schema、提示词、配置模板、迁移文档与测试。

用例清单包含 55 组确定性回归、25 个阶段专属真实场景，以及每阶段两端共有的 SC-COMMON-01。一个 REG 编号可以包含多个参数化断言；一个 SC 可以包含多次实际运行，不能把编号数量当作训练或模型调用预算。

## 0 实施依据与范围

### 0.1 本轮明确要求与旧协议的关系

本轮用户明确要求：**每个阶段末，Claude Code 和 Codex 都必须测试。** 该要求优先于当前 `AGENTS.md` 中“阶段最终测试只针对 claude-mod”的范围限制。`claude-mod/` 是仓库的 Claude 适配层目录，真实宿主仍是 Claude Code；不要把目录名当作必须存在的 CLI 命令。

沿用 [14-implementation-protocol.md][R14] 的验收顺序，并补齐其固定步骤表中没有单独列出的终审步骤：

1. 实现本阶段，增加针对缺陷的回归测试。
2. 单元与集成测试、两端构建及适配器检查。
3. Fable 5.1 新会话独立评审，处理 CRITICAL / MAJOR。
4. Claude Code 与 Codex 各自从新项目运行真实场景；发现问题后修复、重建，在新项目重测受影响场景。
5. 对最终代码与两端场景原始证据进行 Fable 5.1 新会话终审。
6. 归档证据和遗留项；阶段验收通过后提交该批次。

Claude 测试主会话使用当前 `AGENTS.md` 指定的 Haiku 5.5 high；Codex 与跨族 reviewer 沿用 14 的相应配置。真实测试采用实际 CPU 指标，替换旧协议允许的“假训练主指标公式”作为正常验收依据。旧协议中“M7 运维噪声必须被过滤”更新为 S5 的用途区分：故障事实与已验证修复可以保存，无依据的永久结论仍需拒绝或降级。

除上述明确调整，本文件不撤销已有用户决定边界、插件权限、评审独立性或证据保留要求。测试控制器只在隔离的虚构项目内扮演场景定义的用户；不得用这些测试指令授权真实科研项目的预算或权限。

### 0.2 基线与已知状态

设计基线为 `616d6463eb397a8cfbbf88262d46b0d0e4a7c964`，于 2026-10-08 经 GitHub 核对。上一轮本地审阅运行的共享核心 311 项、Codex 适配器 24 项、打包及 benchmark 10 项测试均通过；该事实不代表本文件的新场景已经通过。

已复现的主要缺陷包括：相同代码调参后复用确认 seed、无关确认 baseline 被选中、历史单位被新 MetricSpec 重解释、复核细项失败但总体通过、候选重排或 claim 扩大后旧回执继续有效、计划中的 run 支持 verified lesson、finding 未随来源失效、预算池覆盖。

若实施开始时分支已前进，先对本文件涉及的函数和契约做定向差异检查，记录当前基线；已修复项仍需对应回归用例，不能机械重复实现。保留用户已有改动，使用独立工作分支或 worktree。

### 0.3 交付边界

必交付：S0–S7 的源码、必要迁移、测试、提示词和文档同步；每阶段双宿主真实场景记录；最终证据与缺陷追踪表。

本轮不以“系统必须取得正科研收益”作为通过条件。S7 的小规模匹配 pilot 用于检验评测能否真实运行、计量是否正确，以及观察效果；论文级科研优势需要另行充分重复。现有 105 次 A/B/C 提案不能因本文件的阶段验收通过而被追记为已执行。

### 0.4 建议阅读顺序

`AGENTS.md` → 本文件 → `14-implementation-protocol.md` → `04`、`05`、`06`、`07`、`08`、`09`、`10`、`11` 对应章节 → 当前源码与测试。使用现有 CodeGraph（若环境提供）辅助定位，具体调用和结论仍需源码核对。

## 1 全局不变量与实施路线

### 1.1 必须成立的不变量

| 编号 | 不变量 |
| --- | --- |
| INV-01 | 评审通过必须对应一个明确对象和版本；标题、列表位置或代码 SHA 单独不足以表示所有科研对象。 |
| INV-02 | 确认实验必须验证已冻结的同一候选，并与同一参考方法的确认实现比较。 |
| INV-03 | 确认材料的使用历史跨节点保留；改名、换节点或保持代码不变调参，不能清除已经发生的确认反馈。 |
| INV-04 | 原始数值的单位与来源解释不可被后来的配置静默重写。 |
| INV-05 | review 的总体通过必须满足所有适用的必需检查项；合法的负面评审应被保存并阻止放行。 |
| INV-06 | verified lesson 来自已完成的适用验证；finding 的当前可用性由来源证据与 scope 派生。 |
| INV-07 | reservation 的预算归属与批准实验一致；unknown 提交保留占用并对账，不能静默重提。 |
| INV-08 | 所有“真实场景通过”均可由原始会话、运行文件与只读独立检查共同确认。 |
| INV-09 | 历史结果保留；重新解释、撤回、迁移或失效通过新状态/新版本表达。 |
| INV-10 | 拒绝路径不产生半写入：不得留下可用 Evaluation、有效通过回执、额外作业或错误预算扣账。 |

### 1.2 阶段与依赖

| 阶段 | 核心实现 | 依赖 | 阶段末两端必跑 |
| --- | --- | --- | --- |
| S0 | 真实 CPU 虚构项目、场景控制器和证据记录底座 | 无 | 正常初始化、sanity、基线、导入、评估、恢复 |
| S1 | 科学候选身份、claim revision、稳定 Discovery ID 与回执绑定 | S0 | 候选重排、claim 扩大、配置变化、无关执行参数变化 |
| S2 | 独立确认、正确基线、确认暴露与重试语义 | S1 | 正确确认、错误基线、确认后调参、重命名绕过、执行故障重试 |
| S3 | 原始单位、历史重评、独立性字段与兼容迁移 | S1 | 单位转换、元数据不一致、旧证据迁移与正常再准入 |
| S4 | review 一致性、证据引用、模型家族与补查闭环 | S1–S3 | 真实数字复核、claim 范围、补查、后端不可用及同族拒绝 |
| S5 | 可验证执行经验、finding 适用性与恢复消费 | S1、S3、S4 | 真实故障修复、未执行证据拒绝、协议变化、恢复后复用 |
| S6 | 预算池、unknown 对账、重试与重复作业计量 | S0、S2、S5 | 并发争用、跨池覆盖拒绝、真实进程回执丢失、恢复对账 |
| S7 | 有限重复建议、发现依据、评测协议修正及匹配 pilot | S0–S6 | 高噪声决策、零效应报告、组合/竞争解释、真实小规模比较 |

可并行准备不冲突的测试与设计，但阶段完成状态必须遵守依赖。每个阶段使用 `REG-Sn-xx` 标识确定性回归、`SC-Sn-xx` 标识真实宿主场景，不复用旧 M/E/R 等编号。

### 1.3 完成状态

使用 `NOT_STARTED`、`IN_PROGRESS`、`PASS`、`FAIL`、`BLOCKED`。`PASS` 只表示本阶段实现与验收条件满足。`BLOCKED` 必须写出实际阻塞、原始错误、已完成项和恢复所需条件；不能算作通过。

每个阶段的源码、两端构建、确定性测试、Claude 场景、Codex 场景和独立终审分别记录状态。任一必需项未通过，该阶段不能完成。科研效果另记为 `not_evaluated / pilot_only / supported_under_protocol / not_supported / inconclusive`，不与工程验收状态合并。

## 2 每阶段真实验收协议

### 2.1 三类证据的边界

| 类型 | 可使用的手段 | 能证明什么 |
| --- | --- | --- |
| 确定性回归 REG | 固定数值、reviewer 替身、原始回执变异、精确并发屏障 | 接口约束、事务回滚、异常分支与计算正确性 |
| 真实宿主场景 SC | 原生 Claude/Codex、真实模型、真实插件、CPU 子进程与实际文件；允许预先声明的输入/传输故障 | 完整用户路径能否执行、识别问题、恢复并产生可核对状态 |
| 科研效能 pilot | 冻结任务与资源、隔离评测器、真实完整研究重复 | 在指定小样本协议下的效果与成本观察 |

真实 SC 不得用 canned model response、本地 Responses 替身、直接写 DB、预填 review=pass 或预置 GO 代替产品链路。真实模型未给出预期判断时应保存实际结果并分析，不能改写回执。确切的畸形 JSON 接受规则由 REG 保证，真实 SC 通过提供有问题的研究材料检验 reviewer 及后续动作。

### 2.2 双宿主与模型矩阵

| 角色 | Claude Code 验收 | Codex 验收 |
| --- | --- | --- |
| 测试主会话 / RLD | `claude-haiku-5-5`，medium | `gpt-6-luna`，reasoning medium |
| UI / worker / lens | inherit 已观测的主会话模型；记录有效 effort | inherit 已观测的主会话模型；记录有效 effort |
| 产品 reviewer | `openai/gpt-6-luna`，thinking medium，通过 Pi | `anthropic/claude-haiku-5-5`，thinking medium，通过 Claude Code CLI |
| 阶段代码评审及终审 | `claude-fable-5-1`，high，新 Claude Code 会话 | 同一次阶段评审覆盖两端代码与各自证据 |

真实测试使用新启动的测试 agent，不继承实施者的“已经通过”结论。阶段代码评审只给设计、源码、测试和证据文件路径与中性目标，由 reviewer 自行读取。保留 14 的严格成功判据：Fable 原始响应 `is_error == false`、`terminal_reason == "completed"`，且实际 `modelUsage` 对应指定模型；CLI 差异在 S0 用当前 `--help`、模型清单与实际响应确认，不能只因进程 exit 0 就认定评审完成。

如指定模型或宿主实际不可用，记录 BLOCKED，完成不依赖该项的工作后报告；不得自行换模型并宣称原要求通过。接收实施任务时已有的模型、资源与权限授权持续有效，同一范围内不重复申请。

### 2.3 构建与安装

优先复用 [14][R14] 和当前 README 中的命令。以下是基线已有检查；S0 确认当前版本参数后执行并记录实际命令：

```bash
.venv/bin/python -m unittest discover -s shared/research-tree/tests
.venv/bin/python -m unittest discover -s tests
python3 scripts/build_plugins.py --target all
claude plugin validate dist/claude
claude plugin validate dist/claude/plugins/research-tree
.venv/bin/python -m unittest discover -s dist/codex/plugins/research-tree/tests -p test_codex_adapter.py
.venv/bin/python scripts/check_codex_install.py dist/codex
```

增加并运行 Claude 适配层现有及新增测试，依据 `claude-mod/` 当前布局定位。原协议中的“109 项”不是固定验收数量；记录实际发现数量与缺陷用例映射，防止删除用例后仍用旧数字说明通过。

Claude Code 加载本次 `dist/claude/plugins/research-tree`。Codex 按当前适配器 README 安装本次 `dist/codex`，核对已生效插件路径和缓存刷新。不能直接安装仅含适配层的源码目录，也不能只更新源文件后复用旧安装包。

每次测试记录源码 commit、未提交变更清单、构建标识/路径、宿主实际加载路径和版本。执行器尽量保留构建时源码快照或完整变更补丁，保证最终提交与被测内容能对应。

### 2.4 Herdr 与项目隔离

优先按 14 在 Herdr 中为两个宿主各创建独立 pane。每个 `stage × host × attempt` 使用新目录，例如 `<scratch>/rt-S2-codex-a02/`；只复制静态项目生成输入，不复制已通过的数据库、实验结果、评审或模型记忆。

修复后重测使用新项目；同一场景专门测试 resume 时，应保留原项目数据，结束会话后在该项目新开会话恢复。两种情况不能混淆。

Codex 使用受支持的隔离配置与插件安装目录，Claude 使用独立测试会话；复用既有授权登录，不修改用户日常全局模型或插件配置。Herdr 的 pane 继承节点，集群上的训练与较重测试放在符合平台规则的计算节点。虚构项目采用本地执行适配器，不提交 PBS 或占用 GPU。

遇到 blocked，先读取真实提示再处理。需要测试用户输入的地方，由控制器通过正常用户入口提交本场景已定义的输入；不得用直接改 DB 的方式制造同意。

### 2.5 每阶段共有场景 SC-COMMON-01

两个宿主都执行以下完整前缀和后缀，阶段专属 SC 插入其中：

1. 从 `plan.md` 的研究方向和一个用户假说开始，实际执行 prepare、init、立项与确认。
2. 根 worker 运行真实 sanity、至少一组正常基线；生成 manifest、metrics、曲线、日志、模型和用量文件。
3. 经插件生产入口导入、评估；控制器独立读取模型/预测/计数重算主指标，并核对 DB。
4. 执行本阶段专属场景，包括正常路径和预先声明的异常输入。
5. 结束主会话，在同一项目新会话按插件支持的恢复入口继续；不得再提交已完成或 unknown 的同一工作。
6. 实际生成站点后运行 `build_site.py --check`；核对页面与数据库版本、节点状态和待处理项。
7. 保存原始会话、观测模型、review 回执、运行产物、用量和只读状态快照。

控制器的预期值来自独立计算或输入身份关系，不能只把产品输出复制为 expected。共有场景至少验证一个业务状态经恢复后保持一致；各阶段另有专属恢复断言。

### 2.6 修复与阶段终审

失败时先定位是环境、测试设置、模型输出、产品契约还是科研无收益。保留失败记录；修复源码并增加最小回归用例，重建后在新目录重跑受影响场景。若修改共享契约，两端均重测该契约；已验证且不受影响的其他场景不机械重复。

最终代码有变化时，受影响测试结果必须更新。终审读取最终变更和两端全部必需证据，检查未关闭 CRITICAL / MAJOR。两轮修复仍重复出现的重大问题按 14 记录并报告，不把阈值或断言改到通过。

## 3 贯穿各阶段的虚构研究项目

### 3.1 项目 ToyOpt Lab

研究方向：在一个小型合成二分类任务上，比较优化器、学习率和微批处理策略对学习效果与执行成本的影响。用户假说：在固定数据与更新预算下，带动量的方法可能比当前参考方法收敛更快。

复用并扩展现有 [`scripts/make_rt_test_project.py`][RGEN] 的纯 Python logistic regression，避免建立第二套测试工程。正常实验实际计算梯度与参数更新，保存可再次加载的模型；accuracy 必须由预测与标签计数得到，loss 必须由实际模型输出得到。

初始参考方法可以选为在开发集上校准的欠拟合设置，以便确认路径有可达正例，但必须在正式场景前冻结。它只是虚构项目的已声明参考方法，不能称为外部学术 SOTA。不得查看正式确认结果后调 baseline 或 GO 门槛。

### 3.2 固定输入与产物

复用现有小数据规模作为起点，例如 16 特征、1200 训练样本、400 开发验证样本；sanity 采用更小固定输入。扩展生成器，明确产生固定训练集、探索验证集、确认集 C1 和确认集 C2。C1/C2 使用相同任务生成规律，但具有独立样本/标签实例、稳定切分身份和不同于探索集的内容；不能继续让所有训练 seed 共用原有单一验证集。

训练随机 seed 与评测数据生成 seed 分开管理。正常搜索训练 seed 可使用 `[42,43,44]`，C1 配套训练块如 `[1042,1043,1044]`，C2 如 `[2042,2043,2044]`；确认材料身份同时包含相应数据切分与训练 seed 块。具体数据量、实例、块数和资源在 S0 开发校准后冻结，不查看正式确认结果后再选。C2 预留给后续新候选，不能只凭更换训练 seed 宣称得到新数据。

S0–S6 的功能场景可由控制器保管生成清单，并明确记为非盲功能测试；未向研究决策交付的材料与已使用材料分别记录。S7 另启私有材料模式，生成输入和访问边界满足第 11.4 节。公开固定 seed 的旧验证集不能仅换一个目录就升级为盲评确认材料。

每次运行必须包含：

| 产物 | 内容与独立检查 |
| --- | --- |
| `run_manifest.json` | 实验/attempt、有效配置、代码、数据/协议、seed、原始单位、计数、运行状态及产物路径；S1 起补齐 method spec，S2 确认运行再绑定 candidate spec/batch |
| `metrics.json` | 实际计算的 accuracy/loss/时间等；不得写 `baseline + candidate_bonus` 形式的功能分数作为实测指标 |
| `predictions.jsonl` 或等效文件 | 样本 ID、预测与允许公开的标签；控制器可重算 correct/n |
| `model.json` 或现有模型文件 | 可被独立 scorer 加载的模型参数 |
| `curve.json` / `curve.csv` | 实际 step 与 loss 序列，数组长度与训练步数一致 |
| `train.log` | 启动参数、开始/结束、错误和实际执行摘要 |
| `usage.json` | 实际进程时间/墙钟与资源口径，执行适配器产生，不能用请求上限冒充实耗 |

协议注明“合成数据上的真实计算”。沿用现有合适的 eval_type 并明确其限制；任何公式数值场景标记 `simulation_only` 或 REG，绝不混入正常实测结论。

### 3.3 故障注入的允许范围

允许在正式运行前声明：错误 baseline 引用、配置修订、缺失单位字段、错误报告数字、一次输入文件路径错误、一次提交回执丢失、受控环境退出、并发争用。故障清单保存为 `fault-plan.json`，说明目标、触发点、次数和不变条件。

不制造真正系统 OOM。S5 的真实故障采用确定可恢复的文件路径/依赖错误；OOM 语句的接纳规则用 REG 文档测试覆盖。需要显存数值如 40/42 GiB 时只在 REG 使用；真实 CPU 场景使用可核对的模型文件字节数或其它实际测量值检验相同单位机制。

### 3.4 资源与运行边界

S0 先以不进入正式评分的开发数据/seed 测量单次 CPU 成本，再冻结所有阶段通用或逐阶段预算。记录：单 run 上限、每宿主训练次数、并发数、阶段墙钟、原生 agent 回合数、产品 reviewer 调用数、评审修复轮数及费用口径。

采用接收实施任务时已授权的预算；缺少必要额度时先形成一次性可审阅的阶段计划再确认，不逐阶段重复申请同一范围。提醒阈值与实际封顶分开：`review_usd_alert` 不是硬封顶，未知账单也不能记为零。异常重试、确认、失败和预备成本均单独保留并纳入相应资源总额。

常规场景限制为本地少量 CPU 进程。阶段 S7 的比较预算单列，不能挤占已有阶段修复预算或套用原提案的 1050 USD 建议额度作为授权。

## 4 S0 建立可重复的真实验收底座

### 4.1 实现与产物

在 `scripts/` 的测试工具范围内扩展现有项目生成器；可采用 `scripts/scenarios/` 保存计划、故障清单、控制器和独立观察器。生产插件继续负责状态与规则，测试执行适配器负责本地子进程与用量，职责与现有平台技能边界一致。

S0 交付：

- 可参数化的静态项目生成器，支持 host、stage、case、实例身份和全新输出目录；分别登记训练随机 seed、训练/探索/C1/C2 切分身份，并支持 S7 的私有生成输入边界。
- 一份固定项目计划与正常真实训练入口，至少能完成 sanity、基线、导入和评估。
- 场景结果记录器与只读观察器；输出见第 12 节的记录格式。
- 可按 submission key 追踪本地进程的轻量测试执行适配器，为 S6 留出“已启动但回执丢失”的受控触发点。
- 更新 14、README 的本轮协议说明，并将 `AGENTS.md` 中冲突的单宿主测试范围更新为每阶段双宿主必需；写明 Claude high、正常 SC 使用真实测量与阶段后终审。

### 4.2 确定性回归

| ID | 输入与断言 |
| --- | --- |
| REG-S0-01 | 两次相同静态输入生成相同数据/配置语义；新目录不含旧 DB、评审或结果。 |
| REG-S0-02 | scorer 从模型和数据独立计算 correct/n，与正常训练产物一致；修改报告数字不会改变 scorer 的结果。 |
| REG-S0-03 | 场景记录缺失 host、observed model、实际命令、原始证据或恢复记录时不能汇总 PASS。 |
| REG-S0-04 | mock reviewer / 预设分数结果只能归为 REG/simulation，不能通过真实 SC 的证据分类校验。 |
| REG-S0-05 | 探索、C1、C2 的样本/标签实例及切分身份不同；改变训练 seed 不改变切分身份；同一材料改显示名不能变成未使用材料。 |

### 4.3 真实场景

**SC-S0-01 正常项目从立项到可恢复评估**

- 初始条件：每个宿主一个全新 ToyOpt Lab，使用本次构建插件与冻结模型矩阵。
- 用户输入：研究方向和一条假说；允许当前机器上的小规模 CPU 试验。
- 步骤：执行 SC-COMMON-01；控制器检查 worker 实际 PID、模型文件与非空 loss 曲线；恢复后请求当前 baseline 和下一步。
- 预期：两端均得到由实际 run 构成的基线 Evaluation；恢复识别已完成 run，不重复执行；当前页面与 DB 一致。
- 证据：完整会话、baseline 的原始文件、scorer 复算、恢复前后 run/attempt 数和作业记录。

**SC-S0-02 报告错误与真实数值分离**

- 从同一正常模型生成一份故意写错 accuracy 的报告，输入事实记录在故障清单。
- 通过正常产品入口尝试登记/评估；预期被现有数值核验拒绝或明确要求修正，不产生以错误数字为依据的有效 Evaluation。
- 修复报告后重新提交，结果与原始 scorer 一致；保留前后记录。

### 4.4 BUG修复

修复plans/real-run-error.md记录的bug,并完成测试

S0 完成条件：两端 SC-S0-01/02 与共有场景通过，Fable 终审确认场景底座没有用直接 DB 写入或模型替身制造成功。

## 5 S1 统一科研对象身份与评审依据

### 5.1 最小数据契约

优先扩展现有 Experiment、Hypothesis、Document 和 Discovery JSON，不新增独立知识图谱服务。

| 对象 | 新增或明确的最小信息 |
| --- | --- |
| 方法身份 | `method_spec_id` 及不可变 spec 快照：code_ref、method、解析后的有效方法配置、训练数据/预处理/实现环境中影响结果的声明项、比较协议身份；创建时不需要运行结果 |
| 冻结候选 | `candidate_spec_id`：指向已有 method spec、据以选择的搜索 Evaluation、相关 claim revision 与参考方法；由 S2 的 `freeze_candidate` 建立 |
| 研究主张 | `claim_revision`：statement、Claim map、论证/适用范围和相关目标文档版本；纯显示排版可规范化 |
| Discovery 候选 | 永不按排序重编号的稳定 `candidate_id`，内容 `revision`，文献与选择状态分别可追踪 |
| review 依据 | 由系统在发起评审时写入的 `basis`：适用的 method spec、已存在的冻结 candidate spec、claim、evaluation、discovery revision 与 literature dossier revision |

两类 spec 均优先用已有文档 ID 指向不可变 JSON，并可查看内容差异。`create_experiment` 根据有效配置自动建立或复用 method spec；baseline、sanity、search 均可在没有搜索结果和冻结候选时创建。`freeze_candidate` 只记录从已有搜索证据选中了哪个方法，不向原 method spec 事后补写结果。指纹只做身份索引，不代替保存原配置。未知配置字段默认视为科学配置，只有预先声明的纯执行字段可排除。

科学配置包含学习率、优化器、训练步数、有效 batch、训练数据版本/预处理、模型结构等。排除输出路径、节点申请、walltime、提交键及搜索/确认阶段标签；训练 seed 和本次开发/确认评测切分属于验证材料计划，另行绑定，不能因为合法切换确认材料就把同一方法误认成新方法。比较协议仍约束指标定义与评测过程。若运行环境、精度或设备类型可能影响结果，应按协议保留对应身份，不能统一归为纯执行参数。

当前 `config_hash` 包含 stage 和资源字段，不能直接作为跨阶段身份。配置文件在实验创建时解析为有效配置并保存；实际 runner 产物必须回报相同科学配置，避免登记后文件被改变而身份仍旧。

### 5.2 版本更新和失效规则

- `update_hypothesis` 的科研内容改变生成新 claim revision；仅对明确定义的结构字段、换行和排版规则做确定性规范化，规范化后完全相等的重复提交幂等。不得由模型判断“语义没变”而跳过 revision。
- Discovery merge 保留原稳定 ID。新候选得到新 ID；没有明确来源身份的重新生成不能仅因标题相同继承旧 review。去重保留来源，不把不同机制强行并成一个已评审对象。
- 内容变化递增 revision。显示排序变化不改内容 revision；selected 集合变化使最终 gate 重新计算，但未变候选的内容 review 可复用。
- review 的 basis 由调用时快照决定，不能由 reviewer 自报覆盖。模型返回期间对象改变，该回执可归档，但标记 stale，不能获得当前通过资格。
- numbers/protocol 绑定所评 Evaluation；method-code 至少绑定 method spec 与相应 claim；novelty/theory 绑定 claim、method spec 及其所需的文献/论证版本。冻结后需要验证“所选候选”的评审再绑定 candidate spec，不能要求创建首次实验前已有冻结候选。
- 所有依据消费者同时更新：`candidate_recheck`、提交前 `code_review`、相应 waiver、RLD novelty/theory decision。明确修改 `_latest_code_review`、`_check_ready`、`_recheck_bound`、`decide` 和 eligibility；不只修 `_candidate_rechecks`。decision 与 waiver 的 basis 也由系统捕获，旧同 code clear 或 RLD pass 不能放行新科学配置/相关 claim。waiver 仍受现有 reviewer unavailable 条件约束。
- sanity 绑定目标 method spec 与实际 harness。允许协议明确的小样本/短训练 sanity projection：保存目标身份、允许的 overrides 和实际 sanity method spec，验证其他相关字段一致；不能要求 sanity 的 epoch 数等于正式训练，也不能把任意同 code 的 sanity 视为满足新配置。仅 claim 文本改变而未影响 sanity 的检查内容时，不无故重训 sanity。
- gate 重新查询当前 basis，不只读取以前保存的 PASS。失效传播到 candidate_ready/confirmed/GO eligibility 和后续 finding 使用状态。

### 5.3 迁移

旧 candidate ID 保留为 legacy alias，不把旧位置编号自动认作内容身份。只有保存了足够原始候选内容、claim 与 code/config 的记录，才能建立可证明的旧版本绑定；其余 review 标为 `needs_recheck`，历史原文保留。只读显示旧项目仍可运行，当前放行不得依赖无法重建依据的旧回执。

新建实验不得缺少完整 method spec；仅确认实验额外要求冻结 candidate spec 和 batch。旧实验的历史数据允许保留为 `legacy_unbound`，在升级到当前资格时要求补齐可验证依据。迁移事务需幂等，不能每次打开项目生成新 revision。

### 5.4 回归与真实场景

| REG ID | 必测断言 |
| --- | --- |
| REG-S1-01 | baseline/sanity/首次 search 无搜索结果也能创建 method spec；同 code、不同学习率产生不同 method spec；不同输出目录或 walltime 不改变科学身份。 |
| REG-S1-02 | claim 扩大使 novelty/theory/method-code 的相关依据失效；未变数字的 evaluation 可以保留。 |
| REG-S1-03 | 候选排序、插入和删除不转移旧回执；新候选不能继承相同位置旧 ID 的 PASS。 |
| REG-S1-04 | reviewer 调用期间对象被修订，返回回执只能成为历史记录；不能错误放行。 |
| REG-S1-05 | 旧缺依据回执迁移为待复核；幂等迁移与读旧数据路径通过。 |
| REG-S1-06 | 同 code 改科学配置/相关 claim 后，旧提交前 clear、waiver 与 RLD novelty/theory pass 不放行；声明的 sanity projection 可用于目标方法，无关同 code sanity 不可替代。 |

**SC-S1-01 候选重排和插入**

- 两端各运行 Discovery，先产生 Zebra 候选并完成真实查新/批判回执。
- 经正常候选接口加入排序更靠前的 Alpha；保持 Zebra 内容不变，再将 Alpha 的机制改成另一种方法。
- 预期：Zebra 的稳定 ID 与适用 review 保留；Alpha 缺少对应 revision 的评审时 gate 阻塞。重新 merge、重启会话和重新 evaluate gate 都不能改变这一结论。
- 补齐 Alpha 的真实评审后，gate 按实际 verdict 决定；不预设所有候选都应通过。

**SC-S1-02 主张改变与局部重评**

- 为已真实运行的普通优化器候选取得当前复核，再把主张从“该合成任务的收敛表现”扩大为“所有分布上的收敛保证”。
- 预期：相关 review 失效，已有数字不被改写，GO 不得沿用旧通过。真实 reviewer 应指出证据不足或缩小主张要求。
- 恢复原本有证据支持的范围作为新 revision，重新审查受影响维度；重启后保持正确依据。

**SC-S1-03 方法配置与执行配置**

- 同 commit 下分别改变学习率和输出路径。通过原生宿主创建实验，检查 method_spec；实际训练 manifest 回报有效配置。
- 预期：学习率变化得到新身份；纯路径变化保持身份；创建后悄然改配置文件导致运行回报不一致时不能按旧身份导入。旧提交前 clear、waiver 和 RLD pass 在相应配置/claim 改变后失效；补做符合新目标配置的 sanity/评审后才可继续。

S1 完成条件：两端三个 SC 与全部 REG 通过；旧回执迁移不默许当前 GO，场景中的失效可在页面和恢复包中看见。

## 6 S2 修复独立确认的候选 基线与材料身份

### 6.1 实现入口与接口

主要修改 `research_db.py` 的 `_confirm_setup`、`_confirmation`、`_stale_reasons`、实验创建、产物导入及提交状态路径；确认相关工具 schema 与配置同步更新。[当前实现定位][RC]

复用不可变文档保存候选及确认批次，拟议接口：

```python
freeze_candidate(hypothesis_id, search_evaluation_id) -> candidate_spec_id
create_confirmation_batch(candidate_spec_ids, material_spec) -> confirmation_batch_id
create_experiment(..., stage="confirm", candidate_spec_id=...,
                  confirmation_batch_id=..., baseline_experiment_id=...)
create_experiment(..., kind="baseline", stage="confirm",
                  confirmation_of=search_sota_experiment_id,
                  confirmation_batch_id=...)
```

`freeze_candidate` 核对当前搜索 Evaluation 与 S1 已保存的 method spec，建立一份不可变的选择记录；不首次生成方法身份，不接受调用方另填均值或不同配置。需满足当前搜索证据、保护指标和非确认类义务；依赖确认数字的 review 不得成为创建确认实验的循环前置条件。

`confirmation_batch` 保存候选名单、每个候选的方法身份、冻结的 SOTA 身份、确认材料、配对要求和协议。名单必须在第一次使用确认材料前冻结，**包括确认 baseline 的第一次执行**。候选数量上限按不同科学候选计数，不按 hypothesis 节点个数计数。

`material_spec` 至少包含规范化的数据集/切分版本、可验证的材料清单身份与训练 seed 块；具体 C1/C2 定义见第 3.2 节。相同材料换个文档 ID 不算新材料；仅更换训练 seed 也不能把已暴露的测试标签/数据内容重新声明为未见。S0 的功能项目验证切分和 seed 的使用约束；S7 的盲评还需独立私有评测边界。

确认 baseline 必须显式指向该 batch 冻结的搜索参考实验，并匹配其方法身份。确认候选固定引用这份确认 baseline；后来创建其他 control 不得移动引用。项目 SOTA 改变后，旧确认保留为历史，不能自动改绑新 SOTA。

从 S2 开始，产物导入必须保存完整小型 manifest 和有效方法配置快照，不能继续丢弃嵌套 config/env 字段。S3 在此基础上强化单位与独立性校验。

### 6.2 确认使用历史和重试

按项目保存最小确认使用记录：material key、batch、candidate spec、run/attempt、开始使用时间、提交/结果导入事件。使用史不依赖 Evaluation 是否存在，也不因撤回、节点改名、文档 supersede 或进程重启而删除。

- planned 尚未执行与已投入材料分开记录；首个确认提交/执行时冻结名单并保守占用材料。
- 提交 unknown 时保留占用。只有可信对账证明完全未执行、没有材料或结果暴露，才可释放纯占用。
- 同一预先冻结 batch 的多个候选可按预定协议共享材料；开始后不能加入根据结果修改的新候选。
- 确认反馈导致方法变化时，后续工作属于新候选，使用已授权池中的新材料建立新 batch，或继续作为探索。池耗尽时保留未确认状态。
- 相同候选、同一已导入结果的重评/报告修正不增加独立样本。
- 已明确的执行故障允许同候选同材料产生新 attempt，保留全部历史；失败判定必须有执行依据，不能因为指标不好把有效结果改作技术失败。有效 attempt 的选取规则预先固定，不能取最好一次。

这些规则记录并约束确认材料参与决策的边界；非盲功能测试不证明私有材料已隔离。默认仍为描述性 Stage 1 判断，不宣称对多候选筛选提供统计显著性或全局错误率保证。

### 6.3 迁移与错误

旧 confirmed 只有在候选配置、参考方法和材料使用史均能从原始记录可靠重建时，才能进入当前资格检查；缺依据则显示历史 confirmed、当前 `confirmation_unverified`，要求新确认或可核验的补证。不得用“当时最新 baseline”或当前配置倒填历史关系。

建议复用或新增：`CANDIDATE_IDENTITY_MISMATCH`、`CONFIRMATION_BASELINE_MISMATCH`、`CONFIRMATION_MATERIAL_REUSED`、`CONFIRMATION_IDENTITY_UNVERIFIED`。拒绝需在写入前或同一事务内完成，不产生半个确认实验，也不启动外部作业。

### 6.4 确定性回归

| ID | 必测断言 |
| --- | --- |
| REG-S2-01 | 搜索70.0→70.3，无关弱基线10.0不能成为确认参照；后创建 control 不改变原引用。数值仅为 REG 夹具。 |
| REG-S2-02 | 相同 code、lr改变，在同材料上申请确认被拒；候选名单开始后不可增加。 |
| REG-S2-03 | 已启动/已导入但未建立 Evaluation 的确认，使用历史仍能阻止反馈后新候选复用。 |
| REG-S2-04 | 换 hypothesis、repairs/combines、方法显示名均不清除项目级材料使用史。 |
| REG-S2-05 | 同一批预先冻结的两个候选按协议允许共享材料；计数不因换节点绕过上限。 |
| REG-S2-06 | 真实执行失败的合法 retry 可继续；已有有效但不佳的结果不能被选择性撤销并挑最好 attempt。 |
| REG-S2-07 | unknown、取消、恢复和重复导入保持使用史；纯 planned 且可证明未执行的取消不误记为结果暴露。 |
| REG-S2-08 | 旧缺配置/基线依据的 confirmed 迁移后不能直接 GO；重复迁移不改历史。 |

### 6.5 双宿主真实场景

**SC-S2-01 正确候选与确认基线**

- 在每个宿主的新 ToyOpt Lab 中，按 S0 冻结的参考和候选配置完成真实搜索与复制；不提前运行确认 seed。
- 冻结 candidate spec 和 batch，执行正确参考方法在确认材料上的训练，再执行候选确认。
- 独立 scorer 核对真实数值；DB 中 candidate、baseline、材料和 Evaluation 关系必须完全相符。
- 预期：达到固定门槛时确认依据有效；未满足的真实 review 仍应阻止整体 GO。若数值未达门槛，记录科学结果，正常 confirmed 正例保持未覆盖，不修改门槛或补假指标。

**SC-S2-02 错误 baseline 与最新 control 干扰**

- 真实训练一个预先定义的弱 control，经正常入口尝试用其替代确认参考。
- 预期：错误身份被拒绝；没有该错误请求对应的新候选确认作业。正常确认建立后再创建另一个 control，已绑定的参照和 delta 不变。
- 保存请求、错误、外部作业计数和确认关系前后快照。

**SC-S2-03 确认反馈后调整超参数**

- 使用 C1 完成至少一个真实确认反馈，不论结果正负；随后保持 code 不变改变学习率。
- 尝试沿用旧 spec、旧 batch 和 C1，预期被身份/材料规则拒绝；换 hypothesis 后再尝试同样被拒。
- 若协议已预留并授权 C2，正常创建新候选与 batch，在 C2 的新评测切分和对应训练 seed 块运行；否则保留待确认并说明池已耗尽。核对 C2 未复用 C1 标签实例，不能仅临时生成新训练 seed 伪称它是新材料或已在原授权中。

**SC-S2-04 确认过程的执行故障与恢复**

- 对冻结候选注入一次有日志依据的启动/输入路径故障，保留失败 attempt；修复纯执行设置后，在同候选身份下合法重试。
- 在一次材料已投入但 Evaluation 尚未写入的时刻结束会话，恢复后检查使用历史仍在。报告修正或重复导入不能增加配对数。
- 已存在有效结果的 run，不允许通过降低结果或删除 Evaluation 制造“可重试”的空白状态。

S2 完成条件：两端四个 SC、正常确认正例和所有拒绝路径均有真实证据；REG 覆盖精确边界；最终 GO 按实际全部资格判定，不以玩具方法必须新颖为验收目标。

## 7 S3 保留原始单位并约束历史证据重评

### 7.1 导入和重评契约

主要修改 `import_run_result`、`_compute`、`_check_protocol_runs`、`metrics.run_values/canonical/check_unit_mix` 与 schema。[当前单位路径][RU]

每个 run/attempt 保存：原始主次指标值、`raw_units`、完整 manifest 快照、有效配置、导入时 MetricSpec/协议身份、parser 版本和现有来源引用。数值快照与解释依据同时保留。后续更新配置不能原地重写这些字段。

本轮采用保守且明确的初版兼容规则：

1. 当前规范 `input_unit` 与已保存 `raw_units` 一致，才可直接重评该原始值。
2. 本批仅允许辅助/保护指标在原始单位不变时，改为受支持的 `canonical_unit` 并等价转换其边界；从原始快照重新计算，物理含义必须不变。已存在实验时，主指标 canonical unit、`go_margin` 及其对应收益门槛保持冻结；会改变这些字段的请求按现有冻结门规则拒绝，不借单位转换放开事后调门槛。主指标纯显示换算不得改变计算契约。
3. 当前 `input_unit` 与历史原始单位不一致时，拒绝旧值重新解释。本批不提供同一 attempt 的原始编码修订接口；恢复正确 input_unit，或使用第 2 条允许的 canonical/display 换算。不得通过新 attempt、原地覆盖、替换标签或撤回有效结果来“修正编码”。未来运行可按事前声明的新原始格式导入，历史值仍按其保存的表示处理。
4. 重新评分产生新 Evaluation，并更新其适用的复核依据；不重跑训练、不增加独立重复数。
5. `artifact_imported` 表示有可验证的导入依据；若原路径当前不可取得，只要完整已接受快照仍在，历史计算可保留，同时显示来源可用性，不能假称原文件仍可读取。

合法 fraction `0.001` 与 `0.1` 均在声明范围内时，不能仅因倍率大而硬拒绝。单位与范围构成硬约束，异常尺度可形成复查提示。

### 7.2 独立性字段

声明的 `pair_fields` 与 `independence_fields` 在方法侧及对应 baseline 侧都必须按协议完整。缺失、null 或类型不合法时拒绝/标记未验证，不能把 `None` 当作一个新的独立单位。

`n_paired`、`n_independent` 分别记录。多个 attempt、重复导入、共享同一独立性 key 的结果不能增加独立样本。字段完整只证明满足已声明的元数据契约，不等于自动证明统计独立；协议须解释字段所代表的重复单位。

### 7.3 旧数据迁移

优先从已保存完整 manifest 或可核验的历史原始 manifest 恢复真实单位，并记录恢复来源。若只能看到当前规范，不能倒填。无法证明的旧 run 保留可读，但不进入要求可信单位的当前 gate/guardrail。

迁移前后保留旧 Evaluation 与 GO 历史。补齐旧元数据时明确列出缺失字段及所需原件，仅恢复可证明的原始解释；不开放同 attempt 的数据覆盖，也不要求无理由重训所有旧实验。单位拒绝可沿用 `METRIC_UNIT_MISMATCH`，缺原始依据建议 `RAW_METADATA_UNVERIFIED`，独立性缺失建议 `INDEPENDENCE_UNVERIFIED`。

### 7.4 确定性回归

| ID | 必测断言 |
| --- | --- |
| REG-S3-01 | 原 manifest GiB、40/42、允许增1：保护失败。改 input_unit=MiB 后重评被拒，不能变通过。 |
| REG-S3-02 | 辅助/保护指标原始单位不变，只更换 canonical_unit 并等价转换边界：效应物理意义与判定一致。 |
| REG-S3-03 | 完整 nested units/config/env 的保存与读取；当前文件变动不重写导入快照。 |
| REG-S3-04 | independence key 为 a/b/missing 时不能计作3；两侧缺字段、重复 attempt、重复导入分别覆盖。 |
| REG-S3-05 | 合法比例相差100倍不误报单位错；超范围、非有限值和不支持换算仍拒绝。 |
| REG-S3-06 | 历史缺单位有可验证原件时修复，否则 legacy/unverified；迁移幂等且不改历史已花费用。 |
| REG-S3-07 | 已有实验后改变冻结主指标 canonical unit/go_margin 被拒；同 attempt 改原始编码不能覆盖、伪造新 attempt 或增加独立样本。 |

### 7.5 双宿主真实场景

**SC-S3-01 实际产物大小与单位变更**

- 将模型/预测文件的实际字节数作为一项辅助测量；使用现有支持的 bytes、mib 或 gib 单位。
- 真实运行并导入后，通过虚构用户的正常配置变更入口改变输入单位，原产物保持不变；尝试重评必须拒绝。
- 恢复正确输入单位后，仅改变该辅助指标的 canonical 表示并使用等价边界，重评得到等价结果；独立按文件大小核算。另确认修改冻结主指标计算单位会被拒。全部操作不新增训练或独立配对。

**SC-S3-02 不完整的导入副本**

- 保留原始 manifest；在 `fault-injection/` 制作一个缺失声明独立性字段或单位字段的副本。
- 原生宿主尝试导入副本，被拒且 DB 没有半写入；用原件重试可正常导入。
- 结束会话并恢复，原始单位与拒绝原因仍可查，不会从当前配置自动填补副本。

**SC-S3-03 历史项目升级**

- 用升级前构建在该宿主生成一份真实旧项目；不是手填 current/confirmed 的假数据库。
- 在项目副本上执行正式迁移，分别测试原始 manifest 可用和明确移走原始 manifest 的情况。
- 预期：可证明的字段恢复并重新校验；不可证明的记录保留历史但当前待验证；迁移再执行一次不重复写 revision 或提升资格。

S3 完成条件：两端所有 SC 与 REG 通过；拒绝旧输入重解释和正常等价换算两条路径均完成；旧项目不会因缺元数据崩溃或被静默当作可信。

## 8 S4 让评审结论与实际依据一致

### 8.1 结构有效 负面结论和调用失败分别处理

主要修改 `review_call.py`、review JSON Schema/提示词、`register_review`、`_candidate_rechecks`、`_latest_code_review`、`_check_ready`、`_recheck_bound`、obligation 登记/解决路径、模型家族解析及相应 MCP/CLI 契约。[当前复核路径][RR]

保留原始 payload，新增系统产生的 `reported_result`、`effective_result`、`normalization_warnings` 和 `evidence_manifest`。数据库与 wrapper 使用同一个规范化函数，防止某个登记入口只接受顶层 pass。

candidate_recheck 的 checklist 成为必需项，按维度约定：

| dimension | 必需内容 |
| --- | --- |
| numbers | 现有 A–F：数值、来源、汇总、配置与比较等检查；保留原清单语义 |
| protocol | 显式协议项，如命令、版本、训练量、数据与评测一致性；同步 schema，不能强塞入错误的 A–I 含义 |
| method_code | D、G，以及候选方法配置与实际执行代码的一致性 |
| novelty | H，对当前 claim 与最近相关工作的区别作判断 |
| theory | I，检查理论/机制解释及范围；经验研究也需检查是否存在无证据保证 |

先从当前冻结的协议和结构化 Claim map 解析适用性，再规范化回执。在现有不可变 claim/协议文档中保存 `review_applicability`：各维度的 `required`、协议是否允许整维度豁免、`scope_ref` 和理由；由产品校验并绑定 claim revision，reviewer 自报 N/A 不能改写这些字段。numbers/protocol/method_code 对经验结果不得整维度豁免。无方法新颖性主张的复现/工程评测可按协议豁免 novelty；理论维度通常核对“只作经验结论、无无依据保证”即可 pass，不要求虚构定理。仅协议明确允许且当前 claim 不含相应理论主张时，才可申请整维度 theory 豁免。

规范化的唯一判定规则如下。`fail > uncertain > pass` 只定义这三种结果的保守顺序，N/A 按适用性规则单独处理。

| 回执与当前适用性 | effective_result 与资格 |
| --- | --- |
| 任一适用必需项 fail，或顶层明确 fail | `fail`；保存问题并阻止资格，顶层乐观不能覆盖 |
| 无 fail，但适用项含 uncertain，或顶层明确 uncertain | `uncertain`；待补证，不自动放行 |
| 必需维度；至少一项适用，其余 N/A 均有匹配理由；适用项全 pass 且顶层 pass | `pass` |
| 必需维度全项 N/A、缺少适用性依据，或未经适用性授权的顶层 N/A | 至少 `uncertain`；若另有 fail 则仍 `fail` |
| 冻结协议允许、当前结构化 scope 确认整维度豁免，回执顶层与各项均为有据 N/A | `not_applicable`；资格显示 `exempt`，保留 scope/reason/basis，不改写为 pass |
| 已允许豁免，但 reviewer 指出实际适用的负面/不确定问题 | 按负面/不确定规则处理并记录适用性冲突；不能用豁免消除该发现 |
| 缺失/重复必需项或结构无法解析 | `REVIEW_INVALID`；保留原文，按有限结构修正流程处理，不能取得资格 |

整维度可豁免时也允许 reviewer 完整审查并返回有据 pass；这种情况保存实际 pass 和审查范围，不伪造 N/A。修改 claim 或协议后，适用性声明及依赖它的旧 exemption 同时重新校验。顶层和细项的结果不一致时记录 `SUMMARY_CHECKLIST_MISMATCH`，输出始终采用上述规则。

合法 fail 是有效评审，应保存、产生对应未解决问题并阻止资格。不得把合法 fail 当作格式错误，让模型反复改到 pass。只有结构不合法才走现有有限格式修正；原始负面发现保留，修正结构不等于问题已解决。

重复/缺失必需项属于结构问题；非阻断建议写 observations 或 note，不能把必需项的 fail 同时解释成“无影响”。code_review 的 CRITICAL/MAJOR/MINOR 规则保持独立，不把所有类型的轻微建议一律变成失败。

**未解决问题的创建与关闭必须闭环。** 复用现有 obligation，不另建问题管理系统。登记合法 fail 时，在同一事务内按 `(subject, relevant_basis, dimension, required_item)` 创建/更新对应 OPEN；同项多个发现保留为有来源的列表。只有顶层 fail 而无失败细项时用明确的 summary 项保留原因。保存来源 review ID 和原始条目，同一回执重复交付幂等，不能重复创建，也不能把已解决问题重新打开。后续独立回执发现新问题时，才可按新观察追加或重新打开，并保留历史。

reviewer 仍只读；由受控的评审登记路径写入上述问题，不授予任意 obligation 修改权限。修复后，RLD 使用现有 `resolve_obligation`，提供对应 issue/subject、新 method/claim/evaluation basis，以及针对该检查项的有效 review 或真实验证证据。系统核对来源匹配、当前有效性和实际检查项；仅引用任意存在的文件/成功 run 不足以关闭。新 review 的整体 pass 不会自动关闭其他问题，`reconcile_obligations` 中问题消失也不等于解决。

claim 缩小可使用 `claim_narrowed` 类型的 resolution，必须引用新 scope 和相关复核，旧问题保留历史。解决问题本身不以整体 GO 已通过为前提，避免循环阻断；完成所有相关 resolution 后再重新计算 eligibility。

### 8.2 引用路径与读取边界

登记 pass 前，把 evidence_paths 解析到明确的项目 root、候选只读代码版本或允许的文档目录，核对真实存在、可读取、对象类型与 basis 版本。相对路径基准固定；代码扩展名不足以证明文件存在或版本一致。

候选代码可用已有只读 checkout 或从固定 code_ref 提供的文件快照；不能让 reviewer 看当前工作树，再把回执绑定旧 commit。研究文档和结果引用其不可变版本/导入快照；不要把调用方自行写的“read=true”当作实际读取证明。

`evidence_manifest` 区分路径/版本已核验与后端确有读取轨迹。最小实现先保证前者；只有原始工具调用能证明时才记录后者。合法负面评审指出文件缺失时保留该发现，不能因文件缺失把其负面结论丢掉。

### 8.3 模型家族

接入 provider、规范化 model ID、family 分开保存。优先使用后端观测的实际模型，provider 只是通道。覆盖同一模型经直接 provider、代理、聚合路由访问的别名；无法确定 family 时不能宣称满足跨族要求。

配置同族应尽可能在调用前拒绝；实际观测身份与请求不一致时，该调用原文与费用保留，但不能作为满足要求的独立复核。不得退回主 agent 自评。

### 8.4 有限文献补查与 ABANDON 依据

增加合法待证状态：novelty_precheck 可返回 `NEEDS_EVIDENCE`，candidate novelty recheck 用 `uncertain`，并附 `requested_queries`。每轮最多 3 个明确查询，默认自动补查最多 1 轮；查询、来源、时间、原始结果路径和失败都要登记。

通过现有 literature 工具/Discovery 助手执行补查，再把原始来源路径和原始 reviewer 问题返回 reviewer。优先续用同一会话；若后端只能新开会话，记录 parent_review_id，传递原始前轮回执和补证材料，不用 Leader 的倾向性总结替代。

候选/claim basis 在补查期间固定，文献输入集单独记录追加版本；最终回执绑定实际使用的资料集。不要把新增一条补证或 select/cite 自身操作设计成无限失效循环；也不要绑定整个全局文献列表而让无关新增文献使所有评审过期。

ABANDON 增加 `abandon_evidence`：已核验 literature_doc_id、canonical DOI/arXiv 身份、覆盖的 claim、可读取原文位置及覆盖解释。代码核验来源身份与版本；内容是否覆盖主张仍由真实 reviewer 判断。

论文未核验、定位材料不可取或仅在 JSON 内自报一个标题时，保留 reported ABANDON，effective verdict 为 NEEDS_EVIDENCE。网络错误不是科学否定。用户假说即使取得有效 ABANDON 意见，仍遵循原有用户决定边界，不自动删除。

### 8.5 迁移

旧 review 原始文档继续可读。缺 checklist 或 basis 的旧 pass 不能自动补全成新协议 pass；确需用于当前资格时重新评审。已有合法负面意见保留为未解决事项，不能因为协议迁移消失。模型家族未知显示 unverified，不静默从 provider 推断。

### 8.6 确定性回归

| ID | 必测断言 |
| --- | --- |
| REG-S4-01 | 细项 fail / 顶层 pass：保存原文，effective=fail，GO 被拒；不能触发“重写到通过”。 |
| REG-S4-02 | 细项 uncertain、顶层更保守、缺项、重复项、非法全N/A分别得到约定结果；正常部分N/A可pass，合法整维度豁免返回N/A/exempt；claim变化使豁免失效；格式修正有上限。 |
| REG-S4-03 | 不存在的 .py、错误代码版本、相对路径歧义不能形成 pass；负面缺文件发现可以保留。 |
| REG-S4-04 | 直接/代理/聚合渠道中的同模型判同族；同一 aggregator 下不同家族正确识别；未知身份不放行。 |
| REG-S4-05 | ABANDON 仅有虚构 arXiv/title 时待证；已核验来源但 claim revision 改变时旧意见失效。 |
| REG-S4-06 | 补查一次、重复恢复、相同 manifest 重交不会重复履行已完成请求或重复统计同一调用成本。 |
| REG-S4-07 | 补查期间 claim 改变时旧回执 stale；文献集正常追加不导致自我失效死循环。 |
| REG-S4-08 | fail→同回执重交→真实修复/新评审→显式resolution→资格重算闭环；重交不增殖或重开旧问题，无关成功证据不关闭问题，其他OPEN仍阻断。 |

### 8.7 双宿主真实场景

**SC-S4-01 真实 reviewer 发现数字矛盾并闭环修复**

- 真实训练后，控制器制作与 metrics 明显不一致的报告副本；原指标保留。通过正式 review 入口调用真实 reviewer。
- 预期：真实回执、requested/observed model、backend、费用齐全；fail/uncertain 如实登记并阻断，不能被 wrapper 改成 pass。
- 首次 fail 恰好生成相应 OPEN；重复交付与恢复不增殖问题。修复报告或方法问题，生成新依据，再调用 reviewer，并由 RLD 用针对该问题的有效证据显式 resolve。
- 新评审仍负面时保留问题；真正解决后解除对应阻断，其他未解决问题仍 OPEN。重交旧 fail 回执不能重开已解决问题，未经当前有效资格不得宣布 GO。
- 顶层/细项矛盾的精确 JSON 注入只在 REG-S4-01 执行，不要求真实模型必然生成该 JSON。

**SC-S4-02 查新材料不足和补查**

- 给一个声明“已有标准方法的新实现/新组合”的候选，初始 dossier 故意缺少一篇真实相关基础论文；具体来源在场景准备时冻结。
- 真实 reviewer 的补查请求被登记后，通过真实文献工具获取原始来源、核验并回传；重启会话后继续未完成补查，已完成查询不无故重复。
- 预期：足够材料后才能形成有依据的 verdict。若初轮 reviewer 已从现有材料正确判定，不强迫它制造 NEEDS_EVIDENCE；另选预先声明的材料缺口用例覆盖补查触发，保留全部尝试。
- ABANDON 的有效路径必须有真实可定位来源；不能以本地虚构论文满足“已发表覆盖”条件。

**SC-S4-03 同族与后端不可用**

- 每个宿主各提交一次已支持但同族的 reviewer 配置，预期拒绝且无不应发生的模型调用。
- 在专用子进程的隔离配置中模拟对应 reviewer 未登录/不可用。Codex 路径尤其验证 Claude CLI 不可用时不降级到 Pi；Claude 路径验证 Pi 不可用时不改用自评。
- 恢复测试配置，实际进行一次合法跨族评审；记录真实观测模型和两种后端调用，确认恢复不重放已完成 review。

**SC-S4-04 方法文件缺失或版本不符**

- 对合法候选临时移走其用于评审的代码快照副本或提供另一版本引用，保留原件；真实宿主通过 review 工具遇到证据错误。
- 预期：不能获得 method_code pass。恢复正确可读取快照后重新评审，receipt 与实际代码、配置和 claim 一致。

S4 完成条件：两端四个 SC 与全部 REG 通过。合法 uncertain 导致正确阻断可通过相应负向功能场景；不得把这种结果写成候选整体已通过。

## 9 S5 修复经验验证 适用性与恢复消费

### 9.1 执行经验的数据与状态

主要修改 `memory.py`、`capture_filter.py` 的调用范围、`_check_memory`、`context_pack`、恢复包及 lesson/finding schema。[当前记忆路径][RM]

保留 symptom、root_cause、root_cause_status、fix、scope 和 evidence refs，增加或明确 `fix_verification` 与系统生成的 memory_basis。根因状态和修复有效性独立：已验证修复可以伴随 unknown/proposed 根因；这种经验只指导已验证操作，不宣称根因已经确定。

lesson=verified 至少要求：

- 引用可解析、已完成并有真实导入依据的特定 run/attempt，身份和适用条件匹配。初版仅接纳现有正式 run 或 sanity run，不保留未定义的“等义记录”入口。
- 修复操作确实在该验证中使用；成功退出与相应检查项通过共同成立。
- 失败症状、应用的 fix、验证条件有可核对的结构化记录；不能仅因任意一个成功 run 存在就认定该 fix 有效。
- planned、running、unknown、失败 attempt 或已撤回证据不能作为 verified 的唯一依据。

`fix_verification` 的最小输入契约如下，均引用已有记录或导入快照，不接纳模型自证布尔值：

| 字段 | 约束 |
| --- | --- |
| `failure_attempt_ref` | 指向原失败 attempt/日志，关联 symptom、环境和需解决的问题；失败记录本身不必是有效科研结果 |
| `criterion_doc_id` | 验证开始前冻结的 experiment_design/task_request，包含检查项 ID、允许的证据类型、范围与验收条件 |
| `run_attempt_refs` | 精确到验证 attempt；系统读取 succeeded、exit 0、valid=true、未撤回、完整导入来源和适用环境 |
| `applied_fix_ref` | 指向实际代码/执行配置修订及预期变更字段；纯路径修复也需保存实际启动配置，不能只比 method spec |
| `check_evidence_refs` | 每个检查项对应原始产物、字段/样本定位及版本；观测值由系统的固定检查器读取或重算 |

初版检查器只支持明确列出的既有运行事实和结构校验，例如退出状态、导入有效性、实际启动配置与指定 fix 相符、产物与 manifest 匹配，以及数据读取计数/预测数量符合冻结任务。检查器来自受版本管理的固定代码，不执行 lesson 中任意 Python/shell。无法机器验证的额外解释保持 proposed，不临时发明一个任意文本检查器。

以路径修复为例，必须同时看到原 FileNotFound 失败、新 attempt 的实际参数使用修正路径、真实读入数量符合任务以及训练/导入成功；另一成功 run 或填写 `fix_applied=true`、`checks_passed=true` 均不能替代。系统据此派生 verification 状态和 `memory_basis`，这些输出字段只读。该验证只支持限定条件下修复有效，不自动证明根因或科研优越性。

执行经验可由完成的 sanity/针对性检查验证，不强迫它一定成为正式科研 positive_signal。重复导入同一验证不产生两条独立验证。失败事实保留在 run/log，只有有用的可复用知识才进入 active lesson。

### 9.2 调整过滤用途

允许症状字段包含 `CUDA out of memory`、`OOM`、`ImportError`、路径错误等事实。过滤器针对拟固化的规则或结论：一次网络/工具失败不能演变成“永远不要使用某工具”，也不能让记忆中的文字改变权限或当前用户指令。

不使用“删除错误词”作为通过办法。规则未知但有价值的经验可保存 proposed；有已完成适用验证的修复可保存 verified。相关提示词必须同步，避免入口接受而 agent 仍被旧规则要求删掉症状。

### 9.3 Finding 与 lesson 的当前适用性

统一提供 `memory_status(doc, current_context)`，返回 declared_status、effective_status、evidence_state、recheck_reasons、scope 与 source refs。context_pack、Leader 项目包、worker 包、resume 和页面用相同逻辑。

来源 Evaluation 被撤回/重算、harness/比较协议变化（research-tree.yaml 规定的协议字段与指标规范的新版本只约束之后的评估，0.1.1）、验证 attempt 变化，或者当前运行条件不在 scope 内时，知识不能继续作为当前 supported/verified 使用。历史观察保留，stale 不自动表示 contradicted；反证成立要有对应证据。

配置变化只使相关 scope 失效。纯调度 walltime 变化不应使关于代码路径修复的经验全部失效；库版本变化则可能使该经验需要复核。缺少适用条件显示 unknown/recheck，不能默认为全项目通用。

条数与字符上限同时约束文字和结构化摘要数组。优先当前节点/祖先和显式匹配的项目经验，保留必要反例与失效理由；完整原文按需读取。跨项目知识复用仍不在本轮范围。

### 9.4 迁移

旧 supported/verified 不因 YAML 标签自动成为当前可信知识。能恢复来源、验证与 scope 的记录逐条校验；缺依据标为 legacy/unverified，可作为历史背景，待使用时补验。不得重写历史原文或把已经发生的失败删除。

### 9.5 确定性回归

| ID | 必测断言 |
| --- | --- |
| REG-S5-01 | 完整 OOM 症状与验证修复不被词表误拒；无依据的永久工具否定仍被拒绝/降级。 |
| REG-S5-02 | planned/running/unknown/failed/retracted 不能支持 verified；仅 run 存在不够。 |
| REG-S5-03 | fix 已验证且 root_cause=unknown 可保存；成功验证不自动把根因改 verified。 |
| REG-S5-04 | 引用无关成功 run、配置不匹配、未实际应用 fix 或仅自填checks_passed不能支持该lesson；固定检查器从原始产物重算，未知检查类型保持未验证。 |
| REG-S5-05 | harness/协议/证据撤回后，Leader 与 worker 的 finding/lesson均显示相应 stale 和来源。 |
| REG-S5-06 | scope 不匹配、缺字段和反例保留；文本及结构化数组共同受上下文预算约束。 |
| REG-S5-07 | 旧无 memory_basis 的可信标签不自动放行；迁移和重复验证幂等。 |

### 9.6 双宿主真实场景

**SC-S5-01 真实故障 修复和后续避免**

- 首次训练使用预先声明的错误输入路径或缺少一个测试专用依赖，实际进程失败且产生日志。
- agent 根据日志修复执行设置，先冻结具体验证检查项，再完成真实 retry/sanity；登记包含原症状、实际修复、适用条件和验证记录的 lesson。核对真实启动参数包含 fix，并从原始产物重算相应验收项。
- 在另一个同条件任务中不再强制注入故障，让 agent 经 context_pack 获取经验并执行成功。
- 预期：经验可入库、验证依据正确、后续确实使用相关 fix；用另一个成功 run 或只填写 checks_passed 的对照请求不能变为 verified。注入的首次故障不计作“已有经验仍重复犯错”。

**SC-S5-02 未执行证据与未知根因**

- 创建但不执行一个 run，尝试用它支持 verified lesson；生产入口拒绝或保持 proposed。
- 对 SC-S5-01 的真实成功修复保留 root_cause=unknown，登记 verified fix；预期允许且上下文明确根因尚不确定。
- 恢复后两条记录的状态不混淆，不能因重启自动升级 planned 证据。

**SC-S5-03 协议改变后的知识降级**

- 从真实 Evaluation 建立有范围的 finding，读取 Leader/worker 包确认来源与支持状态。
- 先通过虚构用户的配置入口改变 research-tree.yaml 规定的协议字段（如确认设置）；预期 finding 与 lesson 保持当前状态（0.1.1 起配置变更只约束之后的工作，见 CHANGELOG）。
- 再通过虚构用户的合法入口更新 harness 或比较协议本身（配置规定字段以外，如 min_pairs），或撤回该 finding 的一个关键 run；再次读取两类包和恢复包。
- 预期：旧 finding 保留为历史/待复核，当前不再无条件 supported；对不受此次变化影响的 lesson 不过度失效。
- 在新条件下实际补验后建立新依据，恢复当前适用状态；不直接修改标签。

S5 完成条件：两端三类 SC 完整完成故障、修复、复用和恢复链；REG 覆盖词表及未验证引用边界。

## 10 S6 保证预算分池和真实作业恢复一致

### 10.1 预算归属和请求身份

主要修改 `create_experiment`、`reserve_submission`、`claim_submission`、对账/结算、迁移和 `scripts/benchmark/score.py`。[当前预留路径][RB]

预算池由已批准实验推导：普通 screen/replicate 使用 search；符合 S2 batch 约束的 confirm 使用 confirmation；repair 由 RLD 依据实际故障/义务显式分配。worker 不能在实验创建或预留阶段自行把普通搜索标成 confirmation/repair。

`resource_request.budget_pool` 若保留，只能作一致性断言；与实验归属不符则在创建 reservation 前拒绝。初版拒绝跨池混合 allocation，调用方按池拆开；不在一笔请求里自行猜测成本分摊。

幂等性比较完整请求：项目、排序后的 run/attempt refs、池、resource class、节点数、walltime、平台配置等。`1×60` 与 `2×30` 虽同为60 node-s，仍不是同一个资源请求。相同 submission key 改形状/改池/改平台必须拒绝，原预留保持不变。

沿用已实现的在途预留、generation、unknown hold 和真实结算；同一终态重复通知不重复计费。拒绝路径检查 reservation 数、余额、run 的 submission_key 和外部 job 数都未改变。

### 10.2 本地执行适配器与故障窗口

S0 的测试执行适配器至少提供 submit、status、accounting 和测试自有进程 cancel。submit 必须真的启动 CPU 子进程，并保存 submission_key、稳定 job_id、PID 与进程启动时刻、attempt、开始/结束、退出码、产物路径和真实用量。

支持预先声明的一次性窗口：预留后未启动；已启动但响应丢失；作业终态已记录但结算通知丢失。训练由独立于被测主会话的轻量监督进程持有，关闭 Leader 不应同时杀死待恢复 job。

适配器自己的幂等性与崩溃窗口先做进程级 REG；不能用永远返回同一个虚构 job_id 的函数证明“没有重复提交”。控制器只终止自己创建且身份核对一致的测试进程。

### 10.3 分开计量重试和重复作业

| 字段 | 定义 |
| --- | --- |
| `research_attempts` | 实际科研运行尝试总数，包括失败 |
| `authorized_retries` | 已确定失败/取消后，按规则增加的合法 attempt |
| `transport_retries` | 同一 submission key 的请求重试/对账，不应新增 job |
| `duplicate_jobs` | 同一逻辑意图在没有合法新 attempt 的情况下实际多启动的外部 job |
| `duplicate_import_requests` | 同一产物的重复导入请求；只有重复记样本才是错误 |
| `duplicate_settlement_requests` | 重复终态通知；只有重复扣费才是错误 |
| `injected_failures` | 控制器强制注入的故障 |
| `avoidable_repeated_failures` | 当时已有适用且已验证修复，仍因未采用它而重复发生的故障 |

`duplicate_jobs` 由外部启动账本与 run intent/attempt 关系计算，不能用 `sum(attempt-1)` 代替。固定故障使用稳定 fault_class 和时间/环境匹配；不靠 root_cause 文本子串判断经验是否失败。强制再次注入的故障不能归罪于 agent 未学会经验。

资源分别报告实际 CPU seconds、实际 job wall seconds、插件 node-seconds、模型调用及已知费用。reservation 的申请上限不能写成实际用量，记录中的最小1秒舍入也不能作为精确性能结论。

### 10.4 预算迁移

已花总费用不变。旧错池记录保留原账及更正依据，可修正分池视图，但不能增加总预算。仍在途但身份/池不明的 reservation 保持 held/unknown 并对账，不因迁移释放余额。旧请求形状无法重建时，不凭 node-seconds 编造其请求身份。

纠正分池后若超出某池上限，明确报告当前超额，拒绝相关新准入；不能自动挪用别池掩盖。建议使用 `BUDGET_POOL_MISMATCH`，请求身份冲突沿用 `SUBMISSION_AMBIGUOUS`。

### 10.5 确定性回归

| ID | 必测断言 |
| --- | --- |
| REG-S6-01 | search满，创建/预留时分别尝试confirmation、repair覆盖，均拒绝且无副作用。 |
| REG-S6-02 | 混池refs拒绝；合法RLD分配repair后worker可以按批准归属执行。 |
| REG-S6-03 | 相同key但资源形状/平台/池不同，即使总node-s相同也拒绝。 |
| REG-S6-04 | 两worker争最后额度只有一个预留成功；并发写入不超池上限。 |
| REG-S6-05 | 已启动但回执丢失→恢复→按同key找到原job→一次导入/结算，不新增外部job。 |
| REG-S6-06 | 合法失败重试使 authorized_retries 增1、duplicate_jobs不增；真实额外启动恰好使duplicate_jobs增1。 |
| REG-S6-07 | 重复终态/导入不重复计费或样本；历史错池迁移不凭空释放在途额度。 |

### 10.6 双宿主真实场景

**SC-S6-01 最后额度的并发争用**

- 用小的已声明 search 限额运行至仅剩一笔请求的空间；两个真实 worker 分别准备下一请求。
- 控制器同步释放申请，并在两笔申请均返回前不让第一笔作业结算释放余额，避免把串行运行误当并发测试。
- 预期：只允许一笔 reservation 与对应真实 job，另一笔明确拒绝。拒绝的 worker 尝试预算池覆盖仍失败；合法完成后余额按真实用量结算。

**SC-S6-02 已启动作业的回执丢失**

- 在真实 CPU 子进程已启动、job_id 尚未 attach 时，适配器丢失一次响应，系统进入 unknown。
- 结束被测主会话，保留 job。新会话只收到项目路径和“恢复当前工作”，经持久状态按原 submission key 对账。
- 预期：找到同一 job/进程开始身份，attach 并导入真实结果；外部启动计数不增，材料使用史与预算占用保留。
- 若原 job 已完成，仍复用原产物而非重跑。恢复完成点是恢复到后续合法动作，不是只打开新窗口。

**SC-S6-03 合法重试和重复终态**

- 注入一次真实可恢复的执行失败，按规则新建 attempt；随后对成功终态重复通知两次，并重交同一导入请求。
- 预期：存在两次真实尝试，其中一项合法 retry；duplicate_jobs=0，独立样本和结算各只计算一次成功结果。失败成本保留。
- 另用测试执行适配器的明确故障模式制造一次额外真实启动，独立观察器必须报duplicate_jobs=1；不得靠插件本身的记账视图掩盖孤儿作业。

S6 完成条件：两端三类 SC 及所有 REG 通过，实际作业记录、DB与评分器对重试/重复的解释一致，恢复路径不消耗额外确认材料或错误释放预算。

## 11 S7 改善实验选择依据并运行匹配 pilot

### 11.1 有限的重复实验建议

保留当前 descriptive 结果分类和科学结果/投入处置分离，不在本轮把 Stage 1 改成发表级显著性门。增加纯计算的 `repetition_advice`：输入效应模式、配对差值、实际收益门槛、协议独立单元及其身份、预留 seed 池和追加资源请求，输出建议、理由与可用预算。

初版仅对 `effect_mode=absolute` 且输入为完整、互不重复的协议独立配对单元计算数值建议。绝对差值、均值、SE 和收益门槛必须在同一 canonical 单位。`relative_to_reference_mean` 等相对效应返回 `unsupported_effect_mode`；缺少独立性依据或多个输入共用独立性 key 时返回 `independence_unverified`。不得把秒的差值 SE 与相对改善 fraction 比较，也不得用全部相关配对的 SD 除以缩小后的 n 冒充独立估计。

规则在协议中预先固定：n 是已验证独立配对单元数，n<2 时不声称已知方差；n≥2 时计算这些单元的差值 SD 和 `SE = SD/sqrt(n)`，用效应距离门槛与一个固定 SE 倍数的关系识别需要更多重复的情况。SE 在此仅作描述性分配启发式，不输出显著性保证。符号不稳定可作为补充理由，不引入未经校准的 LLM 概率分数。遇到不支持的模式只返回原因和现有描述性结果，不产生数值 SE 或自动追加；相对效应的不确定性方法另行设计。

追加重复只用已声明的搜索/复制 seed，不使用确认池；必须通过真实预算预留。是否自动执行由预先配置决定，默认先向 RLD 返回建议与行动依据。到 seed/预算上限仍不清楚时保留 inconclusive 或现有观测信号与局限，投入可以暂停。

新增协议/配置仅覆盖这一有限策略，包含启用状态、SE倍数、单批追加数及可用seed边界；默认值与触发规则在测试前冻结。纯数值建议的全部分支由 REG 覆盖，真实 SC 验证建议基于实际测量和预算被正确消费。

### 11.2 用具体发现支持停滞与下一步决策

`note_findings` 新入口接收 `finding_ids` 与已有 decision 文档；兼容旧 `new_findings` 时只能与可验证列表交叉检查，不能单独用调用方整数重置停滞。

校验发现属于当前项目、证据与引用存在且在该决策时适用、批次未重复登记。相同 claim/证据集合反复包装不能反复增加发现数。系统校验来源与重复；是否具有实质新信息仍由 Leader 给出可审阅理由，不声称代码自动理解科研新颖性。

每个新增实验块说明：待区分的解释、已有 finding/evidence refs、什么结果会改变下一步、预期成本。组合/修复关系复用现有图结构，不要求父节点必须 positive。历史决策保留当时依据，后续证据失效作为新的状态反馈，不重写旧决策事实。

### 11.3 修正整体评测协议

区分三个比较问题：

| 比较 | 固定版本 | 回答的问题 |
| --- | --- | --- |
| 本轮闭环修复 | B=`616d646`，C=本文件实现后的冻结版本 | 本轮修复是否减少错误状态、重复故障和资源浪费 |
| 整轮 ARIS 吸收 | 升级前=`48b3841`，升级后=C | 整轮改进是否优于原始 research-tree |
| 编排的净收益 | A=最小单agent循环，B/C=指定插件版本 | 更复杂工作流是否值得其成本 |

原提案的 `53f3f4a` 与 `61b7784` 主要用于此前最后一轮宿主修复比较，不能继续混称为整个升级的前后对照。本阶段先执行第一行的小规模 pilot；后两行保留完整冻结协议、数据与预算计划，不冒充已完成。

C 必须是实际被测源码快照，可在最终提交前用只读快照加完整变更记录固定，提交后关联同一内容。快照后有功能修改则重新冻结并重跑受影响比较，不能把不同版本的好结果拼在一起。

`false_go` 根据冻结协议下实际 GO 所附主张是否被独立证据支持判断；不再用 `go_knobs != truth.best` 一概判错。找到另一个真实有效方案可以成功，最优解命中率另列。机制贡献与单纯指标改善分开评分，retired 当前状态不等于“过早放弃”。

多个最终候选逐个评分。blocked、active、预算停止、NOT GO 和未完成分别保留，报告总启动数、完成率和成本，避免以“从不产出结论”换取零错误 GO。

### 11.4 可信评测器与隐藏材料边界

当前 benchmark 把 `RT_BENCH_TRUTH` 交给 agent 可修改的训练代码；不能直接把它用于声称盲评的比较。[现有工具][RBE]

功能 SC 可以公开故障和预期规则；科研 pilot 的私有真值/确认标签则由独立可信 evaluator 保管。被测 agent 及其可修改训练代码均不能读取它们。把文件放到项目外、只从主 agent 环境删除变量或只隐藏目录名，都不足以构成隔离。

私有确认材料必须独立于公开训练/开发材料生成，保留受控的生成记录供独立复现。私有实例 seed、salt、标签真值，以及足以精确重建标签的任务生成参数，不得出现在 agent 或训练子进程可读的源码、配置、环境和挂载中。公开任务规律与训练样本可以提供，但不能使私有真值通过公开固定 seed 或生成器直接还原。S0 的公开验证集不得仅通过移动标签文件升级为盲评材料。

优先复用目标环境已有的独立用户、rootless 容器或经实际验证的文件系统/PID隔离。只挂载工作区、所需只读依赖及最小必要运行资源。evaluator 对参数做固定结构校验，只接受合法 run/候选模型请求；不能执行 agent 提供的 Python/shell，也不能成为免费无限枚举的 oracle。

训练输出采用数据格式模型/预测，evaluator 不反序列化任意可执行对象。评价请求绑定 run intent、候选版本、材料和预算；重复请求幂等，不增加独立样本。

在真实 agent 及训练子进程边界中，用无敏感内容的 canary 验证直接路径、符号链接、环境、继承FD和可见进程信息不能取到私有材料；允许的训练/评分仍可完成。同时审查公开生成代码与全部可读输入，并执行针对公开固定 seed/生成参数的重建检查，确认其不能精确还原私有确认材料。检查通过只支持已声明的隔离与生成边界，不声称对任意攻击形式完成证明。仅 canary 不可读或 bwrap 命令可运行均不足以报告盲评隔离通过。

若无法建立此边界，阶段功能 SC 仍可运行并明确“非盲功能测试”；盲评 pilot 保持 BLOCKED。不能用“agent 没有主动读答案”替代访问边界。

### 11.5 最小匹配 pilot

预先固定 3 类任务：零效应、组合/竞争解释、可恢复执行故障；每类一个匹配实例，B/C 各一个完整研究 episode。Claude Code 与 Codex 分别运行这 6 次，合计 **12 次 episode**，按宿主分组报告，不将不同主模型当作同一组重复。

B/C 使用相同主模型、同等工具/起始材料、训练与模型调用上限、并发数和空记忆；所有 reviewer、修复、确认与准备成本明确计量。B 缺少某能力时保留真实差异，不偷偷为 B 实现 C 的策略，也不剥夺 B 本来可用的资料。

正常学习结果来自真实 CPU 训练及独立 scorer。零效应可使用相同方法的无效配置变体；组合任务可使用两个必须共同启用才生效的真实特征/实现改动；故障按 S6 方式实际发生。受控解析函数任务若保留，只能单列 controlled/simulation 结果，不能混入真实学习收益。

小样本实测的“错误 GO”只能依据预先定义的私有判据报告；无法确定真实无效时写 independent confirmation not supported/inconclusive，不把一次噪声结果当作数学真值。重复单位是整个 episode，训练seed不是额外的完整研究重复。

先运行一对匹配 episode 检查计量与隔离，再按已冻结矩阵继续。不得因 C 表现不好而为 C 单独扩预算、改门槛或换实例。12 次是工程 pilot，不足以证明通用科研优势；有效负结果和 inconclusive 都必须进入报告。

原 105 次比较及论文级样本扩展仍按独立研究范围执行，不因本阶段完成自动启动。若接收实施任务的预算不涵盖该最小 pilot，完成可独立的功能实现和双宿主 SC，明确标注 S7-pilot 未完成，不能把全阶段写成 PASS。

### 11.6 确定性回归

| ID | 必测断言 |
| --- | --- |
| REG-S7-01 | 同均值不同SD产生符合规则的建议；n=1、零方差、预算不足、seed耗尽覆盖；不偷用确认seed。 |
| REG-S7-02 | finding_ids 与计数不符、重复批次、无依据发现不能重置停滞；实际新增证据可登记。 |
| REG-S7-03 | 两个真实不同但都有效的方案均可获支持；非唯一best不自动算false_go。 |
| REG-S7-04 | 负面/blocked/预算停止/未完成分别计量；多个GO候选与随后修订的决策按事件和版本评分。 |
| REG-S7-05 | A/B/C标签不能掩盖不同执行器；评分器使用规范化事件与外部证据，不要求旧系统先采用新DB结构。 |
| REG-S7-06 | canary访问被阻止；公开固定seed/生成参数可还原私有标签的配置被拒，合格私有材料模式可评分；重复请求幂等，非法候选/材料/过量请求拒绝。 |
| REG-S7-07 | 相对效应返回unsupported_effect_mode；重复独立性key或未定义分组返回independence_unverified；不跨单位计算SE、不自动追加。 |

### 11.7 双宿主真实场景

**SC-S7-01 真实噪声与有限追加重复**

- 使用 S0 开发阶段选定的小验证集/随机初始化变体，真实运行配对实验。
- 使用 absolute 主指标和有完整独立性身份的配对单元，读取实际差值与预算，独立计算 repetition_advice 的输入和规则；条件触发时按预声明seed追加，未触发时保留真实输出。
- 主动耗尽可用复制seed或预算后，系统不得借用确认池或强制给出确定科学否定；恢复后建议与已完成run一致。
- 精确高/低方差分支由REG-S7-01保证，不强迫一次真实测量恰好落入指定数值区间。

**SC-S7-02 组合与竞争解释**

- 分别运行两个单独收益有限的实际改动，再依据机制关系通过生产入口创建组合节点和最小对照。
- 预期：父节点为实际 inconclusive/negative 时，组合关系仍可建立；每次选择引用具体发现与待区分解释。
- 结果无收益时如实保留；不得修改指标或父节点状态来制造组合成功。

**SC-S7-03 两端匹配 pilot 与恢复后的独立评分**

- 每个宿主完成第11.5节的B/C六次episode；控制器记录实际启动的所有episode，不丢弃失败。
- 至少故障类episode经历实际会话恢复；由隔离evaluator/观察器根据原始模型、事件和账务评分。
- 预期：逐episode结果、版本、预算、独立确认状态、完成状态、重试/重复作业及模型成本可核对；pipeline完整执行即可检验工程目标，效果不佳不得被改写为成功。

S7 完成条件：两端SC-S7-01/02及共有场景通过；12次pilot执行、计量与隔离证据齐全；独立终审无未关闭CRITICAL/MAJOR。科学效能标记为pilot_only及实际观察，不声称完整科研benchmark已通过。

## 12 记录格式与最终交付

### 12.1 建议目录

在现有 `plans/design/` 中追加本文件和索引，并按现有风格保存：

- `reviews/Sn-r1.md`、`reviews/Sn-final.md`：阶段评审原文、有效结构结果、修复对应关系。
- `test-logs/Sn-claude.md`、`test-logs/Sn-codex.md`：各自命令、模型、场景判据、真实结果、失败与恢复。
- `test-logs/scenarios/Sn/<host>/<case>/<attempt>/`：小型manifest、状态快照、观察器结果和原始日志索引。
- `test-logs/implementation-status.md`：阶段矩阵、REG/SC映射、遗留项及科学效能状态。
- `test-logs/pilot/`：冻结协议、实际episode清单、私有evaluator的公开评分输出及逐项结果。

大模型权重、依赖缓存和重复的大日志不强制进入Git；放在项目已有的可持久获取证据位置，并保存明确索引。关键记录不能只链接会被删除的 `/tmp` 路径。保留失败原文及修复后记录，不用“最终通过”覆盖失败历史。

### 12.2 单场景最小记录示例

以下是待执行模板，值为示例占位，不是实际通过记录：

```yaml
scenario_id: SC-S2-03
stage: S2
host: codex
attempt: 1
status: NOT_STARTED
project_root: null
source_ref: null
build_path: null
loaded_plugin_path: null
requested_model: gpt-6-luna
observed_model: null
observed_effort: null
session_id: null
review_calls: []
preconditions: []
commands: []
fault_plan: null
assertions: []
raw_evidence_paths: []
observer_results: null
state_before: null
state_after: null
resume_evidence: null
resource_usage:
  cpu_seconds: null
  job_wall_seconds: null
  plugin_node_seconds: null
  known_model_cost_usd: null
  unknown_cost_calls: []
failures: []
fixes_and_retests: []
remaining_gaps: []
```

每条 assertion 写出输入/前置、expected、actual、证据路径与判定。不能仅写“agent说完成”。观测模型来自原始响应/运行日志；配置值只能放 requested。费用未知保持 null/unknown，不能以 token估计冒充实际账单。

### 12.3 阶段状态表模板

| 阶段 | REG与构建 | Claude真实SC | Codex真实SC | 独立终审 | 阶段状态 |
| --- | --- | --- | --- | --- | --- |
| S0 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S1 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S2 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S3 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S4 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S5 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S6 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |
| S7 | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED |

每阶段评审前确认测试编号有实际实现及真实执行入口。最终汇总全部required SC，缺失一端、遗漏恢复、用REG替换SC或缺原始模型调用证据，均不得汇总PASS。

### 12.4 源码与文档同步清单

| 范围 | 需要同步的位置 |
| --- | --- |
| 共享契约 | `shared/research-tree/tools/`、SQL/schema、config校验、文档类型/错误码、Python与MCP入口 |
| reviewer | 所有受影响的review schema、提示词、模型身份解析、规范化与登记路径 |
| 两端适配 | `claude-mod/`、`codex-plugin/` 的工具schema、权限/只读清单、hooks及安装说明 |
| 设计文件 | 02/03/04/05/06/07/08/09/10/11/12/14与README的相关条款，避免旧规则继续指导agent |
| 测试与示例 | 对应REG、新场景工具、项目生成器、demo、旧项目迁移测试及发布验证范围 |

修改只覆盖本文件定义的契约与必要调用链。优先小型共享函数和现有不可变文档机制，避免为这些修复再建设独立调度器、知识服务或全量事件重放系统。

### 12.5 最终报告必须回答

1. 每个审阅缺陷由哪个提交、REG和双宿主SC覆盖，是否还有未关闭项。
2. 哪些历史记录被保留为可信、哪些标为待复核，当前资格是否发生变化。
3. 每阶段真实加载了什么插件和模型，实际执行了哪些CPU运行/reviewer，恢复后是否重复工作。
4. 预算与作业计量是否一致，失败、retry、duplicate和未知费用如何报告。
5. pilot各episode的真实结果，以及工程验收、描述性观察和科研效能结论的边界。

## 13 可直接交给实施 agent 的启动指令

> 在 `new_feature/from_ARIS` 当前代码上，按 `plans/design/15-evidence-integrity-and-real-scenarios.md` 实施 S0–S7。先读取 AGENTS.md、该文件与 14-implementation-protocol.md，并核对当前基线。用户已明确要求每阶段末同时执行 Claude Code 与 Codex 的真实虚构项目场景，此项优先于 AGENTS.md 的旧单端限制。沿用阶段独立评审、修复重测与终审流程。
>
> 先完成 S0 的可执行测试底座和一次性资源/模型预检，然后按依赖实施。每阶段都运行对应 REG、两端构建和两个宿主的 SC-COMMON-01及专属场景，保留原始产物与恢复证据。真实模型与CPU运行不得被替身、预设分数或直接DB写入替代。历史数据按保守迁移处理，已知失败与不确定结果如实保留。
>
> 在现有授权范围内自主推进，不按阶段重复询问同一权限。遇到真正缺失的模型、资源授权或环境能力，先完成可独立的工作，明确写出阻塞条件；未通过的阶段不得报告完成。阶段完成后提交源码、测试与必要记录。最终给出逐缺陷覆盖、双宿主验收、迁移影响、资源和pilot结果；不把工程验收或小规模pilot解释成已证明通用科研优势。

## 14 依据与源码定位

所有源码定位按本文件准备时的固定提交。实施前若版本前进，定位以函数名与实际调用链为准。

| 依据 | 用途 |
| --- | --- |
| [实施协议14][R14]、[AGENTS.md][RAG] | 阶段顺序、宿主测试、模型与记录要求；双宿主范围采用本轮用户明确指示 |
| [共享核心 research_db.py][RDB] | 实验创建、确认、导入、复核、memory、预算与资格 |
| [metrics.py][RMET] | 原始单位、配对、独立重复与描述性outcome |
| [review_call.py][RREV]、[review schema目录][RSCHEMA] | 后端、回执一致性和工具契约 |
| [discovery.py][RDISC]、[memory.py][RMEM] | 候选ID、gate、经验校验与上下文 |
| [真实项目生成器][RGEN] | 复用现有真实CPU logistic任务与静态项目布局 |
| [benchmark工具][RBE]、[原A/B/C提案][RABC] | 评分、版本对照、truth隔离与未执行范围 |
| [ARIS experiment-plan][ARPLAN]、[Reviewer Independence][ARREVIEW] | 有界主张、竞争解释、直接读取产物 |
| [ARIS capture_filter][ARFILTER] | 区分运行事实与拟固化的科研/技能结论 |
| [DeepScientist][DEEP]、[Auto-RecSys][RECSYS] | 研究发现进入下一轮探索、执行故障与修复经验分开复用 |

[R14]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/plans/design/14-implementation-protocol.md
[RAG]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/AGENTS.md
[RDB]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/research_db.py
[RC]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/research_db.py#L2242-L2267
[RU]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/research_db.py#L2532-L2566
[RR]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/review_call.py#L288-L318
[RM]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/research_db.py#L3331-L3441
[RB]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/research_db.py#L1687-L1702
[RMET]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/metrics.py
[RREV]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/review_call.py
[RSCHEMA]: https://github.com/UnbearableFate/research-tree/tree/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/schema/reviews
[RDISC]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/discovery.py
[RMEM]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/shared/research-tree/tools/memory.py
[RGEN]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/scripts/make_rt_test_project.py
[RBE]: https://github.com/UnbearableFate/research-tree/tree/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/scripts/benchmark
[RABC]: https://github.com/UnbearableFate/research-tree/blob/616d6463eb397a8cfbbf88262d46b0d0e4a7c964/plans/design/test-logs/abc-benchmark-proposal.md
[ARPLAN]: https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/26b95cfa0d8747078e9e43b42e20952709e561b8/skills/experiment-plan/SKILL.md
[ARREVIEW]: https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/26b95cfa0d8747078e9e43b42e20952709e561b8/skills/shared-references/reviewer-independence.md
[ARFILTER]: https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/26b95cfa0d8747078e9e43b42e20952709e561b8/tools/capture_filter.py
[DEEP]: https://arxiv.org/html/2509.26603v1
[RECSYS]: https://arxiv.org/html/2609.10922v1
