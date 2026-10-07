# Codex 临时测试清理记录

2026-10-07。用户要求每项测试完成后退出对应测试Codex，清理不会继续使用的临时项目。仍在重测或收尾的项目暂留，测试本身未通过的旧实例保留失败证据后由新实例取代。测试agent退出与pane归属分开处理：用户pane不关闭。最新：27 个 Codex 模型实例、4 个 Claude 模型实例及 35 个纯传输夹具均已清理；没有仍需运行的临时测试项目。

15:04 UTC已清理M0/M0r2/M0r3/M0r4/M0r5/M1/M3/M6/M6r2/M6r3/M6-seed/M7/M7r2项目，以及对应隔离CODEX_HOME（M1另含home-M1r2）。删除前检查没有进程以项目/home为cwd。关键文档、数据库、manifest/metrics/log/usage、实际review原文保存为`/tmp/research-tree-codex-20261007-1XA9OP/evidence-archive/<case>-project.tar.gz`；排除.venv/.git/node_modules等可重建内容。代码历史另外保存并`git bundle verify`为`<case>-code.bundle`。实际native会话的MCP请求/回执及模型/权限上下文保存为`<case>-native-mcp.jsonl`。未归档auth.json或home凭据。

逐项SHA256、字节数、原路径、时间、原生回执数及清理结果在`evidence-archive/cleanup-receipts.json`。原文记录中的临时项目路径现为历史定位，复核应使用上述归档和scratch内既有独立JSON快照；不要把已删除路径视作仍在运行。M2/M4/M5收尾与M7r3/M8尚需运行的实例仅在本阶段结束后清理。终审未完成，不将清理等同于整个测试目标完成。

15:09追加M5：Codex正常退出，独立最终页面297/297false、无live/12秒后归档并移除项目与home。15:20追加M2：Codex正常退出，仅关闭自建收尾pane w3:pM，独立367/367false、无live/14秒后归档并移除项目与home。至此清理15个旧实例；尚需实测的M4/M7r3/M8继续保留。归档内实际Claude review原文件已额外抽取到各`<case>-review-raw`目录，便于只读终审直接读取；SHA清单`review-raw-extraction.json`。

已额外清理27个结束的安装/后台会话/环境探针夹具，先保留结果JSON与project证据为`evidence-archive/*-transport.tar.gz`，排除隔离home、auth.json和调试log；过程清单`transport-cleanup-receipts.json`。benchmark组合CLI的已完成4CPU/生成与评分夹具亦已归档后移除，真实结果入口`benchmark-cli-smoke.json`保留，另见`benchmark-cleanup-receipt.json`。不会删除仍在运行的M4/M7r3/M8。

15:50 UTC 按用户要求收尾 M7r3：正常退出 Codex，无活跃 worker；页面210/210false。先保留失败报告、原 MCP、Git bundle 和项目归档，再删除 M7r3 项目及隔离 home。旧 pK 仅因马上用于新 M7r4 而复用。累计已清理16个完成/被替代的真实实例；最新 SHA 和删除回执见 evidence-archive/cleanup-receipts.json。


16:15 UTC：旧M8完成有限失败审计后正常退出Codex并关闭自建pN，原项目/home归档后删除，cleanup receipt追加为第17个真实实例。仅预先声明静态baseline代码与root-only driver复制到全新M8r2继续修复验证，旧DB/run/evaluation不复用；可读失败报告和原始review JSON保留于scratch/evidence-archive/M8-audit及M8-review-raw，独立页面244/244 false和9实际秒见M8-failed-independent-closeout.json。


16:31 UTC：M4最后实际未登录probe/有限终审读取已完成，普通UI CLI也已/quit；正常退出Codex并关闭自建pJ。检查无live worker/open reservation、独立page609/609，归档源project/code.bundle/native MCP及选定可读原始run、实际review JSON/current报告后删除project/home。cleanup receipt现18个真实实例，剩余M7r4/M8r2仅为立即继续的未完测试。


16:34 UTC：旧M7r4有限审计/no live/openRS/page197完成，正常退出并关闭自建pK，静态root代码和driver在删除前复制至新M7r5继续受影响回归；旧项目/home删除，关键原始native gate/上下文与最终报告可读保留、code.bundle验证。cleanup receipt现19个真实实例；目前仅M8r2与新M7r5为仍需使用的测试项目。

