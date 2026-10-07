# 跨端修复后的 Claude 原生回归

状态：Claude 与 Codex R17 各自同一项目完整 11 §1.8 链均已完成、独立核验并清理。R14–R16 历史实例亦已清理；最新完整 diff Fable R15 有效：0 CRITICAL / 1 MAJOR / 1 MINOR；MINOR文档已修正，唯一MAJOR为未执行/未豁免的科研benchmark，整体批次未完成。

- 最终修复构建 r14：Claude 61 / Codex 69 文件。
- 使用 herdr 自建侧边 pane w3:pW，实际 Claude Code v2.1.292，claude-sonnet-5-5 / medium / auto；临时项目 `/tmp/research-tree-codex-20261007-1XA9OP/rt-test-ClaudeR14`。
- prepare、init 原生命令已执行；Full discovery，仅一个 method-transfer lens，无用户假说，triage_top_n/max_initial_nodes=1，600 node-seconds，实际 CPU toy-v1。
- Pi `auth check --provider openai --json` 原始结果 ready / oauth；配置 reviewer openai/gpt-6-luna，不做同族替代。
- 验证范围：真实 lens 固定身份与模型记录、未绑定 helper 拒绝角色代入、confirm_request 缺 docs 与 discovery 未通过时无日志/phase副作用、通过后用户确认、根 worker 实际 sanity 与两家基线、冻结与页面独立 check。
- 源和构建 Claude 插件宿主测试均 32 PASS；原生项目流程待完成。测试结束即退出、归档必要证据并清理临时项目。

## R14 首次原生回归：真实费用缺陷，停止并清理

- 实际主会话 `a224fada-f929-4817-9eb4-aa0faa7289bb`；lens `a0f092502171e82c4`、固定 actor `assistant/lens_method_transfer`，requested/observed 均 claude-sonnet-5-5。同一 lens 曾续接权限探针，但其只读工具集合没有 research_db，故该 MCP 读写探针未执行；真实 Read/Glob 和模型绑定已验证，不伪造读成功或写拒绝。
- 原生 confirm_request 缺 docs 与 discovery 未通过的两次拒绝均观察到，phase 仍 planning，消息没有新增确认请求。未绑定 general-purpose helper 的 Bash 命名 rld/main、research_db 读取、post_to_ui 均实际拒绝。
- 三个真实 Pi API 原始文件：RV-0001.v1.jsonl（3 turn_end）、同会话 retry（1）、RV-0002.v1.jsonl（4）。第一个 triage 格式无效且 retry 后仍 REVIEW_INVALID，第二个新的 triage 有效；均保留。
- 原始计费分别为 0.0022952000000000002、0.0004940400000000001、0.00200692 USD，总计约 0.00479616；旧适配器仅取最后回合，分别漏计 0.0007176 和 0.00121266 USD。`ClaudeR14-pi-cost-counterproof.json` 用原始回执验证修复后的解析费用恰等于每个 turn_end 的和。
- 源码改为只累计 turn_end，一回合在 message_end/agent_end 的重复消息不重复收费；新增成功后预算拒绝及失败终止仍计费的两项回归。43 项 review_call 测试通过（38.940s）。
- 控制器发现后停止新增工作；无确认、worker、训练、Evaluation 或预算预留。本次共同流程尚未完成，需全新项目。
- `/exit` 后 agent list 仅用户主 pane；自建 w3:pW 已关闭。项目已删除，native 日志、Git bundle、可读材料与 tar 已保存。`ClaudeR14-project.tar.gz` SHA256 `3dcac1a480d8130dcda57a0115d2d5de1e05de2c240eb72b3ef169bb1f87008a`，清理回执 `evidence-archive/claude-cleanup-receipts.json`。

## R15 新项目（启动记录）

新项目 `/tmp/research-tree-codex-20261007-1XA9OP/rt-test-ClaudeR15`，自建 pane w3:pX；同一实际 Claude 模型、full 单 lens 配置。仅提供 M0r5 已检查的静态真实 CPU trainer、runner、stats 和三份配置，无 DB、模型记录、run、结果或 review 状态。提供代码 HEAD `635de0b7a21f85032789216186c0fb0456aeefc5`；trainer 的 accuracy 直接来自验证集 correct/n，未使用公式。确认后的预算只覆盖根 sanity 一次和 Adam/Momentum 各三个搜索 seed，共七次，验收冻结后停止，不新增方法训练。

