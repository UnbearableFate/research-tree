# M5 Codex 真实宿主测试（进行中）

2026-10-07；scratch `/tmp/research-tree-codex-20261007-1XA9OP`，项目 `rt-test-M5-codex`，隔离 home `codex-home-M5`，自建 pane `w3:pG`，agent `rt-codex-m5`。原生插件安装后启动 `gpt-6-luna` medium、Full access / approval never；四 hooks 已按用户授权信任。日常配置未修改。

## 实际模型与根流程

- 主线程 `01a11650-b441-7a41-bb6b-7a0b586e1e9d`、root `01a1165a-decd-7030-80fb-680ae407514a`、h0003 `01a11667-6aae-7871-ae53-130a46391919` 均有实际 observed `gpt-6-luna` 记录。
- 原生 prepare/init 于 12:22:51 完成，所选 Claude Code / Sonnet 5.5 认证预检可用。默认规划协议字段正确；前两个 root 请求因冻结顺序与 helper 前提冲突被合法取消，v3 新请求先由 RLD 静态审计并冻结真实 HEAD `8c8cc045b9649f01afdb12f26f530b61e06f94b8` 的六条框架路径，再确认并指派。
- T-0003 根七 run（Adam sanity 一次、Adam/Momentum 各三 seed）真实 CPU、manifest 导入、valid 与实际用量结算通过；独立 RLD 审计 D-0031，T-0003 accepted、SOTA E-0002。实际 7 node-seconds；不把 toy-v1 代理结果宣称为真实科研优势。

## X01 / X06 与三次实际失败

12:45:08 原生 MCP `create_hypothesis` 对 D-0036 缺 Claim map 返回 `DESIGN_SECTION_MISSING`，没有新增 hypothesis。实际拒绝收据 `<scratch>/M5-X01-native-refusal.json`；原始 native rollout 保留。v2 仍缺成功判据/失败解释被拒，合规 v3 D-0038 创建实际 H-0003。项目占位 T-0004 取消，新 T-0005 正式指向 H-0003 / h0003。

worker 只改未冻结的 `toytrain/methods.py`，三份真实 commit 分别为 `5a0620bc24d5ed35b0fcc39ebb7bf1d363ce4e78`、`e28c79e0ebbae02707df7f4ff671f72297025283`、`66f5b0d02ac958cc6d2e169195d5231c9e21034a`。预先声明 FaultNaN 为故意工程故障；两次无效 patch 保留 nonfinite 根因，不称为成功修复。

E-0004/5/6 各 seed 0、attempt 1，分别经冻结 runner 真实执行并 exit 1，原日志记录 non-finite parameters。manifest、runner/train logs 与 usage 真实存在，metrics/curve/model 不存在；没有伪造、导入或科学 Evaluation。RS-0008/9/10 各按实际 1 node-second 结算，项目累计 10/600，无开放预留。六条冻结路径无 diff。

同任务、同根因 `M5_INTENTIONAL_NONFINITE_METHOD_OUTPUT` 的 patch 请求前两次接受，第三次返回 `FAILURE_BUDGET`，当即停止，无第四次 CPU。D-0043 worker 交付、D-0044 独立 RLD 审计后，T-0005 accepted，分支归还。只读快照 `M5-state-1256.json` 是审计前 delivered 检查点，不能替代随后 accepted 的原生回执。

## 尚未完成

第二阶段 X07 已实际通过：原 h0003 同线程恢复，新 T-0006 / D-0046 以既有失败为上下文。两次从 H3 文档重建的 methods-only commit `3ea45d50e218bf0b3b0ca9d53734a2f5bcb5b5c0`、`4ebf0f4cbe67a68a6faa4249b21943799a1cbeac` 分别对应 E-0007/8，真实 runner exit 1，各结算 1 秒。第二次失败结算后第三次 rewrite 请求返回 blocked=true / rewrites=2，数据库 blocked_reason 与公共 status 的 task_blocked attention 均存在；未执行第三次重写/CPU。

解除前保存 D-0050 与控制器 `M5-state-1306.json`、`M5-X07-native-blocked.json`（两份真实 native status 响应）。D-0051 交付、D-0052 独立审计后，RLD 以当前停止 decision D-0053 调用 unblock_task，再取消 T-0006。API 按契约清空当前 failure_log，原 rewrite/blocked 历史由上述快照/文档保留；没有将解除解释为新运行授权。T-0005 accepted 与两条 patch 历史不变。`M5-state-1312.json` 证明无 live worker、T-0006 cancelled，实际累计 12/600 秒。

R04 同族配置已由临时用户经正式人工 CLI 应用，实际反例仍在执行；未登录 R19、新安装恢复、最终页面检查与 Fable 终审未完成。

评审费用：当前 Claude Code 与 pi 实际调用均 0 USD；认证预检不算模型 review。

## R04/R19 与最终核验（15:06 UTC）

R04 实际同族 review 于13:19返回 REVIEW_UNAVAILABLE、session null/cost0，没有新增review；报告D57。控制器14:49以正式human CLI恢复原Anthropic配置字节，登记D58/config.v4，事件已由原生RLD确认。正常退出旧主会话后，安装最新构建并用同线程01a11650-b441-7a41-bb6b-7a0b586e1e9d在新自建pane w3:pM resume，Full Access / never，临时CLAUDE_CONFIG_DIR明确未登录。

唯一一次实际公共proposal_review返回 REVIEW_UNAVAILABLE: claude is not logged in，无session、review文档与模型费用；不调用pi、不登录、无降级。新独立审计D60 project/reports/r19-final-audit.v1.md再次读取X06/X07的真实manifest/log/usage与任务历史。控制器M5-final-state.json证明无活跃worker，实际12/600秒、全部12预留已结算；独立human CLI check得到297/297/stale=false。原生会话随后正常/exit。

M5所需原生场景与页面已验证，阶段Fable终审仍待完成，不宣称整个协议已完成。按用户后续清理要求，项目与home将在保存关键证据后移除，归档路径见codex-cleanup.md。Claude Code/pi 模型review累计均0USD；认证与失败门不计模型调用。
