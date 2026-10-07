# M2 Codex 真实宿主补测（进行中）

日期2026-10-07，scratch `/tmp/research-tree-codex-20261007-1XA9OP`。新项目 `rt-test-M2-codex`、隔离 `codex-home-M2`，Herdr `rt-codex-m2` / 用户pane w3:pF。prepare-only旧线程正常退出后，在尚未init的项目安装最新字段/草稿修复构建并启动新原生主线程 `01a11608-afd0-7801-bfcf-1e5dfffcbad8`，observed gpt-6-luna。主会话 FullAccess/approval never；真实UI仍read-only。

## 规划与新 init 认证检查

provided CPU code HEAD `55988b40cd12beff096b028349e682040af586f0`，完整runner/stats/configs/动态methods registry。H-0001为Momentum beta0.85相对固定beta0.9，H-0002仅保留warmup，不沿用旧模板Nesterov；搜索seed顺序[1,0,2]、筛选1、追加0/2、确认100/101/102。尚无方法输出，不为命中U01/U02造数。根范围仅一次Adam sanity和六基线，600nodeSec、单次1node10s、严格0.5pp。

prepare保留输入。原生init实际marker `reviewer_backend`：checked_at11:06:02Z、model anthropic/claude-sonnet-5-5、backend claude_code、ok=true/error=null，正式计划明确只代表认证/基座预检，不是review/model可用回执。五个关键源码与实际缓存一致，`M2-latest-source-cache-consistency.json`。新文献2411.19671/1910.04209分别核验/缓存/阅读，重新登记本项目记录，未复制历史DB/确认/费用。

正式init-plan.v1/protocol.v1：actual required_counts n_train1200/n_val400/epochs30/steps1140、准确model字符串，未把seed门当per-run计数。立项确认前2假说、未指派根任务T-0001、0训练；页面33/33/stale=false，inbox空。

## 独立 UI 真实流程

human-facing原生 `codex_cli.py ui` 打开研究窗口，所有UI observed gpt-6-luna、原生turn_context read-only（`M2-native-ui-proof.json`）。

- 草稿93a7fa1b/thread01a11610-9f5b-7151-8db3-fc1e37bee0da：模糊图表要求保存同REQ-0001、向用户澄清，actions=[]；未转交RLD、不确认。补充seeds0/1/2、Adam/Momentum、accuracy百分比/真实train_time_s、PNG路径后，同REQ正文七字段及两个用户消息来源均完整，仍open/v0/actions=[]。
- 明确仅提交供后续审阅：真实submit动作completed，REQ-0001.v1为D-0014，三个用户消息原话保留；RLD实际回执ui-0001，只接收需求，不确认或派worker。
- SVG修订首次误传材料project参数，被fixed child-project门拒绝，v1不变；记录thread01a11615-5449-7d90-b6c3-e4f0bb4cbaa3/actions=[]。测试控制器提供省略project的技术澄清后，新真实UI提交同REQ v2，SVG/path变更、旧版与原话保留，submit completed，RLD实际ui-0002回执。此修订成功经过技术协助；默认流程需新安装重测。
- 正常明确立项确认首次被UI误解只读限制，thread01a1161e-b78a-7c30-8aad-3a2d65500f0e返回actions=[]，phase仍awaiting_confirmation。查明SessionStart UI高层context写了笼统“不确认计划”，与输出confirm转交控制器的职责冲突；源码改为禁止直接写状态，明确转交已给出的用户确认。不能以单元fixture已成功替代该实际失败。
- 本旧缓存测试经控制器澄清后，真实UI thread01a11621-eb0c-7292-963a-291405434d62输出confirm、动作completed，登记D-0017/phase=confirmed。原话明确仅根T1/600nodeSec/单次1node10s，不授权H1/H2/图表或确认seed；RLD实际接收并开始根任务。此成功验证控制器动作链，修复后默认UI确认仍待新项目验证。

截至本记录，根运行/验收、M2自然方法输出/不确定性、同族R04及最终页面仍未记通过；不把UI或认证检查当作M2科学场景已完成。

## 根验收与方法继续（11:48 UTC）

真实 root observed gpt-6-luna，线程 01a11623-51e1-77a2-9c7f-bfaaefbfad27，原生 Full Access。七个实际 CPU run 通过：sanity seed1（本项目首筛选seed为1）、Adam/Momentum各0/1/2；七笔真实reservation全settled/共7node-seconds、两项artifact_imported Evaluation。RLD核对新版交付 D-0024 后 T-0001 accepted，并确认实际结束通知与空inbox；快照 M2-root-accepted.json。不把旧版交付冒充当前验收。

