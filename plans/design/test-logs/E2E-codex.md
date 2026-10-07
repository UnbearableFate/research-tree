# 单项目 Codex 端到端补测

2026-10-07。R12 独立评审发现，M1 的追加重复与 M4 的候选五维复核分属两个项目，不能视作 11 §1.8 的一次完整端到端验收。本次新建 P-E2E，只复制静态训练代码和运行辅助脚本；没有复制旧项目的数据库、结果、评审或模型记录。

原生 Codex 0.160.1 在 Herdr 自建 w3:pV 运行，thread `01a11818-c5f3-7722-a02a-bacc602ec563`，模型 gpt-6-luna / medium、Full access / never，加载最新版安装插件。项目与 CODEX_HOME 分别隔离在 scratch 的 rt-test-E2E-codex / codex-home-E2E。既有用户授权覆盖临时 hooks、MCP、依赖和 Git；结束后退出、归档去凭据证据并删除。

## 初始化与确认

在任何初始化前声明 simulation_only：primary accuracy 为 0.80 + 0.0025×(seed%3) + functional_case 偏移，baseline 为 0、combination 为 +0.01。真实 CPU logistic 训练、measured_logistic_accuracy、loss、曲线、时间、weights、manifest 和 usage 仍实际执行及保存；诊断不表示真实科研收益。方法只继承已有 Adam 更新，不声称新优化器。原始静态框架 HEAD `a4e601387349a701876e38a3701599870fb99007`；冻结 train/runner/stats 和三个框架 config，共六路径，methods.py 可修改。

真实 literature CLI 已验证并读取 Adam arXiv1412.6980，文献 current/verified。协议 JSON version1 / eval_type simulation_only，匹配固定数据与训练设定，排除 method、functional_case、seed 和 code_ref。正式 1200/400/30epochs/1140steps；sanity 200/100/2epochs/14steps。search seeds 0/1/2，筛选仅0，后续重复1/2；independent confirmation 100/101/102。总预算600 node-seconds，各真实请求1node/10s。配置原生绑定后 code_review、sanity、recheck、design、literature 门启用；require_precheck 保留默认 false，无临时关门。

确认请求先遇到 docs 数量上限拒绝，随后按合约修正；保留原始事件。控制器独立核对全部当前文档 SHA、冻结代码及协议，确认阶段没有 experiment/run/worker 后，通过正常 research_control confirm 流程明确授权先运行 Root7。planning 阶段的模板、doc_type、指标集合和关系误调用拒绝均保留，不作为产品缺陷或通过证据。

## Root 基线

固定 managed worker/root thread `01a1181c-97cb-7102-8f03-962153bb6094` 实际执行 E1 sanity、E2 Adam、E3 Momentum，各正式 baseline 三 seeds，合计7 CPU jobs。真实安装 MCP 调用完整保存于 logs/host-harness-mcp.jsonl。7/7成功导入且 valid，每笔 usage 结算，无重跑；两次权威评价 EV1/EV2。RLD 独立接受 T1 并选定 Adam SOTA。

控制器只读审计 E2E-root-independent-audit.json 核对每个实际 manifest/metrics/usage/curve/log/weights、import SHA、counts、尝试、提交身份和结算，共7实际 node-seconds。Root worker 已结束，无活跃 Root 会话。

## 当时的后续未完成项（下文已补齐）

已登记唯一 H1/worker positive_probe/T2，正在准备实际方法分支及代码评审。下一阶段仅允许 sanity 和 seed0；真实筛选评价后暂停，随后显式 extend 同一 experiment 到3且只跑新 seeds1/2。真实五维复核、基于其结果的结项、独立审计、退出和项目清理尚未完成，不报告整链通过。完整科研 A/B/C benchmark 仍开放，未执行、未获豁免。

## 21:04 UTC 单 seed 证据

真实方法提交 `ab7fdffb739611b9c280781df01048a4d8b1ce64` 只改 methods.py。RV1 原始 Sonnet CLI 成功（is_error=false，terminal_reason=completed，modelUsage仅claude-sonnet-5-5），code_review clear，原始费用0.1432746 USD。

RLD 第一次创建 E4/E5 忘记指定 owner，默认 main；辅助脚本在任何 CPU/run/reservation 前拒绝，保持这些空 metadata 和原拒绝历史。未修改数据库或角色。正式创建 owner=positive_probe、标签 positive_probe-sanity-owned / positive_probe-owned 的 E6/E7，实际 runner 仍 --method positive_probe。新 method_runs_owned.py 只将允许的实验标签替换，所有 ownership/actor/task/node/commit/valid-attempt/MCP checks 保持；原 helper 留存。E6 sanity 与 E7/s0@1 均实际导入/valid/settled。当前9 actual jobs/9 node-seconds；同一方法线程 `01a11821-3121-7f62-8ee4-2a91fdaac0b7` 多次正常 resume。

首个结果 v1 因限制说明中仍含“优于 SOTA”字样被保守词法门拒绝；保留原稿，新v2改为只陈述允许的仿真范围。D27 current，经 RLD 评价 EV3：accuracy mean81.0pp、SD=null、配对效果1.0pp/n=1；**实际 outcome=positive_signal，但 gate_passed=false / passes_gate=false**，不是 inconclusive，也未通过SOTA门。E2E-screen-state.json、E2E-screen-independent-audit.json、E2E-screen-baseline-proof.json 保存当前快照、九run原始审计和seed0原记录/hash。控制器随后明确授权真正 extend E7至3，新增最多2CPU；追加执行、五维复核及结项仍未完成。

