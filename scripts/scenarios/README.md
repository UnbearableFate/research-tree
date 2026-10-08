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