16:43 UTC：最新native-final12原生安装检查已完成，app-server退出且无进程使用fixture目录；去除home/凭据/可重建依赖后归档并删除。transport archive SHA256 `9c428205606de2551d6e923feb3b7c3ad0556831ef22c87b4e760998df12bbaa`，回执见 `evidence-archive/transport-cleanup-receipts.json`。当前不再保留已结束的安装测试项目。
17:05 UTC：M7r5 受影响原文/合法记忆/context 回归完成，最终页面151/151false、无live/openRS、root七次CPU/全部settled。正常退出Codex并关闭自建pQ；保留可读原生回执、context原始输出、文档与原始runs后归档删除项目/home。第20个真实实例清理回执见cleanup-receipts.json；项目tar SHA256 `c20d5bb9fcad43c363d2ed5e091180dbede1f8d9777db8ee9ad91e55f0b595d0`。后续继续使用的项目只有M8r2及为新去重缺陷创建的全新零CPU Dedup回归。


17:19 UTC：全新零CPU Dedup原生幂等回归完成，page41/41false、无run/live/RS，正常/exit并关闭自建pR。归档保留原始MCP与转抄错误历史、当前报告/状态、Git bundle后删除project/home。现累计21个完成或被替代的真实实例；仅M8r2仍需继续。SHA与实际清理时间见cleanup-receipts.json。


17:55:25 UTC：最后M8r2完成原生门和独立审计、page506/506false后正常/exit并关闭自建pP。归档源project/1507 native回执/code.bundle（verify通过）后删除project和隔离home；两份已结束的未登录Claude测试profile也删除。累计22个真实实例已清理，scratch中rt-test-*和codex-home-*目录均不存在，Herdr仅调用者p1继续工作；没有关闭用户pane。项目归档SHA256 2a1048b1410bcb0087c843ecd6897439df2f1f8d3ce5c009247cdae2ebad469e。为终审保留22份归档的3296个可读证据文件，不含凭据、.venv/.git或可重建依赖；这些是复核产物，不是继续运行的临时项目。清理动作不代替待完成终审。

18:26:42 UTC：R6发现停滞重复计数后创建的全新Stall原生回归已通过独立核验，page40/40false、零CPU/无live。正常/exit，agent list确认测试Codex已退出后关闭自建pS。去凭据归档、Git bundle verify后删除Stall项目和隔离home；cleanup-receipts追加第23项，project tar SHA`d718134b915a3d0f8c84ef78878f68dc278a7688ec3c093bca9ee9d75391aafd`。保留72个canonical工具事件、62条归档会话上下文/自定义回执、48个可读项目文件和独立audit；合计23案例3344个可读项目文件。当前scratch无rt-test-*或codex-home-*目录，Herdr没有测试agent，仅用户调用者p1保留。R7终审仍须完成。

19:06:39 UTC：最新Full access原生安装transport已通过并退出app-server；确认无进程使用fixture目录后，排除home/凭据/依赖/调试log归档，删除`native-install-r10-full`项目及home。archive SHA256 `15170ceaef5bddbb851882d379960afe78377cdfa26080c9aa9ec91978a5ee6a`，thread `01a117bf-7330-77f1-894e-266bb8a5e737`，回执追加于`evidence-archive/transport-cleanup-receipts.json`。此项只有原生传输，不增加23个真实模型案例计数；不保留已结束的测试项目。

19:25:08 UTC：M6缺少的逐批R19由全新零训练原生M6R19补齐，实际拒绝/零费用/page11独立核验后正常/exit，确认agent退出再关闭自建pT。项目、隔离home及空Claude profile均删除，Git bundle verify通过；project tar SHA256`c3c63f60c193cb74e96c6f7fc623051fd664c04c0db1b527551bf353189520e7`。第24份真实实例清理回执已追加；保留26个canonical MCP事件、40条选定会话回执、36个可读项目文件及独立核验。累计24案例3380个可读文件，31份transport回执；当前无运行测试项目或test agent，用户pane保持。

20:06:20 UTC：R11确认请求修复后的最新版原生安装transport通过，thread01a117f7-b3f0-7122-b715-a719045c0eb8。app-server退出且无目录使用进程后，排除home/凭据/依赖归档，删除native-install-r12-full项目及home；SHA256`8ec8ddf3adf100720b429dcd2a4971758c7a16d3293f789396c86cdd7f795db6`。transport回执现32项；真实模型实例仍24项且全部已清理。所保留归档及M4历史损坏/恢复字节用于后续复核，不是运行中的项目。


2026-10-07T21:19:27.322270+00:00：E2E单项目完整链及独立审计完成，正常/exit后agent list仅调用者p1，关闭仅自建pV。进程目录检查、Git bundle verify和去凭据归档通过后删除E2E项目/home；第25项project tar SHA256 `9d82485488daf34f6ca30e3e37c4cc75b6bc58170abf967619e327fbadd9cb96`。保留405 canonical MCP事件、867选定会话回执、269可读文件和34控制器审计文件；合计25案例3649可读文件、32 transport回执，scratch无rt-test-*或codex-home-*。这些复核归档不作为继续运行的项目。


