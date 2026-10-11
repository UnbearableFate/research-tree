# 单一研究工作流版本与验证范围（2026-10-11）

## 当前破坏性契约（插件 0.2.0）

- 只支持 **version 3 配置、schema 23 数据库**，工作流固定为快速筛选与增量发现，没有模式切换
- 会话角色仅为 RLD、按需 UI、根节点 Architect、假说 Worker、Explorer、Analyst；Reviewer 只经独立评审包装器。没有根 Worker 别名、角色回退或常驻 UI
- 逐候选按当前 revision/hash、最小设计与授权范围准入；Explorer 实际提案使用 `cache/discovery/proposals/*.json` 的 `{source, candidates}` 格式
- 普通廉价搜索保留有效性、原始证据、方法/主张身份、配对、预算及防重复检查。晋级与 GO 保留强制独立确认、最终五维复核、未决问题和真实用量记账
- 旧项目、配置和数据库明确拒绝并提示迁移；不原地升级、静默改写、解释缺失字段或自动迁移科学状态
- 方法执行去重只看不可变科学身份与材料范围，不看名称、输出路径、调度资源或 screen/replicate 标签。已观察的确认不能通过改名、改节点或改资源重采样；重复方法/材料会复用原实验或明确拒绝并指出既有证据。不同方法仍可共享预声明批次与基线，不同 holdout 可使用相同训练 seed
- 删除旧模式、旧角色、旧 verdict/API、旧评审流水线及无效配置；保留实际实现的独立单元与只读重复建议。高级 verification 配置可应用，零次修复预算不再回退为默认两次

迁移前停止旧写入者、对账在途作业并保留完整备份。在新目录运行 prepare，从 v3 模板重建计划与配置，显式登记所需协议、指标、文献与证据，再由用户确认范围。不能复制旧数据库/标记、只改版本号、沿用旧资格或重置确认材料使用史。历史计划与证据档案保持原样；其中的兼容条款不是当前接口契约。

## 当前验证记录

本轮实际运行（2026-10-11）：

- `python3 scripts/build_plugins.py --target all`：Claude 66 个文件、Codex 73 个文件，独立安装包均为 0.2.0
- `python scripts/run_tests.py -j 12`：**562 个测试、139 个类全部通过**，包含共享核心、仓库/打包/真实 CPU ToyOpt 与 REG 工具，以及新构建 Codex 适配器的 38 个测试
- Claude 源码与新构建包各 **40 个 fixture-only 回调通过**；各有 **7 个原生 SDK 回调未运行**，两边回调不是两套独立原生证据
- 全部 Python 源码/测试的 Ruff `F,E9`、`git diff --check`、`uv lock --check --offline` 通过
- 独立最终评审无未解决的可操作问题：另跑 221 个 Python 测试、40 个 Claude 夹具回调并构建两包，确认 75 个生产文件与所测产物一致；复现并验证了确认重采样修复，以及最终复核豁免回执的真实保留（这些是上面测试范围的交叉检查，不累加为新的总数）
- 旧版本拒绝包含只读与写入入口的字节级不变断言；当前完整确认流程、权限、原始证据、独立重复、预算、恢复与宿主回调由明确标注的夹具覆盖

本环境没有 `codegraph` 命令，未执行 sync；使用源码检查和独立评审。没有修改实际科研数据库，也没有改写历史计划、测试记录或既有 demo 证据。

尤其检查旧配置/DB/项目拒绝时无写入、移除字段和角色被拒绝、Architect/Worker 所有权隔离、候选逐个准入、确定性 outcome、确认与复核、争议、预算、防重复、恢复及轻量展示。复现入口：`scripts/run_tests.py`、`scripts/build_plugins.py --target all`、`scripts/run_claude_fixtures.cjs`。Claude 夹具限制见仓库 `claude-mod/research-tree/TESTING.md`。

夹具不证明原生 SDK/UI、真实模型、GPU/生产调度器或科研质量。没有相应新证据时，不把历史原生测试或 fixture 数量作为当前版本的端到端验收，也不宣称科研速度或发现质量提升。

## 历史证据与限制

此前快速工作流的实现、测试数量与当时的边界保留在仓库 `plans/fast-research-workflow.md`；更早的阶段场景与原始证据保留在 `plans/research-tree-implementation-and-real-scenarios.md`、`plans/design/test-logs/` 等历史档案中。这些记录未被本轮改写，其中原生宿主、CPU toy training、预声明模拟指标和确定性传输夹具的范围各不相同。

完整固定资源 A/B/C 科研效能比较没有在本节登记通过。不能把模拟指标、CPU toy training 或接口测试记为 GPU/生产调度器科研训练，也不能从 reviewer CLI 费用推断其他模型宿主的全部费用。