R15 启动实际版本为 Claude Code v2.1.293（宿主自动更新；实施者未主动升级）。初次两个斜杠输入在终端合并，prepare 报 Usage，尚无项目状态；原样保留失败。之后实际 shared prepare 成功，控制器观察到 idle/.venv 后单独重新提交原生 `/research-tree init`，不把参数错误当产品通过或以 shell 自行初始化替代插件入口。

## R15：费用已修复，评审序列化提示仍需修正

最新完整共享 311 PASS（309.493s）；review_call 源 43 PASS（38.940s）、构建 43 PASS（37.611s）。真实 full 单 lens 运行并保存 requested/observed 与原始候选；两次确认拒绝保持 window 日志和 phase 不变；helper 命名角色被 hook 拒绝。三次 triage 各在内部一次 follow-up 后仍 REVIEW_INVALID，前两次 JSON 不完整，第三次复制了 schema/properties 包装而缺顶层字段。全部失败及费用保留，未登记 Review 或创建节点/任务/worker/run，仍 planning。每个调用的收费已包含工具读取回合，后续独立计费审核验证。

提示修复只明确返回顶层评审字段值的合法 JSON data object，禁止输出 JSON Schema/properties 包装；不改变评审判据，不削弱 schema 校验，不增加内部补正次数。R15 已停止，不在本项目继续源修复；需 R16 全新目录验证。

R15 22:06:26 UTC 已 /exit、关闭自建 w3:pX，并删除临时项目及其专属 native 日志目录；SHA 校验的副本保存在 evidence-archive。tar SHA256 `126fab8e7aeb97d74432ea82741bd45219c0567272584cebd9ffeb8242a24bfe`。R16 新项目正在使用序列化提示修复构建，单 lens/单候选，不复制任何发现/评审状态。另开全新 Codex ReviewPrompt 项目（Full access/never）只检查实际 Claude Code proposal_review 格式，不运行训练。


## R16：最新构建的共同流程（过程记录）

新项目仅含独立提供的静态 CPU 代码，HEAD `b9f39d2f06d64f64936f53ae27d1649945eaa628`，旧状态未复用。实际 Claude Code v2.1.293、Sonnet 5.5 / medium / auto，full 单 lens 生成唯一候选；requested/observed 模型与固定身份均有原生记录。Pi ready/OAuth 实际成功的 triage、novelty_precheck、critical_review 均返回合法顶层 JSON 并登记，九阶段发现门 PASS。首个 triage 在项目记录创建前登记失败，属于调用顺序遗漏，费用与有效 JSON 原件保留；第二次才登记，不冒充首次通过。

两次 confirm_request 拒绝以及未绑定 helper Bash 命名 actor 的拒绝均真实发生，拒绝后 phase/window 无副作用。原生 Leader 因 init 提示又补充一个新的 init-plan 并再次发出确认请求；两个请求原文保留。控制器读计划与快照后逐条提交原生 `/research-tree confirm`，22:23:08 UTC 实际登记为 D-0017，并由插件启动 Root worker。确认前 snapshot 是 awaiting_confirmation、零 run/Experiment/reservation；本次只确认根七次 CPU，不执行候选训练。

发现 state 在最初 start 时的 executor_model 为 null，实际主模型稍后日志已记录，公开 research_review 每次仍按实时 leader_model 执行跨族前置校验；不声称 state 的初始模型字段已核实。共同流程验收、页面与清理尚待 worker 交付。

提示修复后 source/built review_call 各 43 PASS（39.516/39.622s），pack 10 PASS（4.266s），build 61/69、正式两层 Claude validate exit 0。全新 Codex ReviewPrompt 格式回归已实际完成并清理，详见 ReviewPrompt-codex.md；真实 Sonnet 结论 REVISE，schema 登记成功，费用与材料/权限限制保留，不作科研方案通过声明。


## R16 最终独立核验与清理（22:30 UTC）

