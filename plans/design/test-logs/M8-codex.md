# M8 Codex 功能测试（原生回归通过；终审待完成；12 §1 科研 benchmark 未完成）

日期2026-10-07；scratch /tmp/research-tree-codex-20261007-1XA9OP，项目rt-test-M8-codex，隔离home-M8。自建Herdr w3:pN，主线程01a116f0-54ca-77b0-986f-14ff76595321，root线程01a11700-4b7c-79c2-8ef8-f7db0cf6aa31，observed gpt-6-luna/medium；主与worker Full Access。reviewer配置Anthropic Sonnet5.5；付费真实评审尚未执行。

## 提前声明的功能模拟夹具

native init前固定 supplied HEAD017dafbb5c9d0bcf79068d2560819c0d2d471f7a。真实CPU logistic训练/diagnostic保留，主accuracy公式0.80+.0025*(seed%3)+offset，其中baseline0，negative_a/negative_b各-.01，combination+.01。DATAtoy-combination-functional-sim-v1，全程simulation_only，不构成科学收益或整体research效率证据。声明保留M8-fixture-declaration.json。

root-only driver只有文档生成文本的toy-v1→实际sim元数据被控制器在首次CPU前授权修正；公共MCP、actor、CPU、import和accounting逻辑未改，newSHA46d70c3be434bba685d3334534dde1483414adeb9de6d4d729673637256e7788。六框架路径冻结，methods.py可变。早期模型误称YAML缺少合法默认字段并尝试修改被hook拒绝；控制器按actual config parse确认合法，不改用户配置，不视为product defect。

## 当前根证据

真实root七run (Adam sanity0、Adam/Momentum各0/1/2) 全部attempt1/succeeded/valid，RS1..7 settled每次actual_units1，总7/600秒。sanity200/100/2epochs/14steps，full1200/400/30/1140。主公式baseline值.8000/.8025/.8050，两个baseline EV均mean80.25pp/SD.25，仅functional。控制器读取全部manifest/metrics/usage/curve/log并核对provided HEAD、sim数据版本和声明，详见M8-root-manifest-audit.json。首次root continuation未开始CPU便接续，run实际无重复attempt。

初版结果叙述仍含toy-v1静态driver文字，后用新current v2更正sim元数据，raw/evidence数值和原Evaluation历史未改。相同inputs仅换doc的重评被设计拒绝，保留旧EV和superseded原结果可审计，未重训或直接改DB。T2 delivery.v2已交付，等待RLD正式验收。

15:53授权下一有限阶段H1/H2 methods-only各新functional_case，真实身份/真实sanity，RLD各一次真实Sonnet code_review clear后各三seed搜索，共最多8CPU；两者都交付后停止。combination、停滞、repair、探索及obligation尚未完成，不计通过。


16:15 UTC：旧M8最终实际9run（root7+H1/H2各sanity1）全部valid/settled，actual9node-seconds，无live agent或open reservation。两次真正Sonnet code_review皆CLI无prompt失败，raw fee0，故没有negative search/combination通过。独立页面244/244 false，控制器读取D41 gate报告及两个sanity交付，提取可读原始review JSON/交付，正常/exit并关闭自建w3:pN。旧项目/home已删除，证据tar SHA256 3cbd247710fa1d555b0b853e0566b32b297c36fcff22583f30d985e729b3d2af，native MCP 829条 SHA2066180c03fdf037c5a950af77304fe6c3aac6b0e191427ffb43ff48e3b62ac8；code.bundle已验证。失败保留，不以归档宣称M8完成。

全新M8r2已使用最新stdin及参数门修复构建安装，在自建w3:pP、Full Access/never运行，提供实际HEAD ea1db9899469a87c5ffb4bc064e522a0cf1201a8及同一预先声明simulation_only formula。root-only driver SHA46d70c3be434bba685d3334534dde1483414adeb9de6d4d729673637256e7788；未继承旧数据库、评估、结论或方法提交。当前只prepare/init/planning，须完整阅读计划后另确认根7run，不能计已通过。

16:45 UTC后续：M8r2主线程 `01a11726-5d7b-7951-a28c-37f3e2726e3c`、root线程 `01a1172e-4047-77c0-b419-2ff95979a909` 均 observed gpt-6-luna。完整计划经读取后正式确认，root7实际run全部attempt1/succeeded/valid/settled，控制器逐一核对原始manifest/metrics/usage/日志与simulation公式，见 `M8r2-root-independent-audit.json`。初版protocol缺artifact import要求被confirm正确拒绝，新v2补正、保留历史；根补充表的E2/s2与E3/s1转录hash错误由RLD独立读取更正为新报告，原CPU/DB/import未改，不计错误文字为通过。

