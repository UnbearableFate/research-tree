# Codex 真实宿主补测方案

日期：2026-10-07。范围：补齐 14 §4 的 Codex 宿主测试及 11 §1.8 的小型端到端验收。此前仅测试 Claude 的阶段决定不作为本次 Codex 补测的豁免。历史 M1-codex 中止记录保留。这里的 M0–M8 是 Codex 功能场景，不表示 12 §1 的全部实施批次完成；其中完整 A/B/C 科研 benchmark 标准仍开放，未获得豁免。

当前结论：原生功能补测与修复证据已完成；有效Fable R15为0 CRITICAL/1 MAJOR/1 MINOR，文档MINOR已修正，唯一MAJOR为完整科研benchmark未执行、未豁免。14 §6整体批次仍未完成，等待用户对提案范围与预算/豁免的明确决定。

## 环境与证据

- 源码、构建包、安装缓存必须一致；修复后重新构建，在全新项目中重跑受影响场景。
- scratch：`/tmp/research-tree-codex-20261007-1XA9OP`。每批次一个 `rt-test-Mn-codex`；配置使用 version 2，秒级 CPU toytrain，无 GPU 或集群作业。
- 通过 herdr 在侧边 pane 加载原生安装的插件。Codex 主模型 `gpt-6-luna`、reasoning medium；worker/UI inherit medium；reviewer `anthropic/claude-sonnet-5-5`、thinking medium，走 Claude Code CLI。
- CODEX_HOME 与日常配置隔离。仅复制登录与所需配置，不提交凭据。用户已授权临时 hooks、插件 MCP、依赖安装与测试提交，并要求开启的 Codex 测试项目使用 Full access；主会话以 `--sandbox danger-full-access --ask-for-approval never` 启动。新隔离 config.toml 明确设置 Full access，后台 worker 继承该用户选择；插件默认 worker workspace-write、UI read-only。
- 每批保存实际命令、pane/线程、requested/observed 模型、数据库只读快照、消息与运行日志、页面 `--check`、失败及修复、按基座累计评审费用。模型无法核实时明确记为未验证。
- 单元测试或本地 Responses fixture 不能替代真实模型、真实插件 MCP 与 worker 的成功证据。

## 批次矩阵

所有批次共同执行 prepare → init → 立项计划 → 显式测试确认 → 根 worker sanity/基线 → 冻结；核对数据库和六视图页面。

| 批次 | 额外真实宿主场景 | 核对要点 | 状态 |
|---|---|---|---|
| M0 | prepare 保留已有文件；配置展示与版本应用；确认前拒绝 worker | 原文、phase、文档版本、权限、root task | M0r5 根七run/冻结/验收/页面与R04通过；修复后默认UI五操作在新M4通过，功能证据已核验；整体批次未完成 |
| M1 | 原始指标与结果文档声明不符；正常导入与幂等重导 | STAT_MISMATCH/核验拒绝，无错误 Evaluation；权威统计 | 实际数字拒绝/幂等、方法追加重复与有依据NOT GO、R04和393/393页面通过，功能证据已核验；整体批次未完成 |
| M2 | 一个 seed 轻微负向；达到搜索 seed 上限仍接近门槛；追加重复；资格失效 | inconclusive 不强制剪枝；工程失败不是科学负向；旧证据失效 | 真实controls+search、单seed -0.25pp/三seed上限inconclusive通过；R04/恢复/367页面通过；额外资格失效在M4公开撤回确认run验证；实例已退出清理，功能证据已核验；整体批次未完成 |
| M3 | 两 worker 争用最后额度；提交 unknown 后恢复/对账；重复结算 | 仅一个准入、不重提、原 job/attempt 继续、实际费用保留 | 真实两worker争额、原job/attempt恢复、重复结算、R04与255/255页面通过，功能证据已核验；整体批次未完成 |
| M4 | reviewer 可用、不可用、同族；候选五维复核；费用告警 | Claude Code backend 与 observed 模型；R04、R14、R18–R22；独立只读与无降级 | 真实五维复核/六独立confirm/functional GO、OB1–4、显式撤回资格失效、R04/R14/R19及609页面通过；20真实CPU/完整账务/退出清理完成；功能证据已核验；整体批次未完成 |
| M5 | 缺 claim map；sanity 连续三次失败；审查/消融/交付门 | X01、X06/X07；task_blocked、决定文档；结果到 claim | 根七run/X01/X06/X07/R04/R19/297页面通过；实例已退出清理，功能证据已核验；整体批次未完成 |
| M6 | 只给方向；用户种子；低排名/ABANDON 用户种子；中断恢复 | 两栏报告、用户种子查新、待用户决定、accepted 阶段不重做 | 方向-only及用户种子两场景通过，用户种子16/16仍查新/ABANDON待决定；根七run/页面/R04均通过；曾跳过的本批R19于19:25由全新M6R19实际原生探针补齐，零训练/评审费且11/11页面一致，已退出清理；功能证据已核验；整体批次未完成 |
| M7 | 运维噪声 lesson；要求扩权的记忆；proposed/verified、反例与依赖变化 | 过滤与权限不变；context_pack/文献；清理保留重算证据 | M7r4未受影响K02/R04/R19等原生边界通过；新M7r5精确六负例/合法proposed及verified/context2141字与页面151通过，实例已退出清理；功能证据已核验；整体批次未完成 |
| M8 功能场景 | 两个负向父节点组合；重复方向/修复上限；探索额度；停滞/obligation | typed relations、预算与拒绝门；新发现；未决事项阻止 GO | 新M8r2实际19run/三Sonnet clear、两负向EV与组合positive_signal、U07/U08、R04/R19及page506通过，已退出清理；Dedup五步通过并清理，OB1–4在M4验证；旧T01/T02重复同文档的计数证据因R6发现而撤销，修复后全新Stall五个不同批次及重试原生回归通过并清理，功能证据已核验；整体批次未完成；12 §1完整科研benchmark未完成 |

