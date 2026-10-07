# Codex 补测基础设施验证

日期：2026-10-07。scratch：`/tmp/research-tree-codex-20261007-1XA9OP`。这些检查验证构建、确定性规则及原生 CLI transport；真实模型的 M0–M8 另记，尚未完成。

## 修复与失败调查

1. `check_codex_install.py` 原断言五个工具，原生 app-server 实际返回六个。改为独立核对完整名称集合，包含 `research_review`。
2. 两个检查使用的临时输入曾启用未完成的 discovery，后续又触发 protocol/config 与 metric spec 不一致。修改 fixture 为明确的 version 2 / discovery off，并从配置生成匹配协议与指标；生产确认门不变。
3. 后台会话检查的 provider 收到请求时，thread_id 可能尚未落盘。仅在 fixture 持续挂起期间有界等待 thread_id，再测试活跃 follow-up；不重试生产 worker。
4. 新原生项目在 SessionStart 之后 init，主模型观察原只在 SessionStart 写入，导致跨族评审取不到宿主模型。新增 adapter 回归测试先失败（None 与 gpt-6-luna 不相等），再修复 PostToolUse 使用实际 event.model；按 agent/actor 去重，实际换模型仍追加观察。
5. 主会话 MCP timeout 900 秒、后台 1800 秒短于 review runtime 的 3900 秒等待。统一传输等待为 3900 秒并同步 README。
6. 测试计划声明 final_loss/train_time，而生成配置只有 accuracy。计划与配置统一，额外指标保留为诊断，不加入 gate。
7. 真实 M0r2 根 worker 的完成通知无法找到主会话 rollout，worker 也没有 observed 模型。检查原生 MCP 进程 `/proc/1692881/environ` 的指定字段，发现 CODEX_HOME 缺失。插件 manifest 增加该环境传递，让后台 CLI、hooks、resume 和 queue 使用主会话的隔离配置目录。实际新 worker 与通知仍待重测。
8. 用户要求临时 Codex 项目 Full access；此前后台 worker 强制 workspace-write，在创建 Git 分支时被拒。适配层现在只在用户的原生 CODEX_HOME/config.toml 明确设置 danger-full-access 时继承该选择；默认 workspace-write、UI read-only。仅在两个新隔离配置目录写入 Full access；日常配置未被此设置改写。边界回归测试通过。
9. worker 试图以 notice/blocker 发送阻塞消息，而接口只能接收共享消息 schema 的类型。公开 tool schema 增加类型枚举和 200 字限制，运行时提供可操作的非法类型错误；worker 提示明确以 alert 报告阻塞。没有放行非法类型或 worker 的 post_to_ui。

原始各轮临时证据目录保留；失败没有记为通过。未创建假 observed 模型记录。

10. 原生无模型 turn 的 app-server 检查进一步证明：后台显式 `mcp_servers.research_tree` 配置同样必须传递 CODEX_HOME，不能只修改插件 manifest。补齐相同的三项环境 allowlist 后，`mcp-env-probe-r2.json` 记录真实 MCP PID 1730732，CODEX_HOME 为隔离 probe 目录、actor 为 worker/root；原生 thread 返回 dangerFullAccess，实际只读 status 调用成功。最初只检查 launcher 的直接子进程漏掉被原生 launcher 重挂的 MCP，后来按隔离目录及脚本 argv 精确定位；这是探针问题，没有据此修改产品或伪造模型观察。
11. M6 仅方向会话完成 D0/D1 后，在 D2 验证缺少设计要求的正式只读 lens 入口。新增 `research_control lens`，仅允许 full 模式、planning 阶段与已配置 lens；稳定助手身份、独占运行锁、只读 CLI 沙箱和 MCP allowlist，不绑定科学节点。主会话读取实际助手结果后才登记分片；移除提示词中的 RLD 串行生成替代。两项边界回归覆盖重复启动、写库/登记文档/评审/控制/消息拒绝和确认后的拒绝。

上述最新修复构建 Claude 61 / Codex 69 files；adapter **21 tests OK（8.430s）**。新原生 M0r4 与 M6r2 已安装该构建，主会话和隔离配置均 Full access，prepare 已提交。UI 与 lens 维持其只读角色契约。实际根 worker 成功与完整发现流程仍待验证。

12. M6r2 的真实 Claude Code triage 在模型调用前拒绝 `$schema: https://json-schema.org/draft/2020-12/schema`，费用 0，无 review 登记。共有七个评审 schema，其中多个还有嵌套方言标记。只在 Claude CLI 传输参数中移除方言注解；原 schema 及本地严格结果校验保留。原生错误加入 stand-in CLI，回归先复现相同失败，修复后 review_call 35 项通过；最新补充断言的两项继承回归也通过，验证原 schema 不被修改、CLI schema 语法兼容、空对象/越界评分/无来源引用仍不合格。新 M6r3 必须用真实 CLI 重测。

最新构建仍为 Claude 61 / Codex 69 files；adapter **21 tests OK（8.403s）**；两个 Claude validate 均通过。此前该轮共享 **293 tests OK（263.501s）**，打包 **10 tests OK（4.015s）**，原生 final-4 安装与后台会话检查均通过：install thread `01a1159b-65db-7642-ad3f-25ecb12dfef7`；worker/resume `01a1159b-6925-75a2-8be9-0e16970d6816`，UI `01a1159b-6f44-7ea0-a073-568f5391787b`，三个本地 Responses 请求和活跃 follow-up queued。final-4 在 Schema 兼容修复之前，不能替代它的真实评审检查。

