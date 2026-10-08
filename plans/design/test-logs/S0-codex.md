# S0 Codex 真实场景记录

宿主 codex-cli 0.160.1，主会话 `gpt-6-luna`，reasoning medium（会话记录与 agent_models.jsonl 一致）；隔离 `CODEX_HOME`
（`scripts/setup_codex_home.sh`，复制登录、只信任测试项目），插件从构建快照的 marketplace 安装到该 home 的缓存目录。
插件 hooks 按 README 信任；研究工具 MCP 调用与插件自带工具的沙箱外命令（prepare、文献检索）由控制器以用户身份批准，全部记在
commands.jsonl。

| 尝试 | 源码 | 结果 | 说明 |
| --- | --- | --- | --- |
| a01 | `b45974c` | FAIL | 两个产品缺陷（见下），停止并修复 |
| a02 | `762a60b`（运行中把项目的 `tools/local_exec.py` 替换为调度服务版：sha256 `027a4bb6461f…`，即 `7047965` 的 `scripts/scenarios/local_exec.py`） | PASS | 记录：`scenarios/S0/codex/*/a02/record.json` |

## a01 发现的缺陷

1. Codex 立项提示只说“配置中的预算与门槛”，没有像 Claude 端那样给出插件算出的生效字段；RLD 把 yaml 的
   `require_precheck: true` 原样写进项目记录（discovery.mode 为 off 时生效值应为 false），`create_hypothesis` 因此要求发现回执。
   修复：Codex 立项提示给出 `db_fields` 并说明不要从 yaml 原样抄写（`762a60b`，REG `test_planning_prompt_gives_the_effective_project_fields`）。
2. worker 调用 `update_task(status=in_progress, assignee_id=root)`（重述自己的指派）被当作改派拒绝。修复：重述当前指派为空操作
   （`762a60b`，REG `TaskTest.test_lifecycle`）。

## a02 过程

prepare → init（生效字段正确：require_precheck=false、repo_path=code/）→ 用户的暂停要求 → `$research-tree confirm`。
第一个 sanity 作业随 Codex 沙箱命令结束被杀（Codex 在独立 PID 命名空间运行命令）：这是测试执行适配器的问题，控制器以“站点管理员”
身份改为调度服务模式（服务在沙箱外启动作业），并告知 RLD；RLD 将该 run 记为失败 attempt 1、经用户指令释放其预留，worker 以
attempt 2 重跑。之后冻结框架，3 个基线 run 导入并 valid，独立 scorer 一致。SC-S0-02 同 Claude：错误报告 STAT_MISMATCH 被拒、
无 evaluation；修正后 EV-0001 = 79.16666666666667 pp。`/quit` 后新会话只读恢复，未新增运行；`$research-tree build` / `check`
→ 136 / 136。

## 遗留观察

- 被杀的第一个 sanity 进程的少量 CPU 时间不在插件账本中（预留已释放）；S6 处理“已启动但回执丢失/进程消失”的计量。
- 恢复会话因已有登记的 RLD 会话而未接管（hook 提示需 `research_control attach`）；只读核对不受影响，接管路径在后续阶段的恢复场景检验。