两个不适用code_ref的实际public research_review调用已在任何backend调用前返回 `REVIEW_INVALID`，无review_started、无模型调用、无费用，验证新前置门。方法worker `h0001`（线程 `01a1173d-0db8-73b3-a67a-bac9e8eb6775`）和 `h0002`（`01a1173d-0f21-7ae3-8107-46871636e429`）均 observed gpt-6-luna、Full Access。独立methods-only commits分别 `63d72d2bc2d62b17b45f685e42d9191d20e1d61d`、`2332a119907e11e58fd25ac2140ecdc66ca18e0d`；真实sanity E5与E4分别导入并settled1秒。两份交付已到RLD，正在按已授权的一次真实Sonnet code_review/clear后各3正式seed流程推进；实际负向EV与组合仍未完成。

16:47 UTC：两次真正跨族Sonnet code_review已分别clear，RV1/D39 fee0.1705、RV2/D40 fee0.143235 USD，均backend=claude_code、model_observed=anthropic/claude-sonnet-5-5。第一次brief相对路径遗漏docs层导致实际前置REVIEW_INVALID/0费；RLD把文件放到实际参数所指位置后成功，不计前置失败为模型review。latest共享stdin修复在这两个新项目调用中已真正验证，原旧M8失败保留。正式三seed与组合仍待实际完成，当前独立九run audit已通过，actual9秒。
## 17:08 UTC：两个真实负向评估与去重缺陷

E6/FunctionalA 和 E7/FunctionalB 各三个实际 seed，配对同协议 Adam E2。原生 EV-0003/EV-0004 均 artifact_imported、mean 79.25pp、SD .25pp、三对差值 −1pp，outcome 为 negative_signal；公式为 init 前已声明的 simulation_only，CPU 训练诊断与用量真实，不作科研机制结论。控制器已核对全部15个真实 run/原始哈希/settled actual1：`M8r2-fifteen-independent-audit.json`。

正式建实验先被缺 SOTA、继而 screening_seeds=1 正确拒绝。RLD 设置 E2 为当前 SOTA、以 public extend_seeds 对原一 seed 实验扩至三 seed，未改变 YAML 或伪造 close 判定。H2 一轮 resume 误读了旧的“仅创建后停止”，重复登记 E8；原生 session 明确已收到新的唯一 E7 指令，属于模型执行错误，未观察到传输丢失。E8 无 run/reservation/CPU/评估，旧记录保留；续接原 worker 后只执行 E7 三次。

此误读同时暴露生产去重缺陷：扩 seed 后 create_experiment 原一 seed 请求不能返回同实验，存在重复提交相同 seed 的风险，违反 05 §5。新增两个真实边界回归修改前 2FAIL；修复后 CostEstimateTest 6PASS。同节点/代码/config 的 seed 重叠返回已有实验，需要更多 seed 时显式 extend_seeds，不改变扩展门。不同配置仍独立登记。共享源码修复与设计/API说明同步；新全隔离 Dedup 原生测试正在验证安装后行为，M8 当前缓存不热改。组合和停滞/探索尚未验证，不计通过。


17:19 UTC：去重修复已在全新 Dedup 项目（Herdr pR，原生线程01a11755-7c15-71d2-9094-c7b3227833b4、observed gpt-6-luna/Full Access）通过五步public MCP：n1→E1；同配置n3→E1且仍[0]；extend E1至3；重发n1→E1且仍[0,1,2]；walltime90→E2。代码/配置身份、get回读和原生McpToolCall completed返回由控制器独立核对，源码/dist/安装cache SHA一致a33a6a2907fcb5264a98aac2a3b6b77cc99e71192d1a8f5769cc7e860212974c。首轮SHA漏字参数拒绝/中止报告保留，未建立任何实验，按新指令正确读取HEAD后继续，不能把该输入错误当去重产品失败。全程零CPU/无run、task、reservation、review、evaluation；page41/41false。完成后结束收件箱处理，正常/exit、关闭pR，归档后删除项目/home。证据scratch/evidence-archive/Dedup-audit/与Dedup-controller-closeout.json；相关共享306测试/pack10与两层validate通过。