## 实际验证

| 命令 | 结果 | 范围/证据 |
|---|---|---|
| `.venv/bin/python -m unittest discover -s shared/research-tree/tests` | 293 tests，OK，263.553s | 共享核心；执行在适配层修复前，共享代码未改 |
| `.venv/bin/python -m unittest discover -s tests` | 10 tests，OK，3.730s | 最终构建后打包检查 |
| `python3 scripts/build_plugins.py --target all` | exit 0；Claude 61 files，Codex 69 files | 最新 timeout 与 hook 修复均进入 dist |
| `.venv/bin/python -m unittest discover -s dist/codex/plugins/research-tree/tests -p test_codex_adapter.py` | 17 tests，OK，6.958s | 最新构建，包含首次 init 模型观察回归 |
| `.venv/bin/python scripts/check_codex_install.py dist/codex --evidence /tmp/research-tree-codex-20261007-1XA9OP/install-check-final-1` | ok=true；6 tools | 原生 app-server；thread `01a1156c-3478-71e2-9dcd-bbaae5289078`；init → documents → project → confirmation → progress page |
| `.venv/bin/python scripts/check_codex_sessions.py dist/codex/plugins/research-tree --evidence /tmp/research-tree-codex-20261007-1XA9OP/session-check-final-1` | ok=true；local_responses=3；live_followup=queued；task_status=open | 真 Codex CLI + 本地 Responses fixture；worker/resume 同线程 `01a1156c-43e8-73c1-b238-5cae4d44df42`，UI `01a1156c-4b00-7a70-85eb-1a03544a6d44`；不证明真实模型判断或 Leader 通知 |
| `git diff --check` | exit 0 | 本轮修改 |

上述 final-1 记录保留。后续 deadline 修复版实际通过 18 项 adapter（7.655s）、10 项打包（3.586s）、16 项 research_tree/prepare/config（17.232s）；final-2 原生安装与会话检查也通过。

当前 worker/隔离修复构建：`python3 scripts/build_plugins.py --target all` exit 0，Claude 61 / Codex 69 files；adapter **19 tests OK（7.839s）**。当前原生检查：

- `check_codex_install.py dist/codex --evidence <scratch>/install-check-final-3`：ok=true，6 tools，thread `01a11582-db05-7ae2-9734-8c7d252e92c5`，完整 transport 工作流通过。
- `check_codex_sessions.py dist/codex/plugins/research-tree --evidence <scratch>/session-check-final-3`：ok=true；worker/resume 同线程 `01a11582-e907-73d2-981c-eac82503d5b8`；UI `01a11582-effe-7d81-983a-4feae49b2064`；3 个本地 Responses 调用，活跃 follow-up queued，task 仍 open。

一次 deadline 新测试先因未创建 fixture 的 .venv 而报错，修正测试设置后才复现真正的 3900=3900 失败。另两次测试过早读取仍在构建中的 dist，分别运行 0 项和导入失败，并导致一次构建临时目录清理报 Directory not empty；按构建完成后再执行的顺序重跑通过。这些执行顺序错误没有作为产品回归，也未放松断言。

## Claude 独立最终测试

Herdr 自建 pane `w3:pG`，agent `rt-claude-validation-r2`。原生启动参数为 `--model claude-sonnet-5-5 --effort high --permission-mode auto`；父会话观察的 CLI banner 为 Sonnet 5.5 with high effort。子会话只能自行核实模型，无法将其 reasoning_effort 数字映射为 high；这里以原生启动参数与 banner 核实 effort。

实际四条命令均 exit 0：`python3 scripts/build_plugins.py --target claude`、`claude plugin validate dist/claude`、`claude plugin validate dist/claude/plugins/research-tree`、`claude plugin test dist/claude/plugins/research-tree`。插件测试 **22 pass / 0 fail**。完整子会话报告：`/tmp/research-tree-codex-20261007-1XA9OP/claude-validation-r2.md`。

初次委派错误使用 safe-mode，插件 hook 被该模式禁用，未构成产品失败；正常模式的新会话重跑通过。本委派仅覆盖 claude-mod，未做新的 Claude 科研项目端到端测试。

## 独立评审

Fable 第一至三轮均 `claude-fable-5-1` high，is_error=false、terminal_reason=completed、modelUsage 仅请求模型；无 CRITICAL/MAJOR。原文与 MINOR 处理见 `../reviews/codex-real-infrastructure-r1.md`、`r2.md`、`r3.md`（同一文件名前缀）。Claude Code 基座名义费用分别 3.6318012500000005、3.85856675、4.1743375 USD，累计 11.664705500000001 USD。真实 worker 新修复不在第三轮 brief 范围内，仍需终审。

第四轮有效，5.5646955 USD，累计 17.229401 USD；0 CRITICAL / 2 MAJOR / 5 MINOR。包括共享规则错误声称 Claude lens 全部只读、以及 M0/M6 尚未实测完成。已准确区分 Claude 指定分片写入与 Codex 只读返回，同步其余 MINOR；批次仍进行中，不将完成缺口标作已解决。原文及处理见 `../reviews/codex-real-infrastructure-r4.md`。随后新发现的 Schema 兼容修复仍待独立审查。

## Schema 修复后的完整验证（final-5）