2026-10-07 21:49 UTC：最新 sessions fixture 已完成并删除，第 33 个 transport 回执（worker Full access/never，UI 只读）；25 个真实 Codex 实例仍全部退出和清理。跨端 Claude 回归另计：R14 在实际 Pi 费用漏计缺陷后停止，已 /exit、关闭 w3:pW、保存 native/代码 bundle/tar/可读证据，删除临时项目；新 R15 正在后续必要回归，故暂时保留。Claude 回执另存 `evidence-archive/claude-cleanup-receipts.json`，不混作新的 Codex 实例。


2026-10-07 22:15:42 UTC：ReviewPrompt 格式回归完成，实际 REVISE/schema 登记与零 CPU、页面 12/12/false 独立核验。正常 /exit、确认 agent 消失后关闭自建 pZ，去凭据归档及 Git bundle verify 后删除 project/home；第 26 个真实 Codex 实例，tar SHA256 `520c5540f72ba85f5d52dadf736693ea57b0f2d7e5e0704fccaf7418000993a0`。readable-extraction.json 共 26 案例、3688 个可读文件，transport 仍 33 项。Claude R15 已停止并于 22:06:26 清理；R14 专属 native cache 也已校验归档副本后删除。只有仍用于必要共同流程回归的 Claude R16 项目暂留。


2026-10-07 22:30:54 UTC：最后 Claude R16 共同流程及独立核验完成（7 CPU、task accepted、21 current SHA、page131/131/false）。正常 /exit 后 agent list 仅调用者 p1；关闭自建 pY，native 副本 SHA 核对、Git bundle verify 后归档并删除项目及专属 cache。tar SHA256 `c2139a36f1f642bb1fa525b8b92a96ec2a27b18bba3b2d003727e555c2e0bd8a`。现 26 个真实 Codex 案例、33 个 transport、3 个 Claude 原生重测案例均已退出并清理；scratch 无 rt-test-* 或 codex-home-* 目录，没有测试 agent。归档只用于复核，不含登录凭据或可重建依赖。最终 Fable 审查尚待完成，完整科研 benchmark 仍 OPEN。


R17 最终构建的两个纯传输夹具已分别于22:46:59 / 22:53:45 UTC退出进程、去凭据归档并删除项目/home。install线程01a11889-8952-7ac3-ab15-90f4ae776670，archive SHA e6e09921e50ae7d27af9455b5c0c1e378e9d72fe417e4a305a8a454f3650d50c；sessions同一worker/resume线程01a11890-c573-7191-96bf-9e587e429a8c，另UI线程01a11890-cafa-7a22-beea-6b17639fd527，archive SHA faf4c0f450392d74362efb3481f8a99106201b41ed613de7566b9d81b1a6dfb2。两个worker上下文均Full access/never，UI按角色read-only/never；transport ledger现35项，不增加付费模型案例。

23:20:27 UTC：ClaudeE2ER17完整单项目链完成、11实际CPU/30 current SHA/page208独立核验后，正常/exit并观察shell提示，仅关闭自建p0。原始native副本逐字SHA一致，git bundle verify通过，排除凭据/依赖后归档，删除临时项目和专属全局native cache。tar SHA edbeb54ef8bcbde1e8c3307bab55a27a6bd464f58cf6832c817c88adbfcf2452；Claude ledger现4项。真实复核uncertain与原始调用错误/JSON补正均保留；工程链通过不宣称科学收益。仅Codex E2ER17尚需完成，故保留其项目/home及自建p11。


23:30:38 UTC：Codex E2ER17完整链已NOT GO结项、11实际CPU/41 current SHA/page257独立审计通过。worker全completed、无open RS，控制器Esc停止结项后的额外通知读取，再正常/exit观察shell提示，仅关闭自建p11；git bundle verify后归档删除项目和隔离home。tar SHA f783e6361d9c5b8b3a58a24eec93e398d5213473bb36817c6982d5b3d9e43b41；archive native849条回执、470 canonical事件、65自定义工具对、257可读文件保留。Codex ledger现27项/3945可读文件，Claude独立ledger4项、transport35项；scratch无rt-test-*或codex-home-*目录，Herdr没有测试agent，只保留调用者。Fable最终审查尚待执行，完整科研benchmark仍OPEN，清理不改变整体完成标准。


R15终审结束后另将八份历史诊断DB与误写到scratch/research的旧brief逐字SHA保存到evidence-archive/remaining-diagnostic-artifacts，再移除原临时目录；原路径映射与SHA见该目录cleanup-proof.json。空E2E-original-candidate-briefs与可重建__pycache__也移除。没有丢弃科学或故障证据，没有剩余测试项目/home/测试agent；证据归档供后续复核，不是运行项目。