控制器在读取根验收后明确当前 user_instruction，仅授权既有 H-0001 Momentum85：只改方法独立注册项，保持六冻结文件、同实际方法提交重跑三Adam控制、真实sanity/跨族code_review、按seed1→0/2搜索至三seed上限，不启动H2/confirmation/网格。自然结果不满足U01/U02则原样报告，另用明示功能模拟项目测试所需边界，不能改真实指标。方法继续中，额外场景/最终页面/R04仍待核验。

## 真实sanity的两处预执行拒绝与已有产物恢复

H1独立Momentum85代码44bce6fb087cab4fe2daec43953707dcafc2292a、冻结六路径未改，真实worker线程01a11636-2984-7860-92e1-3b9c6d046c27。首次错误create_run seed0被拒，本E4 sanity正式seeds=[1]，没有run/reservation/CPU；T2 delivered原报告D31与M2-sanity-prelaunch-refusal.json保留。控制器当前授权只在原E4/s1首次运行，新恢复请求登记先因about引用尚不存在T3被拒，随后按help与实际返回ID纠正顺序，T3/D34/D35合法建立，不抹掉拒绝原文。

实际E4/s1/a1经原runner于12:23:56一次退出0，accuracy0.87、counts200/100/2/14、真实usage1秒；随后纯验收路径遗漏research/且workspace大小写错误，worker停下，原run submitted/RS8 attached reserved，未重跑。控制器读真实日志后提供仅语法检查的finalize_existing_sanity.py，同h1线程12:35:30公共MCP将已有原manifest导入/valid/原RS8结算，未启动CPU且原五份产物SHA不变（logs/m2-finalize-existing-sanity-result.json）。manifest8d630056…/metrics5ecbb66a…，attempt1/key/job不变，工程错误未当科学负向。

12:43:04实际Claude Code / Sonnet5.5 code_review RV1/D43已登记，名义原始费用待raw汇总；review_calls四舍五入值0.155509USD，不将其当精确raw费用。method controls/search与U01/U02仍进行中；不能凭sanity通过或review可用宣布M2完成。

## U01/U02 实际最终证据（15:08 UTC）

同一方法 commit 44bce6fb087cab4fe2daec43953707dcafc2292a，真实 root 重跑三 Adam controls E5，真实 H1 运行 E6，均 attempt1、公共导入/结算。E6 首 seed1 的差 -0.25pp，EV4 为 inconclusive；追加 seed0/2 后 EV5 按 seed0/1/2 的配对差 [+0.75,-0.25,-1.00]pp，mean -0.16666666666666666pp、SD 0.8779711460710615，严格0.5pp门未过，三seed上限仍 inconclusive，未强制剪枝。EV4 原记录保留。accuracy 三次均0.9025；Adam对应0.895/0.905/0.9125。真实失败只涉及验收路径或预执行门，修正后没有额外CPU attempt。

T4/T5 accepted，旧版本结果保留，最终审计 D60→D61 更正 seed 展示次序，不能把 JSON 排序与配置顺序混同。M2-state-1447.json 证明14个实际run、14笔结算，共14/600秒，无开放reservation/live worker。code_review 原始 Claude Code费用0.15550920000000001USD，raw is_error=false/terminal_reason=completed/modelUsage仅Sonnet5.5；DB四舍五入0.155509USD。

U01/U02 的真实宿主边界已通过。R04与恢复配置/最终页面目前正在同线程新安装resume中收尾，尚不能计全部批次完成；旧UI默认失败已在新M4默认五操作中重测通过。

## R04与恢复/最终页面/清理

真实公共proposal_review明确拒绝reviewer openai/gpt-6-luna与Leader gpt-6-luna同族，无新session或费用；D65审计。U01/U02分别为D66/D67正式当前审计。旧T2错误seed请求由RLD取消，D31原拒绝不变；T1/T3/T4/T5 accepted。正式human CLI恢复原Anthropic配置原字节并登记D68/config.v4，事件由原生RLD确认。控制器独立build/check与M2-final-state.json证明367/367/stale=false、无live、14笔settled/14秒、费用仍0.155509USD。Codex正常/exit、自建收尾pane w3:pM关闭，项目与隔离home按用户要求归档证据后清理；原用户w3:pF未由控制器关闭。终审及额外资格撤回native边界仍待完成，不将此记录当整体协议完成。
