# M0 固定基准：版本、F01/F02 回归测试与清点

日期：2026-10-06。批次内容见 12 §1（M0）与 00 §2–§2.3。

## 1. 实施基准

| 项目 | 值 |
|---|---|
| 设计基准提交 | `48b3841d97275b2e9ad010d91d261acc9c7c4f5c`（00 §1.1） |
| 实施开始时的提交 | `fb56e27`（分支 `new_feature/from_ARIS`） |
| `shared/`、`claude-mod/`、`codex-plugin/` 相对设计基准 | 除本批次新增的测试外**无差异**（`git diff 48b3841 -- shared claude-mod codex-plugin`），00 §2 的所有源码事实仍成立 |
| schema 版本 | `research_tree.sql` 标注 schema_version 6（10 §2.1） |
| 宿主版本 | Claude Code 2.1.291；codex-cli 0.160.1（14 写的是 0.160.0，本机已升级一个补丁版本）；pi 1.0.4；herdr（HERDR_ENV=1） |

基线测试（实施前）：共享核心 73、打包 4、Codex 适配 13（在 `dist/` 中运行）、Claude 适配 20（`claude plugin test`），共 110；
设计文档写的“109 个”少计了一个。`claude plugin validate`（marketplace 与插件）通过，`check_codex_install.py` 通过。

## 2. F01 / F02 回归测试

`shared/research-tree/tests/test_research_db.py::KnownDefectTest`，四项在基准上均为预期失败（`unittest.expectedFailure`），
M1 修复后去掉标记并改为必须通过。F01 两项断言 STAT_MISMATCH 且没有写入判定与比较边；F02 两项断言候选列表为空、
`decide(go)` 返回 EVIDENCE_STALE 且项目仍为 active。F02 的前置条件（自洽数字构成的候选会被列出）是一项普通测试 `test_a_consistent_candidate_is_listed`。
M1 还必须让夹具 `Fixture.baseline()` / `evaluate()` 改用自洽数字（11 §1.2：夹具提供自洽数字，不得放松生产校验）：

| 测试 | 对应 | 基准上的实际行为 |
|---|---|---|
| `test_f01_summary_must_match_the_runs` | F01 / M01 | 三个 run 的主指标均为 70.0，`record_verdict(metric_mean=70.3)` 被接受 |
| `test_f01_comparison_must_match_the_runs` | F01 / M02 | 方法与 SOTA 的 run 数值完全相同；均值 70.0 如实填写，只有 `delta_mean=0.3` 是假的，判为 `beats_sota` 被接受 |
| `test_f02_a_new_harness_ends_go_candidacy` | F02 / E01 | 节点 beats_sota 且两项复核 pass 后更换框架：SOTA 指针被清空，但 `go_candidates()` 仍返回该节点 |
| `test_f02_a_new_harness_refuses_go` | F02 / E01 | 同一情形下 `decide(project, status=go)` 被接受 |

这确认了 00 §2.3 的场景 A 与场景 B 不只是静态推断：在真实数据库夹具上可稳定复现。

## 3. 协议与实际数据的清点

当前数据库能表达与不能表达的内容（M1 起逐项补上）：

| 设计需要的信息 | 现状 |
|---|---|
| 指标方向与单位 | 只有项目级 `metric_direction` 与 `metric_is_percent`；次指标没有方向、单位或阈值 |
| 原始逐 seed 指标 | `run.metric_value`、`run.secondary` 由调用者填写；无指标文件路径、无 manifest、无输入身份 |
| 汇总与比较 | `experiment.metric_mean/sd`、`rel_compared_with.delta_mean/deltas` 由调用者填写，只做自洽检查，不从 run 重算（F01） |
| 配对 | 只按整数 seed 交集计数；没有数据切分、预训练来源、协议版本等配对字段 |
| 协议 | 不存在协议记录；`min_setup` 是自由文本文档 |
| 评测类型 | 不存在 |
| 证据版本 | 结论缓存在 `hypothesis.experiment_status` 与复核字段上；更换框架只清空 SOTA 指针（F02） |
| 比较参照 | 判定时查找父节点“最新已判定实验”，不在创建时固定 |
| 预算 | 单次运行上限（`max_nodes`、`max_walltime_s`，创建实验与有效 run 时检查）、筛选预算 `screen_budget_node_h`（决定筛选 seed 数）、已记录实际用量的提醒阈值 `alert_node_h`；无总预算、无在途预留 |
| 文档中的数字 | 无任何代码核对结果文档里的数字是否出现在指标文件中 |