最新共享 **295 tests OK（263.852s）**、打包 **10 tests OK（3.978s）**，均在构建完成后执行；最新 adapter **21 tests OK（8.403s）**。原生 final-5 检查通过：install thread `01a115b3-a7c2-7291-b9ec-4d23edf738af`，六工具与完整初始化/确认/进度页面；worker/resume 同线程 `01a115b3-aab2-74d3-8030-404ef7df2687`，UI `01a115b3-b90c-7c73-8897-816063464629`，3 个本地 Responses 调用及活跃 follow-up queued。其范围仍为原生 transport 与确定性 fixture，真实跨族 review 由新 M6r3 单独验证。

13. M0r4 worker 的实际 SessionStart 收到了 RLD 的 inbox/post_to_ui/调度指令，恢复时重复调用 inbox 被固定角色门拒绝。hook 按固定 actor 注入 worker 或只读 UI/lens 上下文，RLD 保留原工作流；技能和worker提示同步限定控制操作。回归先在构建包中复现缺失 worker 身份、误注入 RLD 指令，再修复。最新构建61/69，adapter **21 tests OK（8.365s）**、打包 **10 tests OK（3.453s）**，diff check和CodeGraph sync通过；共享代码未再改，不重复已通过295项。源码目录最初无法单独加载共享依赖/模板，两个设置错误未计为产品回归；在正式dist复现后才修复。新 M1会话使用全新隔离安装重测实际worker角色。

14. 真实独立 UI（M1r2）首次误把 research/<id> 材料根目录作为 MCP 的 project，被固定项目门正确拒绝。worker/UI/lens 提示统一要求省略 project；材料根目录与工作项目不同，未放松运行时绑定。旧提示下测试用户要求省略该参数后，原生 UI 成功刷新 data_version 17；两线程均 observed gpt-6-luna、native read-only、actions=[]，没有确认或启动研究。证据 `<scratch>/M1r2-real-ui-evidence.json`。最新提示默认行为仍须全新安装 UI 重测。

15. M1r2 的真实规划 shell 最后 `cp research-tree.yaml .../config.v1.yaml` 仅读取用户配置，却被 hook 按写入源文件拒绝。新增回归在正式 dist 复现六种允许读取的误拒；修复只检查 cp 的真实目标（包括目录下文件名、多个源、-t/--target-directory/-T），保留配置/生效文档/框架目标保护。换行也恢复命令边界，后续 rm 不能被 copy 处理吞掉。构建 61/69 files exit 0 后，adapter **22 tests OK（8.479s）**、打包 **10 tests OK（3.657s）**、diff check/CodeGraph sync通过。一次测试误在构建仍运行时读取 dist 导入失败，没有算作产品回归；确认构建完成后的回归才复现和验证。全新 M0r5 使用 remove/add 原生插件安装，不修改活跃缓存。M1r2 保留旧安装与误拒原文，不将旧目录继续运行作为修复后重测。

## 第五轮评审后的契约修复

Fable r5 有效（0 CRITICAL / 3 MAJOR / 2 MINOR，6.156965500000001 USD，累计23.3863665 USD），保留原文与处理记录。两处新增MAJOR已实施：Claude lens移除Write、返回JSON由Leader存分片，并在spawn检查planning/full/已配置lens/模型；共享init按配置所选provider做认证预检，结果持久化marker并交两端规划提示，失败不阻止planning、不调用模型或生成review。认证预检不能提前发现原Schema方言失败，当时认证可用，两个问题分别验证。

init回归先复现六个缺失字段失败，再通过两项继承测试（1.120s），分别覆盖Claude可用/未登录、pi候选复核启用且discovery off，确认只选相应基座、不调用模型、无review且未登录仍保持planning。完整共享 **297 tests OK（299.638s）**；最新构建61/69 exit0，Codex adapter **22 OK（8.761s）**、打包 **10 OK（4.459s）**、Claude两项validate通过、原生插件测试 **24 pass/0 fail**，新增lens门和注册只读工具断言。

修复前安装的原生final-6传输检查也实际通过：install thread `01a115e6-2e99-7692-9870-cb2c8ed53f1e`、六工具与init/确认/page；worker/resume同线程 `01a115e6-3399-7cb0-aa5d-57ec520dd1f2`、UI `01a115e6-3b48-7591-8038-1e8277edea03`、三个本地Responses请求和活跃followup queued。该传输检查不证明实际科学模型或新增init预检；后者仍需最新构建新原生项目验证。README记录review alert与CLI最小预算的准确软阈值语义；Codex提示明确同名seed lens逐个执行。diff check与CodeGraph sync通过。

## 独立 UI 原生错误与提示修复（11:48 UTC）

真实M0/M2 UI暴露三项提示错误：草稿使用未定义authorization/open_questions键、about引用尚未成为DB实体的REQ、明确confirm被SessionStart笼统“UI不确认计划”否决。修复fields schema明确七string键/additionalProperties=false和open承载未决授权，REQ只作为草稿/提交ID；澄清向用户reply，不擅自转交RLD；固定UI只读仍有效，而显式用户确认通过actions.confirm交由控制器持久化/通知。未放松DB/project/角色权限。M2原生新草稿、澄清、v1提交通过；旧缓存修订/confirm经过技术澄清成功，不能用它们宣称新默认提示通过。新增M4全新安装承载默认重测。

MCP project metadata与initialize instructions按固定actor区分：main需绝对workspace，managed child省略project；误传仍拒绝并给出省略提示。草稿失败引用的回归同时证明原文/fields保留、动作failed、phase不变、不重复通知。最新构建61/69 exit0，adapter **23 OK（9.117s）**、打包 **10 OK（5.749s）**，CodeGraph sync通过；共享及Claude代码未再变，已通过297项共享/24项Claude保持原验证范围。