| E2E / 11 §1.8 | 同一项目完整链；补齐M1/M4拆分覆盖缺口 | screen1→原生extend3→只新增1/2→真实五维→资格拒绝→NOT GO | 原Codex E2E已通过并清理；最新ClaudeE2ER17完整链11实际CPU/6真实Pi评审、原seed0/EV3不变、30current SHA/page208、NOT GO与退出清理通过；Codex E2ER17最新worker提示全链11CPU/6真实Sonnet/41current SHA/page257及NOT GO通过并清理，Fable R15有效；科研benchmark仍OPEN |

## 横切功能与完成标准

1. 按 14 §2 运行共享测试、打包测试、构建、Claude 校验、Codex adapter 与原生安装检查；保留失败原文并查明原因。11 的 M/E/U/B/K/R/X/O/T 确定性覆盖逐项核对。
2. 真实模型小型完整流程覆盖：建项目、确认、基线、一个方法、产物导入、追加重复、候选五维复核、独立确认、GO 或有充分依据的 NOT GO 结项。
3. 至少一次真实 worker 的活跃消息、同身份 resume、中断后恢复；至少一次 unknown 提交对账；独立 UI 的 status/pane/config/需求草稿/提交、原话与动作账本、收件箱与回执。
4. 核对配置未知字段/锁定门、迁移工具、文献检索/核验/缓存、版本化文档、证据清理与展示、benchmark 生成/评分入口。完整 A/B/C 科研效能比较属于 11 §2 的独立实验；本次验证这些工具功能，不把小型功能测试宣称为研究效能证明。
5. 本轮已按开始时 AGENTS.md 的要求，委派新 Claude `claude-sonnet-5-5` high 会话执行 claude-mod 最终测试；四条命令和 22 项插件测试通过。期间用户修改了 AGENTS.md，删除该阶段测试要求，保留用户改动。14 所要求的独立 Fable 审查沿用其严格成功判据。只给路径，记录原文。
6. 各矩阵项必须有当前证据证明。受阻、跳过、模型缺口或部分运行不得记为通过；全部完成前保持目标 active。

## 已发现问题

- 原生安装检查把 MCP 工具数写死为 5；当前已实现 research_review，实际公开六个工具。改为核对完整六个工具名称集合，仍拒绝缺失或额外工具；最终构建安装检查已通过。
- 安装与会话 fixture 的 discovery、protocol 和 metric 配置曾不匹配生产门；修正测试输入，未放松生产门。最终原生安装、后台会话检查均通过。
- 首次 init 在 SessionStart 后建立项目，原 hook 会漏记实际主模型，导致独立跨族评审缺少宿主族。回归测试先复现失败，再修复 PostToolUse 的实际模型登记。17 项 adapter 测试通过；新原生会话已产生正确 observed 记录。
- 主会话与后台 MCP 等待上限原低于运行时评审等待；客户端统一 3900 秒，服务子进程 3800 秒，包装器整次上限 3600 秒。Fable 前三轮均只有 MINOR；后续真实 worker 新修复仍需终审。
- M0r2 的后台 worker 暴露 CODEX_HOME 被 MCP 环境过滤、Git 写入受限和阻塞消息类型不明确。M0r3 实际主会话通知已通过，进一步诊断后补齐后台显式 MCP 环境，开启 M0r4；原目录保留，未计根流程通过。
- M6 首轮 D2 缺正式只读 lens 助手；已补齐入口和权限门，21 项 adapter 通过；M6r2 的两个实际助手与 D3 通过，D4 暴露 Claude CLI Schema 方言不兼容，已修复并开启 M6r3。