### 3.1 现有数据（虚构 demo 快照 `demo/research/P-demo-lora-opt/snapshots/data-00221.json`）

- 7 个实验（1 个基线、6 个方法实验）；每个实验的 `metric_mean` 等于其有效 run 的 `metric_value` 均值四舍五入到 4 位小数，
  即 demo 的汇总是自洽的；`rel_compared_with` 的 `delta_mean`、`deltas` 是生成脚本按 run 值算出后写入的。
- run 只记录路径字符串（如 `outputs/E-0001/s42/train.log`、`curve.json`）；仓库里没有任何 run 输出文件，也没有指标文件
  （`demo/research/*/outputs/` 被 `.gitignore` 排除，`make_demo.py` 不写 `metrics.json`）。因此 demo 只能做记录级重算，
  按 10 §2.3 属于 `legacy_unverified`，不能声称产物级导入。
- 主指标 `acc`，`metric_is_percent=true`；4 个次指标没有方向与单位记录（demo 的方向只在生成脚本的 `SIGN` 常量里）。

## 4. 未知项

- 真实项目中历史 run 是否保存了可重算的原始指标文件：本仓库只有虚构 demo，demo 不含任何 run 输出文件（见 3.1）。
- 现有用户项目的 `metric_is_percent=false` 次指标的实际单位：需在迁移时由用户核对（10 §2.4）。
- `go_margin` 在旧项目中按 `metric_is_percent` 解释为百分点绝对差或相对百分比差；旧记录只有这个布尔值，没有输入单位，
  因此无法判断 run 填的是比例还是百分数。

## 5. 本批次完成后的 §2 结果

| 命令 | 结果 |
|---|---|
| `unittest discover -s shared/research-tree/tests` | 77 项通过，其中 4 项为预期失败（F01×2、F02×2） |
| `unittest discover -s tests` | 4 项通过 |
| `build_plugins.py --target all` | claude 30 文件、codex 38 文件 |
| `claude plugin validate`（marketplace、插件） | 通过 |
| `claude plugin test dist/claude/plugins/research-tree` | 20 项通过 |
| Codex 适配测试（dist 内）、`check_codex_install.py dist/codex` | 13 项通过；安装检查通过 |

## 6. Herdr 双宿主测试（14 §4）

**阻塞。** 在 Herdr 侧边 pane 启动宿主 agent（`herdr agent start ... --kind claude`）被本会话的自动模式权限分类器拒绝
（理由：Create Unsafe Agents），随后连只读的 `herdr pane list` 也被视为同一目的而拒绝。未启动任何宿主会话，
“所有批次”场景**未执行**，没有 `M0-claude.md` / `M0-codex.md`。

已准备、可复现的部分（`<T>` 为 scratch 下的测试目录）：

```bash
python3 scripts/make_rt_test_project.py <T>/rt-test-M0-claude --host claude   # plan.md（两条假说）、research-tree.yaml、code/
python3 scripts/make_rt_test_project.py <T>/rt-test-M0-codex --host codex
sh scripts/setup_codex_home.sh <T>/codex-home <T>/rt-test-M0-codex             # 复制登录与用户配置、改模型、信任项目、安装 dist/codex；测试后删除
```

被拒绝的步骤（14 §4.2）：`herdr pane split --current --direction right --cwd <T>/rt-test-M0-claude --no-focus` 后
`herdr agent start rt-claude --kind claude --pane <P1> -- --plugin-dir <repo>/dist/claude/plugins/research-tree --model claude-sonnet-5-5`
（第一次尝试带 `--permission-mode bypassPermissions`）。需要用户为本会话授予
启动 Herdr agent 的权限后补跑；在此之前 M0 不能按 14 §6 报告为完成。