修复最后metadata/UIhook前原生final-7 transport通过并明确保留证据：native-install-final7/thread01a1160b-e959-7d32-8633-ea0f5612a3d7、六工具与init/confirm/page；native-sessions-final7/worker-resume01a1160b-009a-7cf3-bbdd-3a89f960c541、UI01a1160b-0692-7ae1-9798-6b59fb62ceed、三本地Responses与活跃follow-up queued/task open。不以transport替代真实模型或最新默认UI行为。

最后metadata/UIhook构建的原生final-8 transport检查均通过，证据显式保留：native-install-final8/thread01a11633-2344-7f80-93ce-814c09b25b91，六工具完整工作流；native-sessions-final8/worker-resume01a11633-2b89-7bc0-b65a-8f9eff8625e1、UI01a11633-3a26-7243-9d63-b07dbc5c807a、三本地Responses、live_followup queued/task open。该fixture范围仍不等同真实模型默认UI确认/科研验证。

## MCP 评审配置目录传递与新安装回归（12:47 UTC）

M7 初次原生会话的父进程使用空的临时 `CLAUDE_CONFIG_DIR`，实际 `claude auth status` 为未登录；插件 MCP 的环境白名单却遗漏该变量，init 从默认登录目录得到 `ok=true`。读取实际 MCP 进程的指定目录环境字段后确认原因，不把父 CLI 的状态当作插件状态。源 manifest 和后台显式 MCP 配置均增加可选 `CLAUDE_CONFIG_DIR`、`PI_CODING_AGENT_DIR` 环境传递；未设置时仍使用各 CLI 默认目录，未以空字符串覆盖正常认证。

重建成功（Claude 61 / Codex 69 files）后，新项目 M7r2、新隔离 home、新原生安装和四 hooks 信任完成。主线程 `01a11666-a321-7853-aa85-8f12eda07f34` 的实际 MCP PID 2163452 使用指定临时 Claude 目录；12:47:18 init 记录 `backend=claude_code`、Sonnet 5.5、`ok=false`、`REVIEW_UNAVAILABLE: claude is not logged in`，项目仍为 planning、无 review。证据 `<scratch>/M7r2-native-profile-precheck.json`。初次 M7 的错误记录保留，没有计作修复后通过。

最新构建后 adapter **23 tests OK（8.970s）**、打包 **10 tests OK（5.678s）**；CodeGraph sync 通过。生成器 v1（无 reviewer）与 v2（有 reviewer）的文本经项目 `.venv` 的正式配置解析器均通过，并含统一 runner 指引。验证脚本曾传入已解析 dict、使用系统旧 jsonschema、将 v2 reviewer 字段加到 v1；这些调用错误分别修正，未据此修改产品门。

M5 全新原生规划在未收到协议技术纠正时，已正确写出每 run 的 `required_counts=1200/400/30/1140`、真实顶层 match 和配对键。M4 最新默认 UI 五种操作（草稿、澄清、v1 提交、v2 修订、普通自然语言确认）全部通过，独立只读模型与动作账本见 `M4-native-ui-proof.json`；M4 根七次真实运行已验收，synthetic 指标的解释限制保留。

该构建的原生 final9 检查均通过：安装线程 `01a11674-eb48-7ee0-8ab0-75477d31d017`、六工具、init/documents/project/confirm/page；后台 worker 与 resume 同线程 `01a11674-f575-7e31-949e-9b28bbedaf89`，UI `01a11675-022f-7490-9a3c-0e9ee8089288`，本地 Responses 三次、活跃 follow-up queued、task open。证据 `native-install-final9` 与 `native-sessions-final9`；仍仅证明原生传输与确定性 fixture，不取代真实模型验收。

benchmark CLI 功能另行实测：`make_task.py` 产生 combination 场景与项目外 truth；四次真实 CPU sanity（无开关、两单臂、组合）成功，metrics 保留 knobs，组合预设收益与单臂噪声出现在实际输出。`score.py` 只读真实 M1 已结项数据库，成功返回 outcome/实际支出效率/attempt/费用等字段。首次评分项目路径拼错导致 FileNotFound，下一次将虚拟环境解释器符号链接解析为系统解释器导致依赖缺失；使用快照内实际 project 路径和未解链接的 `.venv/bin/python` 后通过。未重跑四次 CPU；失败与重试原文一并保留 `benchmark-cli-smoke.json`。这是工具功能检查，不是11 §2完整 A/B/C 工作流比较或科研效能证明。

## 实际manifest协议指导与M4历史核验（12:24 UTC）

M4默认规划再次把baseline_pairs/sanity_runs误写为required_counts、把说明性/别名字段写进match。生产导入始终按manifest顶层match和每run counts比较，未改门；Codex规划提示与共享规则现明确实际字段、每run计数、比较对数及sanity豁免的语义。测试项目生成器补明train仅训练，根worker实现runner后方法/sanity统一经runner输出并导入原manifest。最新构建61/69 exit0，adapter23 OK（8.762s）、打包10 OK（4.474s）；M5全新remove/add安装验证默认规划提示，尚待native计划完成。