## 21:08 UTC 追加重复证据

RLD 原生 extend_seeds E7至3；相同方法身份/线程仅新执行 E7/s1@1、E7/s2@1，helper跳过已valid的s0。控制器 E2E-replication-independent-proof.json 对比追加前后快照：seed0完整record与EV3完整record精确不变；旧result.v2 SHA `671998702878d6c77ca34b19b549b89756360ad8f2371f7250719ae0e3ead104` 和旧n1 preview SHA `5afcb53fce5404a285abbfbe45a5fca792055c23ab4b343893fbd2cdf61ae61e` 保留，新增run列表恰好s1/s2。

新v3结果与独立n3 preview创建EV4：n=3、mean81.25pp、SD0.25，对Adam配对deltas[1,1,1]pp、gate_passed=true，eval_type仍simulation_only。11 actual jobs/11 node-seconds全部导入/valid/settled，0 open reservation；独立核验全部原始文件与imports见E2E-eleven-run-independent-audit.json。五维复核/最终结项及清理尚未完成。


## 五维实际评审

五个candidate_recheck全部真实执行且绑定同一EV4：numbers fail；protocol、novelty、theory、method_code pass。缺失underscore brief路径和误传code_ref参数的提前拒绝保留、不计作已完成评审。correct existing hyphen brief实际执行method_code后才计全五维。numbers独立指出数值虽与原文件一致，但硬编码偏移不是验证标签测量，真实logistic指标不变，且v3结果未充分自述公式；保留原fail，不以重审强迫clear。最终报告必须解释此限制，不覆盖原输入/评审。其他维度的pass不表示新颖科研方法或科研效益。

E2E-six-review-independent-proof.json核对真实CLI raw全部is_error=false、terminal_reason=completed、modelUsage仅claude-sonnet-5-5、当前review文档SHA与EV4绑定；一code_review加五candidate，共原始费用0.7526712 USD。实际session turn_context也独立核实三个线程的17个上下文均gpt-6-luna/Full access/never，见E2E-native-permissions-proof.json。当前结项与清理仍待实际完成。


## 最终独立审计与清理

E2E-controller-closeout.json 对原生MCP事件/最终只读快照核验：唯一实际 extend E7到3；get_eligibility 返回false；项目status=not_go（DEC2）、两个任务accepted、11run均succeeded/valid/attempt1、11笔reservation全settled且合计11node-seconds、无live/openRS。33 current文档逐个SHA一致；method diff仅methods.py。独立页面227/227、stale=false。协议评审一次读取项目外层plan.md权限拒绝和所列未读材料均保留为评审自身限制；不声称该review完整核实了它们。控制器初始化审计及全部实际raw artifacts验证另有独立证据。

同一项目完成11 §1.8建项目→确认→Root基线→一个方法→实际导入→显式追加重复→真实五维复核→有依据NOT GO结项，functional acceptance通过；不是科学收益证明。代码门clear与五维原结论均保持，不追加确认训练或为GO改判。

原生主Codex正常/exit，agent list确认已退出后关闭仅自建w3:pV；无目录使用进程、Git bundle verify成功、去凭据归档后删除project/home。第25份cleanup receipt时间 2026-10-07T21:19:27.322270+00:00，project tar SHA256 9d82485488daf34f6ca30e3e37c4cc75b6bc58170abf967619e327fbadd9cb96。保留405 canonical MCP事件、867条选定会话回执、269可读项目文件及34控制器审计输入/输出。全25实例共3649可读文件，32 transport fixtures也已结束清理；没有保留运行测试项目，用户pane不关闭。

独立Fable R13终审及本地Git收尾仍待执行。12 §1完整科研benchmark与真实Pi已登录路径不在本项目中补充验证；保留原开放/未验证声明。


## R17 最新提示的第二次原生单项目回归

完整记录见[跨端修复回归](Claude-final-codex-fixes.md#codex-r17-最终完整链与清理2330-utc)。全新项目P-E2ER17在当前R17插件上实际通过原生$research-tree confirm、Root7、方法sanity/真实Sonnet clear/单seed、原生extend3且只补1/2、五维Sonnet与RLD独立复核、实际资格拒绝及NOT GO。代码872621fcb0cd9dab71f85a0965121ae64415a548只改methods.py，实验owner h0001在全部有效后evaluate；先前提示中的owner/顺序遗漏已由最新真实worker覆盖。原seed0/EV3不变，11真实CPU/11 settled RS、41current SHA/page257通过，主与后台均Full access/never。

初次Root协议顶层steps错误导致真实PAIRING_MISMATCH；修正当前协议后重导原manifest，没有重跑CPU；首次错误与后续恢复保留。真实review六份费用0.85856679999999995 USD（DB0.858566），五维均pass也不产生科学GO。项目/隔离home在23:30:38 UTC正常退出与归档后删除；第27个Codex案例、257可读证据及原始回执/SHA见E2ER17-controller-closeout.json、-cleanup-proof.json与evidence-archive/E2ER17-*。