- 原生主线程 ddf2cd46-c3d4-4c03-85fa-8d0a52964f33；Root a755543c6face4ae4 与 lens a979356110c7d1606 requested/observed 均 claude-sonnet-5-5。225 个配对 native 工具事件、4 个原始 host JSONL 文件与固定身份模型日志保留。
- 七个 CPU run 均 attempt=1、succeeded、valid=true；七个 reservation 全部 settled，实际 7 node-seconds。原始 manifest/metrics/usage/日志/曲线逐个 SHA 与导入记录核对；accuracy 为验证集 correct/n，未用 simulation 公式。正式 counts=1200/400/30/1140，sanity=200/100/2/14。Adam 三 seed 均值 90.917pp，Momentum 90.167pp，只验证 synthetic_proxy 框架，不作科研收益结论。
- T-0001 实际 accepted；EV-0001/2 由原生 Leader 验收，SOTA 设 E-0002，harness_ref=4f3d8b961b816b0e7ae347f309a06764a9248eb1。初次 create_experiment 因尚未冻结而拒绝，Leader 审核并冻结后同一 Root 恢复；保留任务提示与接口顺序不一致，未放松接口。sanity attach_job 在进程结束后调用，其余六次先 attach；七次计费与原始 job 对应。
- 21 个 current Doc 登记 SHA 均与实际字节一致；lens raw/shard 字节一致，九阶段门 PASS。独立 build_site check：page_version=db_version=131，stale=false。
- 四次真实 Pi 调用（含项目记录未建立时的初次登记失败）每个 turn_end 的原始费用合计 0.00660032000000000014 USD，raw、失败及调用日志保留。初次失败发生在项目记录创建前，不能计入当时不存在的 project；后续三个成功登记的 project.review_cost_usd=0.005049，全部调用成本另由原始/调用账本保留。
- 两个 confirm_request 拒绝与之后两个有效请求均有原文；未绑定 helper 的 Bash --actor 拒绝真实发生。初次控制器断言误把 MCP 文本拒绝期待为 is_error=true；改为按拒绝原文/发送回执核验，产品及原件未改。
- sanity 的 model.pt 约370字节因未统计评估而暂未到期清理；旧框架源读取 grep 被角色 shell guard 拒绝，原始失败保留。测试结束整体归档中保留必要权重，临时项目全部删除。
- 正常 /exit、agent list 确认退出，仅关闭自建 pY；native 原始副本 SHA 一致、Git bundle verify 通过，22:30:54 UTC 删除项目及专属 native cache。tar SHA256 `c2139a36f1f642bb1fa525b8b92a96ec2a27b18bba3b2d003727e555c2e0bd8a`。三次 Claude 的历史失败不混作 Codex 案例通过，最新共同流程通过也不意味着完整 11 §2 benchmark 完成。

证据：ClaudeR16-controller-closeout.json、ClaudeR16-final-state.json、ClaudeR16-native-results.json、ClaudeR16-native-refusal-proof.json、ClaudeR16-independent-page-check.json、ClaudeR16-cleanup-proof.json，以及 evidence-archive/ClaudeR16-*。


## R14 终审后的 R17 E2E 补测（进行中）

Fable R14 有效，0 CRITICAL / 3 MAJOR / 2 MINOR，原始费用 6.283198499999999 USD。确认 R13 修复与 R16 共同流程真实有效；另要求 Claude 单项目方法→追加重复→五维复核→结项及发布说明。完整科研 benchmark 仍 OPEN。

新项目 ClaudeE2ER17 与 Codex E2ER17 在原生 prepare/init 之前只复制已检查的静态 CPU 代码/配置，初始提交 684e51fd6ae0f52669486b9b47014948b92bab03；没有 DB、结果、review 或模型状态。预声明主 accuracy 为 simulation_only 公式，实际 CPU 训练/原始 measured_logistic_accuracy、loss/count/usage 均真实；protocol 使用当前合法 synthetic_proxy，明确结论限于功能测试。不是科学提升证明。Claude 原生 MCP 写入，不使用 Codex adapter driver；Codex managed worker 可使用已检查、固定身份的真实 MCP job driver。

Claude 原生 v2.1.293/Sonnet5.5/medium/auto；Codex 原生 v0.160.1/Luna/medium/Full access/never。两项目都先观察到 awaiting_confirmation、零worker/run/RS/current DocSHA 后，再分别提交原生 /research-tree confirm 和用户本人的 $research-tree confirm；先只授权 Root7，之后方法sanity+screen0与显式extend补1/2分阶段推进，最多11真实CPU，至多两次新review调用/阶段，不为GO强迫结论。

R17 build 62/70（新增共有 RELEASE.md，随两端打包）；同一构建完整共享311 PASS（320.468s）、组装全部335 PASS（329.319s）、adapter24 PASS（9.190s）、pack10 PASS（6.157s）、Claude source/built各32 PASS、正式两层validate exit0。最新 install与exec/resume/UI纯传输夹具均实际通过并立即归档删除，transport已35项。单元与传输通过不替代进行中的真实端到端链。

