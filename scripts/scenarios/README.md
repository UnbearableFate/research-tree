# 真实宿主场景底座（S0）

本目录是 `plans/research-tree-implementation-and-real-scenarios.md`（下称实施文档）S0 交付的测试工具：
虚构的 ToyOpt Lab 项目、本地执行适配器、独立 scorer、只读观察器与场景记录器。它们只属于测试，
不进入插件发布包。

| 文件 | 作用 |
| --- | --- |
| `../make_rt_test_project.py` | 生成全新 ToyOpt Lab 项目（`--host --stage --case --attempt`）；控制器文件写在项目外的 `<项目>.ctl/` |
| `toyopt/toytrain/` | 项目代码：`data.py`（固定切分 train / explore / c1 / c2 与身份）、`train.py`（CPU 上真实训练）、`run.py`（写 run_manifest.json 的 runner）、`methods.py` |
| `local_exec.py` | 复制为项目的 `tools/local_exec.py`：按 submission key 真实启动本地进程，记录 PID 与启动时刻、实测 CPU / 墙钟用量；同一 key 不重复启动；可在场景前声明一次性故障窗口 |
| `scorer.py` | 独立 scorer：从 `model.json` 与评测切分重算 correct/n，不导入项目训练代码，报告中的数字不影响它 |
| `observe.py` | 只读观察器：数据库快照（比较前后 SHA-256）、逐 run 重评分、evaluation 均值独立重算、作业启动账本、`build_site.py --check` |
| `record.py` | 场景记录（实施文档 §12.2）与故障清单（§3.3）的校验、汇总 |

## 证据边界

- 正常运行都是“合成数据上的真实计算”：accuracy 由 predictions 与标签计数得到，loss 来自模型输出，
  usage 由适配器的监督进程实测。没有公式指标。
- c1 / c2 在 S0–S6 中放在项目代码仓库里（`scenario.json` 记 `blind: false`）：这些阶段是非盲功能测试。
  S7 的盲评需要独立私有材料与访问边界（实施文档 §11.4），不能把这里的切分换个目录升级为盲评材料。
- 参考方法 `configs/reference.json`（sgd，lr 0.005，1 epoch，batch 32）在 S0 开发校准时用开发 seed 7–9 与
  explore 切分选定后冻结；c1 / c2 的实例 seed 换成了校准从未接触的值（见 `data.py` 注释）。

## 每个场景的步骤（概要）

1. `python3 scripts/build_plugins.py --target all`，记录源码 commit、未提交变更与 `BUILD.json`。
2. `python3 scripts/make_rt_test_project.py <持久目录>/rt-<Sn>-<host>-a<NN> --host <host> --stage <Sn> --case <SC-id>`。
3. 在 Herdr pane 中启动宿主（Claude Code 加载 `dist/claude/plugins/research-tree`；Codex 用隔离的
   `CODEX_HOME` 安装 `dist/codex`），以虚构用户身份只经正常入口输入（`/research-tree …` 或 `$research-tree …`
   与对话）。故障清单在启动前写好，经 `RT_LOCAL_EXEC_FAULTS` 交给适配器。
4. 结束后运行 `observe.py <项目> --tools dist/<host>/plugins/research-tree/tools --out <记录目录>/observer.json`，
   把原始会话、观测模型、评审回执与快照路径写进 `record.py new` 生成的记录，再 `record.py validate`。

## S2–S7 控制器：`scenario.sh` + `lib.sh` + `sN.sh`（2026-10-09 起）

- `bash scenario.sh <S2..S7> <claude|codex> <两位 attempt> <agent-pane> <scheduler-pane>`：生成全新项目，跑开场
  （prepare、init、用户决定、confirm、根基线，即 SC-COMMON-01 前缀），把开场后的项目存为
  `rt-scenarios/<阶段>/prefix-<host>-aNN.tar.gz`（加同名 `.json`），再跑阶段正文 `sN.sh` 与共有后缀（build、check、
  终检查点、证据、关 pane、打包构建）。共用部分在 `lib.sh`；各阶段只有 `decision()`（立项时用户的决定）与 `body()`。
  S0、S1 仍用 `run_s0.sh`、`run_s1.sh`；SC-S3-03 用 `run_s3_upgrade.sh`。
- **从开场分叉重试**：`FORK=rt-scenarios/<阶段>/prefix-<host>-aNN.tar.gz bash scenario.sh ...`。快照解到本次 attempt
  自己的目录，agent、调度服务与控制器的所有读写都在 bwrap 中运行，副本绑定在快照原路径上（数据库、标记文件与 worktree
  记的是绝对路径）；新会话先按插件的恢复入口接手，再跑阶段正文。开场的检查点以 `prefix-*.json` 复制过来，
  `forked_from.json` 写明来源。规则：
  - 每个阶段 × 宿主至少保留一次**完整不分叉**的运行，SC-COMMON-01 只能由它证明（`record.py` 拒绝分叉 attempt 的
    SC-COMMON-01，记录脚本也不为分叉 attempt 写它）；分叉 attempt 的记录带 `forked_from`。
  - 修复改动了开场路径（prepare/init/confirm/基线、schema、迁移）时不要分叉，跑完整新 attempt。
  - 开场时若有 worktree 在项目目录之外（agent 自选位置），快照不保存（commands.jsonl 记原因），不能分叉。
  - 同一快照的分叉一次只跑一个（它们共用原路径，宿主会话目录也按原路径命名）。
  - 这是实施文档 §2.5（每个项目执行完整前缀）的偏离，由用户 2026-10-09 批准，用于缩短阶段专属场景的重试。
- **冒烟检查**：`bash smoke.sh <阶段> [host]`（约 30 秒）以 `SMOKE=1` 运行同一控制器：agent 与 herdr 换成记日志的
  替身，提示只写入日志，检查点与助手脚本照常执行，报告 bash 错误、助手脚本非零退出、观察器失败，以及提示中指向冻结
  框架（code/toytrain、configs、data）的文件路径。全新项目上没有数据库，检查点会跳过、依赖数据库的助手会失败；
  加 `FORK=<快照>` 可让它们在真实开场上执行。冒烟产物都在 `rt-scenarios/smoke/`，构建也打包在那里，不碰真实归档。
  **冒烟只检查控制器的管道，永远不是证据**；agent 会怎么做完全没有检查。

## 测试套件

`python3 scripts/run_tests.py`（先 `python3 scripts/build_plugins.py`）：共享核心、仓库测试与 Codex 适配器按测试类
并行，约 45 秒（串行约 8 分钟）；开发中用 `python3 scripts/run_tests.py test_units test_s7` 只跑相关模块，
`--suite repo|codex|shared` 选套件。提交或合并前跑全部。