## 当前执行位置（15:20 UTC快照；下有后续更新）

- 最新共享298、memory13、adapter23、pack10、Claude24及两层validate、git diff --check通过；最新功能源码已构建61/69。final9真实native transport两个入口此前通过，具体边界见基础设施记录。
- M0/M1/M3/M6已结束的真实实例与M7失败实例保留关键证据后清理；归档与SHA清单见codex-cleanup.md。用户要求测试结束退出Codex并清理不会复用的临时项目，后续每项均照此处理。
- M2：自然方法同提交三seed结果真实inconclusive，U01/U02、R04通过；原Anthropic配置字节已恢复，旧错误T2取消并保留history，独立页面367/367false，无live/openRS，14/600秒。Codex正常退出，自建收尾pane w3:pM关闭，实例已清理。资格撤回/失效额外边界尚不宣称native通过。
- M4：自建w3:pJ仍工作。默认独立UI五操作/根七run/H1同commit sanity已通过；实际Sonnet code_review clear/RV3费用0.1574008，前两次CLI无输入拒绝的原日志保留。真实controls E5/方法E6三seed已执行，总14秒；新Evaluation对实际当前SOTA重评分不重跑，五个candidate_recheck进行/已产生实际结果，独立confirmation/R04/R14/R19与最终收尾未完成。全程simulation_only，不声称真实科研改进。
- M5：X01/X06/X07/R04/R19均有真实原生回执，五次故意nonfinite工程失败共5秒，根7秒，总12/600，无live/openRS。独立页面297/297false、原配置恢复。same-thread Full Access resume后正常退出，实例和home已清理；终审待完成。
- M7：原M7r2噪声缺陷真实失败、权限/注入拒绝等原记录保留。修复后全新M7r3/最新home在自建w3:pK运行；控制器完整阅读实际计划/current v2配置协议并正式确认仅根七run。真实YAML单run上限10m，根experiment各申请10s，保留实际区别；methods不冻结，六框架路径/真实HEAD绑定。记忆filtered/proposed/verified/context/反例重测仍待完成。
- M8：自建w3:pN、最新安装和Full Access，原生规划进行。真实CPU训练和账务须执行，simulation_only主指标的预设正负公式已在任何native init之前固定。两个负向父节点/combines、停滞/repair/obligations/exploration尚未执行，不计通过。
- 所有未完成功能与Fable R5完成缺口仍保留，目标保持active。最终不得以单元、transport、声明的simulation公式或归档动作替代所需真实功能证据。

### 15:53 UTC 后续状态

共享最新299通过（304.010s）；新 credential disclosure 回归在修改前2FAIL，修复后memory14通过。adapter23/pack10/Claude24、两层validate、61/69构建通过。M7r3 原始恶意literature current失败明确记录，之后换payload的成功不抵消原失败；有限审计与迁移dry通过/页面210，已正常退出/归档/删除原项目和home。新M7r4最新安装/Full Access，正在仅规划，尚未确认CPU或原攻击复测。已清理16个完成/被替代的真实实例，临时原安装transport/CLI夹具也已按cleanup记录清理。

M4的实际五个search维度复核通过后执行六次独立confirm CPU（E8 root对照+E9方法同commit），当前确认统计/复核/资格和收尾未完。E7错误owner未执行，原计划/拒绝历史保留；改为新明确root-owner E8后成功，未改旧身份/重跑旧CPU。当前只允许完成确认门与明确功能性obligation测试，不增CPU。M8真实根7run的manifest/metrics/usage已由控制器核对，simulation-only/actual CPU与公式预声明一致；授权两个真实worker各sanity+三seed、各一次真实code review，共最多8CPU，两个negative evidence尚未交付。combination仍未授权/未计通过。


### 16:37 UTC 后续状态

M4完整functional GO前资格为confirmed/true且20run原始证据已核对；随后test-only公开撤回确认run，真实CONFIRMATION_STALE、历史GO保留，并更正控制器之前的临时JSON自动失效错误。R04/R14/R19三probe实际拒绝零增费，source/cache经停止后刷新一致/真实隔离未登录MCP环境已核对，独立page609/609；已正常退出、关闭自建pJ、归档删除原项目/home。其raw Sonnet fee总1.2316206，DB逐次六位取整1.231619。全部为预声明simulation_only，无科研结论或GPU声明。