17:24 UTC：H3原生combines→H1/H2已登记；设计门正确拒绝缺中文固定节名、未逐字锚点、实验块缺成功/失败判据等输入，修正文档新版本保留历史。当前goal D54/v3根据已登记控制器指令D50有限扩展combination范围，原goal保留superseded，未放松代码门。H3提交0fb5d559c8ac9ab2010d144710b014b60eeb64a7，仅methods.py相对root改变；E9 sanity真实import/valid/settled actual1，控制器16-run完整audit与frozen-path scope通过。RV3一次实际Sonnet clear，严格is_errorfalse/terminalcompleted/modelUsage只Sonnet5.5，raw费.151233；三次raw总.464968。RV1有一次Glob permission denial（明确保留），RV2/RV3无permission denial；不声称所有调用都无拒绝。该Glob拒绝不等于评审失败，实际CLI完成、有效Schema及方法核验为true。协议eval_type实际synthetic_proxy，所有accuracy/run标明预声明simulation_only，不冒充simulation_only协议或真实科学测量。三review原文和SHA/费用详见M8r2-three-review-independent-proof.json。formal combo及零CPU停滞/探索门仍未完成。


## 17:46 UTC：组合、停滞、修复与探索额度的实际回执

H3同一methods-only commit的E10三seed实际执行一次，原生EV5为positive_signal：mean81.25pp、SD.25pp，配对E2三对差值均+1pp，artifact_imported。控制器逐一读取19次实际CPU的manifest/metrics/usage/log/curve/model及import SHA，全部attempt1/succeeded/valid/settled actual1，总19node-seconds；见M8r2-nineteen-independent-audit.json。根7、两个负向分支各4、组合4均含各自sanity，训练规模与诊断真实；主指标仍为init前冻结的functional simulation formula，无科研收益声明。T1–8均accepted；错误重复E8始终无run/reservation/CPU。

T01/T02旧实际调用使用同一决策文档 D69，连续 test-only no-findings 输入产生 streak1/none、2/structural、3/structural、4/human+report_to_user；同方向与未命名方向 child 均实际 STALL_STRUCTURAL 拒绝。合法不同问题 H4 仅元数据登记，无 worker/branch/experiment；current D73 以 public post_to_ui 上报。旧 D69 输入还实际复位至0/none。原生原文见 M8r2-T01-T02-native-proof.json。R6 终审确认同一批次被重复计数是产品缺陷，故这组旧调用不能作为“按不同决策批次升级及复位”的通过证据；原始回执保留，修复后由全新 Stall 项目重测。

U07实际把H1基于E6/EV3负向功能证据作no_gain/prunable/retired并记录reconsider_when。换名但同direction缺repairs节点被REPEATED_DIRECTION拒绝；两份合法新假设文档分别以repairs→H1建立H5/H6，第三次实际REPEATED_DIRECTION/max2拒绝。三个child都未新增CPU或review；无科学因果推断。原生证明M8r2-U07-native-proof.json。

U08第一次create_experiment携带不支持的baseline_experiment_id，实际参数拒绝发生在usage门之前，保留且不计通过；纠正参数后原生实际usage alert拒绝（19秒≥原18秒提醒线）。控制器通过独立human CLI仅临时设置search_limit100/alert.006，总预算600不增，未改DB或执行actor。H2新配置walltime11的planned E11/s0，71秒intent实际BUDGET_EXCEEDED明确exploration share：nonexplore15+71>85，total19+71≤100。H3 exploration新配置E12/s0同额71秒实际reserved/intent，未claim即public release；两probe均public cancelled，无job/usage/metric/import，19次既有实际run不变。原生D83/current报告及M8r2-U08-state.json保留；临时profile已通过human CLI恢复原YAML bytes。R04/R19及终审仍待完成。


## 17:55 UTC：R04/R19、独立收尾与清理完成

控制器在无live worker时通过human CLI应用同族测试profile，一次有效H3 public review实际REVIEW_UNAVAILABLE/Leader family/require_cross_family拒绝；不是虚构的REVIEW_SAME_FAMILY错误码。随后精确恢复原YAML，通过CLI config apply产生D89/v6。正常退出后刷新插件；源码/dist/cache research_db a33a6a29、capture_filter93cae1f6、review_call5302bef6一致，MCP /proc实际CODEX_HOME和新未登录CLAUDE_CONFIG_DIR已核对。相同有效RV3输入的唯一R19 review实际REVIEW_UNAVAILABLE/claude is not logged in；无backend降级、无额外模型调用/增费。实际原文M8r2-review-refusals-native-proof.json；auth与env证明分别M8r2-R19-auth-precondition.json/M8r2-R19-native-environment.json。Pi-ready分支仅确定性反事实覆盖，未声称真实Pi登录或真实Pi调用。