## Claude R17 最终完整链与清理（23:20 UTC）

- 主线程 `0fc4b774-a3e1-452a-a49e-7d79f8685bcc`，Root `aaa4b9104888ef45c`、方法 `aab84f2e8db310e00`；三者真实 observed 均 Sonnet 5.5，方法追加仍恢复原身份。346 个配对 native 工具事件与三个原始宿主 JSONL 保存。
- Root sanity 加 Adam/Momentum 各三个 seed，T-0001 accepted，SOTA E-0002，EV-0001/2。方法第一次遗漏 RLD 创建分支，在私有临时 main 提交后被 create_experiment 门拒绝，尚未运行 CPU；RLD 建立 BR-0001/worktree、搬入同一方法改动并恢复私有 main，原提交另保留 Git ref。有效方法 commit `8815f0cb76ad56887227ec4a9a6f2d9ea927745d` 仅改 methods.py，六冻结文件逐字 SHA 相等；没有削弱接口或复用旧 run。
- E-0004 方法 sanity、真实 Pi code_review clear、E-0005 seed0/EV-0003；首次 code_review 缺 code_ref 提前拒绝且零费用。有效调用的第一份 JSON 经一次内部格式补正，原件和 retry 费用均保留。n=1 的 SD 为 null、gate=false；控制器先独立核验九次 CPU 后才授权公开 extend_seeds(E-0005,3)。只补 seed1/2，owner h0001 实际 evaluate 为 EV-0004。原 seed0 的完整 run/import/manifest/metrics/usage/日志/曲线/model 字节和 EV-0003 记录均未变。T-0002 accepted。
- 最终十一 run 全部 attempt1/succeeded/valid；十一 RS 全部 settled，实际 11/600 node-seconds。主 accuracy 的 +1pp 是立项前预声明公式，实际 measured_logistic_accuracy/loss 与 Adam 逐 seed 相同；没有优化器收益主张。
- 五维真实 Pi/Luna：numbers pass、protocol uncertain、method_code uncertain、novelty pass、theory pass，各一次公开调用。protocol 保留 baseline Python3.13.14 与方法 Python3.12.3 的差异；method_code 保留独立源码/哈希核验不足。跨模型 novelty pass 仅验证无新颖性主张，RLD 自身 novelty fail/theory pass，二者明确区分。资格仍 false，缺独立确认且复核未全部通过；公开 decide 使项目 not_go，节点 retired。未追加确认 CPU。
- 六个已登记 review 的七份原始 API 文件（含内部补正）按所有 turn_end 合计 `0.01909484000000000094 USD`，DB 六位记录 `0.019095`。控制器首次费用断言遗漏 retry 文件，调查后计入原始 retry；产品计费正确，未改金额或原件。
- 三十 current Doc SHA 全部核验；独立页面208/208、stale=false；两个 worker 都结束。23:20:27 UTC 正常 /exit、观察 shell 提示、关闭仅自建 w3:p0，Git bundle verify 和 native 副本 SHA 通过后删除项目与专属全局 native 日志目录。tar SHA `edbeb54ef8bcbde1e8c3307bab55a27a6bd464f58cf6832c817c88adbfcf2452`。

证据：`ClaudeE2ER17-final-state.json`、`-native-results.json`、`-controller-closeout.json`、`-final-eleven-run-independent-audit.json`、`-replication-independent-proof.json`、`-independent-page-check.json`、`-cleanup-proof.json` 与 `evidence-archive/ClaudeE2ER17-*`。工程完整链通过不代替仍未执行的 11 §2 科研效能比较。


## Codex R17 最终完整链与清理（23:30 UTC）