M7r4有限审计完成：根7真实CPU、明确rate-limit/backend-cause、两原文credential文献、扩权/guess拒绝、verified/反例/context、K02真实config pointer变化、R04/R19、两dry migration/page197、原配置bytes恢复，已退出删除旧项目/home。额外“transient operational timeout”“transient scheduler interruption”仍准入proposed，未计成功，现补窄模式；公开准入回归2FAIL前/15测试通过后。新M7r5最新安装/home/Full Access原生只规划，精确原文输入在任何init前固定；受影响场景仍待native通过。M8旧项目CLI故障失败已归档删除；新M8r2最新stdin/参数门已实际完成root7、两错误code_ref提前拒绝零费用，正执行两个methods-only负向分支，两个真实EV及组合仍未完成。

cleanup receipts已19个真实实例，加已完成transport/benchmark临时夹具。当前仅自建pP(M8r2)和pQ(M7r5)测试Codex/project仍需继续；全部未完成门/Fable独立终审与Git最终提交仍保留，目标active。


### 17:55 UTC：全部原生批次完成，独立终审待执行

M0–M8当前矩阵及Dedup受影响回归均有当前原生证据；历史失败保留而不当作通过。M8r2实际19次CPU/三Sonnet clear/负向父节点与组合功能评估、停滞升级、重复与repair上限、探索份额、同族/未登录拒绝、原配置恢复及page506通过。M7r5精确六负例与实际2141-char context已通过；所有22临时实例正常退出或被替代后归档清理。完整可读证据在scratch/evidence-archive（22案例、3296文件），原始 tar/native/code.bundle 与SHA回执仍保留，凭据未归档。

最新共享306/pack10通过，adapter23/memory15/Claude24及两层validate、61/69构建、安装和后台会话入口均已有通过记录。原生Pi-ready未具备登录条件，只验证确定性选择逻辑与实际未登录拒绝；CPU-only的功能模拟不替代完整A/B/C科研效能实验、GPU/集群或真实科学改进。Codex自身未提供费用账单，不推断费用为零；实际CLI reviewer费用单独累计于review-fee-ledger.json。当前只剩14规定独立Fable终审、发现处理、记录/Git收尾，目标保持active。


18:26 UTC最新：R6发现的Claude actor与停滞重复计数已修复；共享308/adapter23/pack10、Claude源码与构建各25通过。全新Stall public MCP五批次、重复/旧批次不复位/null拒绝及每步get/history独立通过；恰好五行账本、13 current SHA、page40/40false、零CPU/付费review。已正常退出、关闭自建pS、删除project/home，累计23实例均清理。旧M8r2同D69的按批次通过声明撤销，原始证据保留。14规定R7独立终审待执行；12 §1完整科研benchmark仍开放，见abc-benchmark-proposal.md，不把功能验收报告为全部实施批次完成。


21:19 UTC最新：E2E单项目11 §1.8整链实际完成并退出清理；数字复核fail阻止GO，保持真实结论。原生功能场景累计25实例，全部清理，32 transport也全部清理；当前验证32 Claude/source+built、308共享、24adapter、10pack和两层validate通过。新R13快照补齐exact validate命令/退出码/时间/日志/hash。独立R13最终审查待执行；完整A/B/C科研benchmark仍未执行、未获豁免。


23:20 UTC最新：ClaudeE2ER17在同一项目完成11 §1.8全链并清理，跨模型uncertain、RLD novelty fail和Python环境差异原样保留，NOT GO真实阻止收益主张。Codex E2ER17已经实际完成11CPU、单seed到显式追加的原seed0/EV3不变验证，正在五维Sonnet复核。最新同一R17构建311/335/24/10/32与两层validate及两个原生传输入口全通过；35传输夹具、26 Codex和4 Claude旧实例已清理。完整A/B/C科研benchmark仍OPEN；原生功能与完整实施批次分别记录，不声称全部完成。


23:30 UTC最终原生状态：ClaudeE2ER17与Codex E2ER17两个R17单项目完整链均完成且退出清理。Codex最新owner/全部有效后evaluate提示有真实受影响worker证据；27 Codex/4 Claude/35 transport临时目录均已移除，3945个Codex可读证据保留，另含Claude独立原件。R14除完整科研benchmark外的发现已有源码、最新构建全命令集和原生证据处理，完整diff R15审查仍待执行；benchmark未执行、未豁免，整体14 §6不能标记完成。


23:46 UTC终审：Fable R15有效0 CRITICAL/1 MAJOR/1 MINOR。R17全链与发布说明等既往发现已处理，未报告新的功能代码缺陷；09 §2.2费用文档MINOR现已修正，运行时代码未改。完整科研benchmark为唯一MAJOR，继续明确未执行/未豁免，整体14 §6未完成；原始审查与post-review验证分别保留，不重复审查以消除已知开放标准。所有测试实例已退出清理。
