# 当前流程的真实宿主场景工具

本目录提供唯一 version-3 合同的 ToyOpt Lab 项目、真实本地执行适配器、独立 scorer、只读观察器和场景记录校验器。
它们只属于测试，不进入插件发布包。历史 S0–S7 的批次、升级和旧角色控制器已删除；历史计划、会话和证据保持原样，
不能作为当前版本已通过真实场景的证明。

## 工具

- `../make_rt_test_project.py`：生成全新 ToyOpt 项目与 version-3 配置；`--stage`、`--case`、`--attempt`
  仅标记来源，不切换流程。控制器材料写在项目外的 `<项目>.ctl/`
- `toyopt/toytrain/`：固定 train / explore / c1 / c2 切分、CPU 上实际计算的逻辑回归、manifest runner
- `local_exec.py`：复制到项目的 `tools/`；按 submission key 启动进程，记录 PID，实测 CPU 和墙钟用量，
  同一 key 不重复启动；支持运行前声明的一次性故障
- `scorer.py`：不导入项目训练代码，从保存的模型与切分独立计算 correct/n；报告不能改变独立分数
- `observe.py`：读取当前数据库快照、逐次重评分、核对 evaluation 均值与真实作业账本、检查网页，并核对数据库未变
- `attempt_metrics.py`：区分研究重试、传输重试、重复作业、重复结算和已验证修复之后的可避免失败
- `db_snapshot.py`、`usage_snapshot.py`：只读数据库与确认材料使用记录
- `record.py`：核验记录、模型与实际 effort、原始证据、断言、恢复证据及预先声明的故障；不自动宣称成功

## 证据边界

正常 ToyOpt 运行的 accuracy 来自预测计数，loss 来自模型输出，usage 由监督进程实测。
c1 / c2 随项目交付，因此这些是非盲功能测试；私有评估必须另有访问边界，不能仅靠移动目录建立。
参考方法 `configs/reference.json`（sgd、lr 0.005、1 epoch、batch 32）保留原始开发校准后冻结的值与切分身份。

`../benchmark/make_task.py` 只生成 REG 公式回归 fixture，其预设偏移会使 accuracy 与预测计数不同。
生成的计划、控制器来源、指标及 manifest 均标记 `evidence_class: reg` / `formula_metric`。
它们不能证明科研有效性或模型能力，不能记为真实宿主场景通过。

## 运行与核验

1. `python3 scripts/build_plugins.py --target all`，记录源码 commit、未提交变更和 `BUILD.json`
2. `python3 scripts/make_rt_test_project.py <新项目目录> --host claude --stage FAST --case SC-FAST-01`
3. 用实际宿主加载本次构建，从当前入口开始新项目；采用 `rld/main`、`ui/ui`、`architect/root`、
   `worker/h…`、`explorer/main`、`analyst/main` 的唯一角色合同。根框架与基线由 architect 负责
4. `.venv/bin/python scripts/scenarios/observe.py <项目目录> --tools dist/<host>/plugins/research-tree/tools --out <记录目录>/observer.json`
5. 用 `record.py new` 建立记录，保存实际会话、观测模型与 effort、评审原始输出、恢复前后快照，最后 `record.py validate`

`observe.py`、`db_snapshot.py`、`usage_snapshot.py` 在进程内导入 research_db，须用仓库的 `.venv/bin/python` 运行
（系统 `python3` 没有 latticedb）；`../benchmark/score.py` 在 `.venv` 存在时用它启动 research_db。
`record.py` 只认非空普通文件作为会话、原始证据、评审原始输出与恢复前后快照，且须位于该场景的证据位置：
记录目录、记录树中同阶段同宿主的目录（如 `evidence-aNN/`）、场景项目及其 `<项目>.ctl/`。

回归检查：`python3 scripts/run_tests.py --suite repo test_scenarios test_benchmark test_attempt_metrics test_private_eval`。
完整检查按仓库要求执行全部套件；Codex 适配器套件每次从当前源码构建到临时目录后运行，不读取也不改写 `dist/`。
回归 fixture 与单元测试通过不能替代真实宿主会话的验证。