M4模型曾用脚本覆盖历史v1字节，随后verify_document/直接写入保护拒绝继续覆盖。此shell保护是有界检测，不声称拦截任意Python间接写入。测试控制器根据实际成功native写入及登记前更正顺序重建三份历史文件，先逐一核对登记SHA256完全一致、备份损坏字节，再只恢复这些相同字节，未改数据库哈希。收据M4-history-restoration.json；原生RLD随后三次verify_document均true，旧版本保持superseded，协议修订用新v2。默认UI草稿、用户澄清、v1提交、v2修订已在四个真实只读UI线程通过；普通自然语言confirm重测仍待实际新版计划核验。

## 15:08 UTC 更新：记忆噪声修复与清理

M7r2原生发现lesson admission仅screen fix，symptom中的rate limit噪声进入current/context_pack。新回归先复现两处失败，再将同一过滤器逐字段用于symptom/root_cause/fix；全文威胁筛选保留。schema同步，最新memory13、共享298（299.495s）、adapter23（9.191s）、pack10（4.772s）、Claude插件24全部通过，Claude两层validate与git diff --check通过。新M7r3已使用最新构建/缓存启动原生重测，不能用单元通过替代它。

用户要求每项测试后退出测试Codex并清理不再使用的临时项目。已退出/被新项目取代的13个旧项目与对应隔离home（含凭据副本）已清理；关键project证据、Git bundle与原生MCP回执先归档并验证，完整清单/校验值见scratch/evidence-archive/cleanup-receipts.json及codex-cleanup.md。未完成项目仍保留，用户pane不由控制器关闭。

15:50 UTC：M7r3 原生文献 current 准入暴露 scanner 漏掉明确 credential disclosure。新增真实回归先复现2失败，再补窄模式；memory14、adapter23、pack10、Claude24、两层validate、构建61/69及diff check通过。完整共享299执行中；全新M7r4原生重测仍待完成，不把单元结果宣称为实际场景通过。旧M7r3已正常退出/归档/清理。

15:53 UTC：凭据披露修复后完整共享299项通过（304.010s），memory14、adapter23、pack10、Claude24及正式两层validate/构建61/69均通过。原生M7r4和当前M4/M8仍执行中。

15:54 UTC：最新final10原生CLI/app-server安装检查通过，六MCP工具全部发现，真实prepare/init/documents/confirm/build/check通过，thread01a11712-0a52-7250-97cb-dc31cf35c1f0。此无模型fixture只证明transport，不替代science/native模型测试。app-server已退出；保存evidence-archive/native-final10-install-transport.tar.gz与SHA回执后临时目录删除。

15:59 UTC：真实M4首次确认numbers调用带不适用code_ref，已在Claude Code实际付费RV9后才由register_review拒绝，raw cost $0.1112364仍计账。新增原生驱动的参数费用回归(真实DB、fake backend)对novelty/candidate两类，修改前两subcase均因真的调用backend而FAIL；共享review_call在任何backend/precheck/分配前拒绝不适用code_ref，未改变注册契约。修复后review_call39通过（38.540s），最新构建61/69；共享300执行中。需新临时native guard项目验证该前置零调用拒绝，不修改活跃M4缓存或抹去已花费用。


16:16 UTC：M4曾仅在旧测试安装缓存修复Claude prompt输送，遗漏共享源码；新M8因此真实复现两次 `--print` 无输入错误（stderr明确提示必须提供stdin或prompt），费用为零，不计code_review成功。CLI `--add-dir <directories...>` 为变长参数，会吞末尾prompt。现在共享`_run`支持显式stdin，Claude的初始/续审均通过stdin送prompt，Pi及认证预检保持DEVNULL。新增真实参数解析回归修改前FAIL，修改后评审41项通过（37.052s）；最新adapter23（9.092s）、pack10（4.307s）、Claude24、两层validate/61+69构建、diff check通过，完整共享301执行中。共享/构建/全新M8r2缓存review_call.py SHA256均为5302bef671b8ba1d8e21d8b7e34208ff77424830c76d3a74cecb7364f44d52be。

同时修复非code_review错误携带code_ref在实际付费后才失败的参数门：现在任何后端/费用发生前拒绝。回归先证明novelty及candidate_recheck两种调用确实会误调用后端，修复后两者数据库/费用不变。需由新M8r2的实际public MCP拒绝回执补齐native验证。M4旧RV9原始付费失败保留，费用实际已入账，无成本漏记缺陷。


16:22 UTC：最新stdin/参数门修复后共享303项全部通过（305.872s）；native-final11实际安装transport再次通过，6tools、init/documents/project/confirmation/page，thread01a11728-ec75-76b2-9fa6-33434775dbd1。transport不调用实际研究模型，不替代M8r2的真实评审；fixture完成后已归档并删除，原生M4/M7/M8r2继续执行。


16:37 UTC：新M7r4两条显式transient噪声补正：2FAIL前置回归证实current被接纳，再补窄模式。修复后memory15（10.289s）、adapter23（8.841s）、pack10（4.487s）、Claude24、两项validate与最新构建61/69全部通过，diff check/CodeGraph sync通过；共享304和native-final12安装检查仍执行中。M7r4其它成功与部分失败原文归档，新M7r5正在最新缓存中仅规划受影响回归；不声称已native通过。

16:41 UTC：最新完整共享 **304 tests OK（307.387s）**；native-final12 原生安装检查通过，六MCP工具及init/documents/project/confirm/progress，thread `01a1173a-369a-7013-aa96-4c5b967b27b1`。app-server已退出，fixture经无活跃进程检查、去凭据归档后删除；SHA/清理回执保存在 `evidence-archive/transport-cleanup-receipts.json`。M7r5的完整限定计划已独立阅读并明确确认，只授权原定7个真实root CPU run，记忆回归须等待根证据验收；M8r2两个真实方法worker已在各自工作树启动，实际review/负例/组合尚待验收。