- 当前R17插件原生安装，v0.160.1/Luna/medium；主线程01a1188b-e916-7973-8329-ca42f3a44c19，Root01a11894-3d40-76a1-92cf-12a301d051f5，方法01a118a0-d5ea-7d63-9270-331e51ea4d5f，requested/observed均Luna，追加恢复同一方法线程。主/worker的全部归档turn_context均Full access/never。原生`$research-tree confirm`确实通过skill映射为confirm，params.words逐字为`$research-tree confirm`；确认前零worker/run/RS与current DocSHA独立核对。
- 初次Root协议把steps=1140误放入顶层match，而runner实际输出counts.steps，正式seed0导入正确拒绝PAIRING_MISMATCH。RLD检查后登记协议v2，仅移除错误match字段、保留required_counts.steps；同一Root重新导入原manifest，未重跑CPU，随后只运行原来缺失的五次。七个Root作业全valid/settled，T1 accepted/SOTA E2。错误协议、首次拒绝和恢复都保留。
- RLD在方法worker前建立BR1/worktree并明确owner h0001；有效commit872621fcb0cd9dab71f85a0965121ae64415a548仅改methods.py，六冻结文件SHA相等。sanity、真实Sonnet code_review clear后只运行方法seed0；owner在全部有效后evaluate为EV3。控制器九run独立审计后授权原生extend E5到三seed，只新增1/2并由同一owner评价EV4。原seed0全部记录/证据文件与EV3完全不变。worker初次未正式update_task交付，RLD恢复同一身份补齐delivery后独立accept T2，没有新CPU。
- 五维真实Sonnet均pass（D38–D42），RLD另登记自己novelty/theory文档并绑定当前代码后才通过状态门；缺正确依据的首次decide实际拒绝。结论仍NOT GO：主指标是预声明simulation_only offset；独立确认未授权/未运行。H1 prunable/retired，最终get_eligibility含DISPOSITION_RETIRED/CONFIRMATION_REQUIRED，cross-model与RLD两组状态明确展示；没有科研收益或GO主张。
- 六个原始Claude Code评审JSON均is_error=false/terminal_reason=completed/仅Sonnet模型，实际CLI费用合计0.85856679999999995 USD，DB六位逐次记账0.858566；全部原件与限制保留。numbers未核验usage/DB JSON等限制由控制器独立manifest/usage/RS审计补足，不改写review。
- 十一实际CPU作业全attempt1/succeeded/valid、十一RS settled、实际11node-seconds；四十一current Doc SHA全匹配，独立page257/257false，无live worker/open RS。final report v1缺六章节且路径前缀初错，原生RLD保留v1并登记v2补齐后正常项目decide not_go；相关拒绝和版本历史保留。
- 470 canonical native事件、65成对自定义工具回执和849条选定归档会话回执保留。审计通过后晚到的已完成worker通知只需读取/ack；控制器Esc停止一条额外通知读取，再正常/exit、观察shell提示，23:30:38 UTC关闭仅自建p11、Git bundle verify通过后删除项目与隔离home（含授权复制的登录凭据）。没有停止活跃科研worker或作业。
- tar SHA f783e6361d9c5b8b3a58a24eec93e398d5213473bb36817c6982d5b3d9e43b41；257可读文件新增后Codex累计27案例3945文件；四个Claude案例另列，纯传输35。scratch无rt-test-*或codex-home-*目录，Herdr agent list只剩调用者，用户pane未关闭。

证据：E2ER17-final-state/native-results/controller-closeout/native-permissions-proof/replication-independent-proof/final-eleven-run-independent-audit/independent-page-check/cleanup-proof.json，以及evidence-archive/E2ER17-*。全活动累计66份原始API费用记录与15次阶段审查（含失败）总账见review-fee-ledger.json；总账只含有报告的reviewer CLI费用，不包括宿主Luna/Sonnet账单或五份未知原始费用。


## R15 独立终审与最终限制

Fable5.1/high原始is_error=false、terminal_reason=completed、仅Fable模型；有效0 CRITICAL/1 MAJOR/1 MINOR，费用6.9200405 USD。唯一MAJOR是完整科研benchmark仍未执行、未获豁免；MINOR是09 §2.2的Pi费用说明仍写最后回合，已按真实正确实现对齐，运行时代码未变。原始审查结果保持不改，post-review文档SHA另记录；不能宣称14 §6整体批次完成。

reported CLI费用总账现为Pi/Luna0.04337552000000000175、Sonnet5.5 5.49663639999999995、Fable5.1 116.3902470000000005 USD；包含原始失败/内部补正/阶段无效输出，排除宿主账单、汇率与未报告费用。五份历史raw费用未知。R15结束后，八个历史诊断DB/stray brief文件逐字SHA保存到evidence-archive/remaining-diagnostic-artifacts，原临时目录、空helper目录和可重建cache已清理；scratch顶层只剩证据归档目录和审计文件，不留测试项目。