最终新current报告D92/final-closeout.v2纠正v1的screening/replication/project seeds转录和控制器audit路径，v1及D88原文/历史保留；真实screening[0]、replication[1,2]、project[0,1,2]。独立closeout核对19条实际run与先前19-run快照逐字段完全一致；另外2 cancelled probe无job/usage/metric/import，RS20 released/intent、19实际RS settled1、T1–8accepted、无live/openRS；全部73份current文档字节与注册SHA吻合。总19/600实际node-seconds，三次review raw总.464968与DB一致，原YAML bytes SHA fb035263...完全恢复。原生及控制器独立页面均506/506、stale=false。

17:55:25 UTC正常/exit后关闭自建pP，验证无人使用目录，Git bundle verify、项目/native原文归档后删除project/home；不再保留测试Codex/project。M8r2-controller-closeout.json、M8r2-final-state.json、M8r2-independent-page-check.json及evidence-archive/M8r2-audit、M8r2-readable、M8r2-review-raw供直接只读复核。原生回执1507条；project tar SHA256 2a1048b1410bcb0087c843ecd6897439df2f1f8d3ce5c009247cdae2ebad469e。清理累计22实例，Fable终审尚未执行，目标仍active。

## R6 终审后的范围与回归（18:23 UTC）

R6 有效终审报告 0 CRITICAL / 2 MAJOR / 4 MINOR，原始费用 11.34867 USD。Claude 工具接受模型自选 actor 的缺陷已移除，真实注册处理器的拒绝回归与源码、构建包各 25 项插件测试通过。停滞计数改为必须引用 current、字节未变的 decision 文档：相同节点/文档重试返回节点当前状态，不重复计数；改变 new_findings 不能借旧文档复位。三项数据库回归通过，完整共享 308 项通过。原生五批次及重复请求正在全新 Stall 项目运行，不以单元通过代替原生证据。

本文件的 M8 是 14 §4 的 Codex 功能场景编号。**12 §1 的 M8 完整研究 benchmark 完成标准仍开放，尚无固定资源下 A/B/C 实际收益或明确无收益结果，未获得豁免，不报告该实施批次完整完成。**本次原始目标是补齐 Codex 插件全部功能测试；功能模拟与 benchmark 工具冒烟不能替代 11 §2 科研效能比较。后续对照的任务、种子及资源草案见 [A/B/C 对照提案](abc-benchmark-proposal.md)。范围澄清已发给用户，尚未收到扩展范围答复；这不阻止继续已授权的功能修复与验证。

## 18:26 UTC：全新停滞批次原生回归通过并清理

Herdr自建pS、线程`01a11798-a34b-7ab0-9777-f318662c85de`，observed gpt-6-luna/medium、danger-full-access/never。全新安装source/dist/cache research_db.py一致`eaeab57893f0125b18cdf710f318d552dd7fce264ba4455535b1a9939b546fe8`。五个不同预声明current decision文档D8..D12与provided原字节一致，实际public note_findings结果依次1/none、2/structural、3/structural、4/human+report_to_user、0/none。batch1重复仍1，batch2之后重放旧batch1输入1仍当前2/structural，batch4重复仍4/human；null doc拒绝且不加账。每步独立public get/history与控制器快照相符，恰好DEC1..5五行，无重复或拒绝新行。

这是零CPU的元数据回归，项目仍planning、假说pending；输入1是init前声明的工程测试输入，不是科学发现。没有task/branch/experiment/run/reservation/evaluation/付费review；未把pending假说伪造成expandable，未重复声称native child-gate已在本次重测。原生Adam存在性核验实际verified。全部13份current文档字节SHA通过，v1报告转录修正用新v2并保留superseded历史；public与独立页面均40/40、stale=false。当前批次计数证据由此替代旧M8r2同D69调用，结构性child拒绝仍由原M8r2实际回执和修正后的StallTest共同限定支持。

控制器证据`Stall-controller-closeout.json`含八次成功调用及每次原始get/history、空doc拒绝和实际账本；`Stall-native-results.json`保存72个canonical原生工具事件。核验后正常/exit、关闭自建pS，18:26:42归档、Git bundle verify后删除project/home；累计23实例，当前没有测试Codex或运行项目。project tar SHA`d718134b915a3d0f8c84ef78878f68dc278a7688ec3c093bca9ee9d75391aafd`；可读证据`evidence-archive/Stall-audit`与`Stall-readable`。独立R7终审待执行，12 §1科研benchmark依旧开放。