17:12 UTC：M8正式seed扩展暴露create_experiment重叠seed去重缺陷，两个新回归修改前2FAIL、修复后CostEstimateTest6PASS。共享完整306项通过（304.144s），打包10项通过（4.555s），最新61/69构建与Claude源码/构建两层validate通过。shared/dist/Dedup安装cache research_db.py SHA256均a33a6a2907fcb5264a98aac2a3b6b77cc99e71192d1a8f5769cc7e860212974c。全新零CPU Dedup Herdr原生项目仍在运行，不能用以上确定性结果替代原生回归。M7r5受影响精确负例/合法上下文已完成并退出清理；M8combo等未完与独立终审仍保留。


17:19 UTC：新Dedup native regression已完成：实际McpToolCall返回E1/E1、显式extend至3后旧请求仍E1，request walltime90独立E2，原生get保持1→3且不隐式扩展/收缩。零训练/run/reservation/review/evaluation，page41/41false，main observed gpt-6-luna/Full Access，源码/dist/cache a33a6a...一致。首轮转抄SHA输入错误正确拒绝且原报告保留，纠正后真实五步通过。已/exit、关闭自建pR、删除project/home；证据evidence-archive/Dedup-audit。当前唯一仍需原生测试项目M8r2；其两negative EV通过，combo sanity已有实际16th run/独立scope audit，正式组合及其他门仍未完成。


17:55 UTC最终原生收尾：新M8r2的19 actual run及零CPU U08/R04/R19 gate、73 current文档SHA、original bytes和page506独立核验通过；M7r5和Dedup已通过并清理；当前全部22实例已退出/移除，证据可读保留。review-fee-ledger.json按每个项目tar中的唯一原始cache review及5轮stage review统计：33 native raw记录，已报告Sonnet5.5费用3.7793676 USD，Fable5.1五轮23.3863665 USD。5份空/不完整JSON历史CLI失败原件没有推断raw费用，失败回执和插件账务原文保留；统计不含Codex调用或未提供的账单。14规定Fable R6独立終审待完成。

## R6 后续修复与范围纠正（18:23 UTC）

R6 严格有效（is_error=false、terminal_reason=completed、modelUsage 仅 claude-fable-5-1），0 CRITICAL / 2 MAJOR / 4 MINOR，原始费用 11.34867 USD，原文见 reviews/codex-real-infrastructure-r6.md。它指出旧 M8r2 停滞测试四次使用同一 D69，不能证明按批次计数；该通过声明撤销，原始实际 child 拒绝和调用历史继续保留。

Claude research_db 移除 actor 参数并在项目加载前拒绝模型提供 actor，始终采用会话绑定角色。新增真实注册处理器回归曾在修复前失败，修复后源码与构建包各 25 项通过。note_findings 要求 current、字节未变的 decision 文档，重复同节点/文档返回当前状态，不能重复升级或用旧文档复位；新增重复和无效文档回归、更新 T01/T02 的不同文档输入及所有调用方/设计/API说明。StallTest 3 项通过；完整共享 **308 项通过（307.306s）**，adapter **23 项通过（8.977s）**，pack **10 项通过（4.356s）**。两层 Claude validate 与61/69构建已通过；CodeGraph sync、git diff --check 通过。新原生 Stall 正在最新源码/dist/cache 一致的安装中验证五批次、重复请求、旧批次不能复位及空 doc 拒绝，无 CPU/付费 review。

三个提示遗漏已修正：brief 示例含 docs/ 并明确相对研究根；技能映射 `$research-tree ui` 到 ui_path；control 动作列表加入 help/pane。12 §1 的完整 M8 科研 benchmark 标准仍未完成、未获豁免；本轮原始任务仅补齐 Codex 功能测试，不据此宣称 A/B/C 科研效能结论。后续任务、种子及预算提案见 test-logs/abc-benchmark-proposal.md。独立 R7 终审尚未运行。


18:26 UTC：Stall原生回归已独立通过并正常退出/关闭自建pS/删除project及home，累计23案例全部清理。五个current批次及三种重复行为、空doc拒绝精确吻合五行账本，13 current SHA与page40/40false通过；实际零CPU/无paid reviewer。canonical72事件、controller-closeout与可读证据保留。R6后累计已报告Fable费用34.7350365 USD（原始Decimal总值保留ledger），Sonnet3.7793676 USD；未提供的账单不推断。R7终审待执行。

## R7角色门修复（18:39 UTC）

R7严格有效，0CRITICAL/3MAJOR/2MINOR，原始费用11.382382 USD。其中完整科研benchmark继续开放，不作为代码缺陷伪修复。Claude的post_to_ui原处理器允许子代理冒用Leader，research_db对未绑定子代理回退cfg.actor；两项真实注册处理器回归修复前FAIL（最初测试接口构造错误另保留，不计产品复现）。现所有子代理post_to_ui提前拒绝，未绑定research_db拒绝，无外部process/UI/阶段副作用；已绑定worker和主会话read的实际argv身份保持正确。Claude WORKFLOW同步note_findings新doc_id契约；Codex测试加强两处MCP环境转发集合一致与三个关键变量断言。

源码最终27项PASS（0.48s）、构建包27项PASS（0.49s）、adapter23项PASS（8.821s）、pack10项PASS（4.516s）；两层validate、最新61/69构建、CodeGraph sync与diff check通过。共享核心未变，完整308项原通过结果仍适用；Codex生产适配器未变，23案例的原生证据/清理维持，无新临时运行项目。R8独立审查待执行，12 §1整体M8科研benchmark标准不报告完成。

18:50 UTC：R8严格有效，0CRITICAL/2MAJOR/2MINOR，原始费用9.37660225 USD。Claude UI shell豁免与post长度问题的新注册处理器回归修复前两项FAIL，现UI专用角色门拒绝写DB/切阶段/其他actor/评审，保留query/ui/requirement与ui/ui只读方法；六拒绝/五允许通过，拒绝未执行next。post/review schema拒绝额外属性，post处理器按Unicode码点检查1..200，新增空/超长/非字符串与200emoji边界通过。brief根内API契约保持，技能明确新brief放docs/reviews/briefs并用实际含docs/参数，历史M8r2根内未注册brief位置照实保留。

源码29 PASS（0.50s）、构建29 PASS（0.48s）、pack10 PASS（5.695s）、两层validate、61/69构建、diff check及CodeGraph sync通过。共享/Codex生产核心未变，308/23及原生23案例的验证范围保留，无新增运行项目。完整benchmark开放项不以代码修复替代；R9独立审查待执行。

## R9模型日志及只读身份修复（19:08 UTC）

R9严格有效，0 CRITICAL / 2 MAJOR / 3 MINOR，原始费用9.536406750000001 USD。Claude lens遗漏requested/observed记录的问题已补正：正式spawn绑定assistant/lens身份并记录requested，正式turn.complete记录实际usage的observed；MCP和shell仍拒绝助手写入。新注册处理器回归先复现缺失绑定，再核对不同requested/observed输入及只读拒绝。它是实际生产处理器的确定性测试，不宣称执行了新的Claude原生模型会话。

Codex post_to_ui schema同步1..200字符并增加消息副作用边界验证；UI/assistant shell查询不得冒用其他actor，新适配器回归在构建包上先FAIL后PASS。第一次直接在缺共享包的适配器源目录运行出现ModuleNotFoundError，属于执行环境错误，日志保留并改用正式合并构建包。M6逐批R19未执行已明确披露，交叉参考其它批次实际拒绝，不改写为M6已跑。

源码/构建Claude各30 PASS，Codex adapter24 PASS（9.508s）、pack10 PASS（4.472s），两层validate、61/69构建、diff check及CodeGraph sync通过。共享核心自完整308项通过后未变。最新Full access原生CLI/app-server transport发现六工具并完成init/documents/project/confirmation/page，thread01a117bf-7330-77f1-894e-266bb8a5e737，page16/16/stale=false；不把该无推断fixture当成科研或新的模型身份验证。已退出并于19:06:39 UTC归档删除项目和home，31份transport清理回执、23真实模型案例清理回执均保留，目前无运行测试目录或测试agent。

已报告原始CLI reviewer费用：33个native cache记录中Sonnet5.5合计3.7793676 USD，Fable5.1九轮合计65.0304275 USD；5份空/不完整历史JSON没有推断费用，统计不含Codex调用及未提供的账单。R10独立审查进行中。12 §1完整科研benchmark仍开放、未获豁免；不报告整体M8实施批次完成。

19:11 UTC：R10调用无效，CLI返回is_error=true/terminal_reason=api_error及会话额度限制，显示本日19:50 UTC恢复。没有finding列表，不能把占位零计数当零缺陷结论。原始费用7.827081999999999 USD和原件保留于reviews/codex-real-infrastructure-r10-invalid-1.md及scratch；等待明确重置时间后再运行规定Fable模型的新独立审查。功能验证、清理及开放项状态不因限流而改写。

19:25 UTC：等待额度恢复期间已用全新Full access原生M6R19补齐逐批未登录探针。实际plugin MCP继承空Claude profile，19:20:16 public proposal_review拒绝未登录，session未分配/费用0，无实验、任务、CPU或付费review；五份current SHA、四文件source/dist/cache、actual observed模型和权限以及最终page11/11false独立通过。正常退出/关闭自建pT后去凭据归档删除project/home/profile，累计24案例全部清理。控制器对失败日志格式的初始断言错误保留、纠正，未改产品。最新源码/测试结论不变；R11有效终审待19:50 UTC额度恢复，完整科研benchmark开放项仍保留。

20:06 UTC：额度重置后的R11严格有效，0 CRITICAL / 2 MAJOR / 2 MINOR，原始费用8.22379575 USD。新发现Claude无docs的confirm_request绕过共享消息校验并切阶段；注册处理器回归修复前FAIL。现缺失/空docs提前拒绝，无阶段/进程/通知/窗口副作用；所有非notice请求进入共享消息校验，带docs的有效请求仍正常记录并进入awaiting_confirmation。源码与构建各31项PASS；pack10 PASS（6.502s）、两层validate、61/69构建和CodeGraph sync通过。共享及Codex工具/测试未变，308/24结果沿用，不把规则文字更新称为完整共享重跑。

lens运行键保留宿主格式并在规则明确，按lens名称/实际session及模型事件比对；Claude并发指导已与Codex对齐，agents类型注释包含助手。Node crypto统一派生的尝试因官方SDK导入规则而未加载，已撤回并保留失败日志，未改SDK权限或既有身份。最新Full access无推断原生安装检查通过并即时退出/归档/清理，32份transport和24真实实例均无运行目录。完整科研benchmark仍开放；R12独立终审待执行。


## 2026-10-07 R12/R13 后续验证

独立 R12 有效（Fable 5.1，completed/is_error=false），0 CRITICAL、1 MAJOR、3 MINOR。MAJOR 是仍开放的完整科研 benchmark。Claude 的 discovery 拒绝现在先于共享消息落盘；新增注册 handler 旧码失败、修复后源码与构建包均 32 PASS。pack 10 PASS，两层 `claude plugin validate` 均 exit 0，实际命令/时间/日志/hash 保存于 `final-validation-r13.json`。

R12 指出的 11 §1.8 单项目链缺口开始用全新原生 E2E 项目补测：此前 M1/M4 拆分覆盖并不等同于此验收。目前 E2E 仍在运行；只有实际完成筛选→追加重复→候选复核→结项且清理后，才更新为完成。


21:19 UTC：R12单项目链MINOR由E2E实际补齐，11CPU/显式extend/6真实评审/实际资格拒绝/NOT GO/33current SHA/page227，保留原seed0/EV3及numbers fail。独立审计后正常退出并删除第25个项目/home。当前无运行测试Codex或临时项目；R13完整diff独立审查待执行，benchmark MAJOR仍开放。


## R13 发现后的验证（2026-10-07 21:40 UTC 起）

新构建 r14 的 check_codex_sessions.py 已在隔离 Full access/never 配置下实际通过；worker 与 resume 同线程 `01a1184e-5844-73b1-9747-378841a8741c`，UI `01a1184e-5e46-7330-8cb3-bdc3127d4899`（只读），本地 Responses 3 次，live_followup queued，task open。没有真实模型推断；CLI 已退出，项目与隔离 home 已删除。归档 `evidence-archive/native-sessions-r14-full-transport.tar.gz`，SHA256 `4ef2ec12bdeb28fc5211c13892ff20c7058f7687e95d39f6f0f724314d16bdf7`，第 33 个 transport 清理回执。

Claude 最新修复需新的真实宿主项目回归，见 `Claude-final-codex-fixes.md`（进行中）；不以 32 项 handler 测试替代该步骤。


## 22:30 UTC 最新功能核验

Pi 多回合费用漏计已用真实 R14 raw 复现并修复；R15/R16 及确定性成功预算/失败终止回归均证明包含所有 turn_end、不重复收费。JSON 提示明确 data object；新 Codex ReviewPrompt 的真实 Sonnet proposal_review 格式/登记通过（REVISE，不是方案验收），新 Claude R16 的实际 Pi triage/novelty/critical 通过并完成 Root 七 CPU、验收、冻结和独立 page131。限制、首次失败与费用详见 Claude-final-codex-fixes.md、ReviewPrompt-codex.md。

完整共享 311 PASS（309.493s，先于提示文字修订），提示修订后 source/built review_call 各 43 PASS（39.516/39.622s）；adapter24 PASS（9.431s，之后适配器未改），Claude source/built 各32 PASS（hooks之后未改），pack10 PASS（4.266s）。最新 build61/69、正式两层 Claude validate exit0、CodeGraph sync 与 diff check 通过；exact command/log/hash 将存 final-validation-r14.json。

26 个真实 Codex、33 个 transport、3 个 Claude 重测实例均退出并清理；没有运行测试项目或测试 agent。真正 Pi-ready 路径现在已实测，旧“仅确定性选择/未登录”记录为当时范围。14 规定 Fable R14 独立终审待执行；12 §1 完整 A/B/C 科研 benchmark 仍未执行、未获豁免，不宣称整体实施批次完成。


2026-10-07 R17：在同一最终构建上重跑完整14命令集：共享311、组装335、adapter24、pack10、Claude源码/构建各32及正式两层validate通过，build62/70。最新Full access安装thread01a11889-8952-7ac3-ab15-90f4ae776670，六tools/工作流/page通过，归档SHA e6e09921e50ae7d27af9455b5c0c1e378e9d72fe417e4a305a8a454f3650d50c；exec/resume同线程01a11890-c573-7191-96bf-9e587e429a8c，独立readonly UI01a11890-cafa-7a22-beea-6b17639fd527，3 Responses、queued/open通过，归档SHA faf4c0f450392d74362efb3481f8a99106201b41ed613de7566b9d81b1a6dfb2。两夹具都已退出并删除，transport累计35，不算新的真实模型案例。Fable R14的Claude单项目完整链及修改后的Codex worker评估顺序由新R17项目继续补测，仍在运行，不报告通过。


23:30 UTC最新：R17两端单项目完整链各11实际CPU、真实跨族六review/五维、显式追加只新增1/2、原seed0/EV3不变和NOT GO均已实际完成并清理；Claude30 current SHA/page208，Codex41/page257，所有RS结清，原始失败/限制保留。27 Codex/4 Claude/35 transport项目均移除，无运行测试agent。当前R17全命令集通过的精确日志与源SHA写入final-validation-r15.json；完整diff Fable R15待执行，完整科研benchmark仍OPEN。


23:46 UTC：Fable R15有效0 CRITICAL/1 MAJOR/1 MINOR；R17功能/完整两端链证据已核验，无新增功能代码缺陷。09 §2.2费用文档MINOR按正确实现修正；原有代码、构建和全套检查SHA保持一致，post-review文档SHA另存。唯一MAJOR为完整科研benchmark未执行/未豁免，整体批次不能记完成。原始费用6.9200405 USD已入独立CLI账本；66原始review记录/15阶段审查，五份未知费用明确保留。
