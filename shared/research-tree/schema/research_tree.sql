-- 研究假说树 LatticeDB 数据模型（schema_version 11，2026-10-07：M3 预留与预算、M4 评审文档与复核、M5 设计门、sanity、失败预算）
--
-- 说明
-- * LatticeDB 是属性图数据库（Cypher 查询），不执行 SQL。本文件用 SQL DDL 作为可读的
--   结构规格：每张 TABLE = 一个节点 label；列 = 节点属性。带 "-- edge:" 注释的列
--   不存为属性，而存为一条该类型的边（单值关系）；以 rel_ 开头的表 = 多值关系（边类型），
--   其列为边属性。以 _doc_id 结尾的列存为属性（文档 id 字符串），由写入代码校验其存在。
--   类型 INTEGER_LIST / TEXT_LIST 表示 list[int] / list[str] 属性，JSON 表示 dict 属性。
-- * LatticeDB 没有 CHECK/UNIQUE/NOT NULL/外键约束。下文的约束由建库/写库 Python 代码
--   负责校验；id 列建属性索引，唯一性由写入代码保证。
-- * 属性类型限于 null/bool/int/float/str/bytes/list/dict。时间统一为 UTC ISO-8601 字符串。
-- * 正文不入库：假说、对比、推导、实验设计、结果解读、评审意见、用户指令等写在文档库里，
--   库中只存 document 索引（路径、版本、简短摘要）和状态、关系。
-- * 状态分层，互不混用：
--     hypothesis.status        节点状态（4 种），由 RLD 依据实验结论决定
--     hypothesis.experiment_status  节点的实验结论（取自最新实验的统计判定）
--     hypothesis.*_recheck     新颖性、理论正确性复核；只在实验优于 SOTA 后由 RLD 进行
--     run.exec_status / valid  单个 seed 的作业执行状态与工程验收
--     experiment.verdict       冻结统计代码对该实验给出的判定（数字由接口从 run 重算，见 evaluation）
--     evaluation               一次统计计算：绑定输入 run/attempt、代码与框架版本、协议、指标规范与参照；
--                              科学内容不就地修改，新的计算追加新记录（plans/design 05 §3）
--     decision                 每次状态变更的审计记录（追加，不修改）

-- 元数据（单例）
CREATE TABLE meta (
    schema_version  INTEGER NOT NULL,          -- 本模型版本
    data_version    INTEGER NOT NULL,          -- 每次写事务提交 +1；HTML/快照引用此号
    updated_at      TEXT    NOT NULL
);

-- 研究项目（树根）
CREATE TABLE project (
    id                  TEXT PRIMARY KEY,      -- 例：P-online-polora
    title               TEXT NOT NULL,
    goal_doc_id         TEXT,                  -- 研究目标文档
    stage               TEXT NOT NULL CHECK (stage IN ('stage1', 'stage2')),
    status              TEXT NOT NULL CHECK (status IN (
                            'active',          -- 进行中
                            'go',              -- 阶段1 GO
                            'not_go',          -- 项目 NOT GO
                            'stopped'          -- 用户要求停止
                        )),
    -- 最小实验与门槛（立项登记）
    min_setup_doc_id    TEXT NOT NULL,         -- 最小实验设定文档（模型、数据、训练量、评测）
    primary_metric      TEXT NOT NULL,         -- 主指标名
    metric_direction    TEXT NOT NULL CHECK (metric_direction IN ('higher', 'lower')),
    metric_is_percent   BOOLEAN NOT NULL,      -- true：门槛按百分点绝对差；false：按相对差
    secondary_metrics   TEXT_LIST NOT NULL,    -- 综合比较的其他指标，例：final_loss、loss_auc、peak_mem_gb、train_time_s
    go_margin           REAL NOT NULL DEFAULT 0.05,  -- 优于 SOTA 的最小主指标优势；有指标规范时等于主指标的 minimum_practical_gain
    gate_seeds          INTEGER NOT NULL DEFAULT 3,  -- 判定“优于 SOTA”所需 seed 数，也是每个实验的 seed 上限
    seeds               INTEGER_LIST NOT NULL, -- 统一 seed 顺序，长度 = gate_seeds；实验按前缀使用
    screen_budget_node_h REAL NOT NULL DEFAULT 10,  -- 筛选预算；seed 数按 SOTA 首个 seed 的成本计算
    min_related_work    INTEGER NOT NULL DEFAULT 3,     -- 创建节点时至少引用的相关研究文档数
    max_nodes           INTEGER NOT NULL DEFAULT 8,     -- 单次运行上限
    max_walltime_s      INTEGER NOT NULL DEFAULT 3600,
    max_parallel_workers INTEGER,              -- 同时有任务在手的 worker 数上限；null 为不限
    alert_node_h        REAL,                  -- 累计用量提醒阈值（node·h）；超过时提醒用户，null 为不提醒
    config_doc_id       TEXT,                  -- 生效中的项目配置（research-tree.yaml 的登记版本）；以上预算与门槛取自它
    -- 硬预算（plans/design 05 §4）：整数 node-seconds；为空 = 只有用量提醒，不声称成本封顶
    total_limit         INTEGER,               -- 授权总量
    search_limit        INTEGER,               -- 其中探索（筛选、复制）的上限
    confirmation_limit  INTEGER,               -- 其中独立确认的上限（总量的一部分，不是追加授权）
    repair_limit        INTEGER,               -- 其中修复的上限
    overrun_factor      REAL NOT NULL DEFAULT 2.0,  -- 实际用量达到预估的倍数即写待处理项（不取消作业）
    admission_paused    TEXT,                  -- 准入暂停的原因（实际超额等）；新的提交预留被拒，直到用户处理
    stall_structural_at INTEGER NOT NULL DEFAULT 2,  -- 子树连续几批没有新发现即须换向（同方向子节点被拒）
    stall_human_at      INTEGER NOT NULL DEFAULT 4,  -- 连续几批没有新发现即上报用户
    recheck_required    BOOLEAN NOT NULL DEFAULT FALSE,  -- GO 候选须有跨模型复核（review.trigger: candidate_ready；07、09）
    review_usd_alert    REAL,                  -- 累计评审费用提醒阈值（USD）；达到后暂停新的评审调用
    review_cost_usd     REAL NOT NULL DEFAULT 0,  -- 评审调用的累计费用（review_call.py 登记）
    design_required     BOOLEAN NOT NULL DEFAULT FALSE,  -- 想法→实验设计的文档门（03）：goal 问题锚点、假说文档章节、实验设计章节
    max_primary_claims  INTEGER NOT NULL DEFAULT 2,   -- 每个想法至多几条主 claim（design.max_primary_claims）
    max_core_blocks     INTEGER NOT NULL DEFAULT 5,   -- 每个想法至多几个实验块（design.max_core_blocks）
    code_review_required BOOLEAN NOT NULL DEFAULT FALSE, -- 方法实验提交前须有该代码的跨模型代码审查（design.code_review）
    sanity_required     BOOLEAN NOT NULL DEFAULT FALSE,  -- 方法实验提交前须有同一代码的有效 sanity 运行（design.sanity_first）
    require_precheck    BOOLEAN NOT NULL DEFAULT FALSE,  -- 建节点须有查新与批判性评审回执（discovery.require_precheck，02 §3）
    literature_verification BOOLEAN NOT NULL DEFAULT FALSE, -- 只有存在性核验为 verified 的文献计入 min_related_work（08 §2）
    memory_max_items    INTEGER NOT NULL DEFAULT 5,   -- 上下文包中至多几条经验（memory.max_items_per_task）
    memory_counterevidence BOOLEAN NOT NULL DEFAULT TRUE, -- 经验与其反例一起返回（memory.include_counterevidence，K03）
    max_repairs_per_root_cause INTEGER NOT NULL DEFAULT 2,  -- 同一根因至多几次补丁（search.max_repairs_per_root_cause，03 §8）
    screen_seeds        INTEGER,               -- 筛选 seed 数上限（version 2：verification.screening_seeds 的个数）；空则只按筛选预算
    protocol_doc_id     TEXT,                  -- 现行实验协议（JSON 文档：评测类型、配对字段、必须一致的设定）
    metric_spec_doc_id  TEXT,                  -- 现行指标规范（JSON 文档：每个指标的方向、单位、效应、最小实际收益、保护阈值）
    -- 冻结的实验框架与统计代码（根节点 worker 实现，RLD 审核）
    repo_path           TEXT,                  -- 代码仓库根；节点分支与框架核对都在这里
    harness_ref         TEXT,                  -- 冻结版本的 git commit；更换后须重跑 SOTA
    harness_paths       TEXT_LIST,             -- 框架与统计代码的文件/目录，节点代码中必须与 harness_ref 一致
    sota_experiment_id  TEXT,                  -- 当前 SOTA 基线实验；edge: SOTA_BASELINE
    owner               TEXT NOT NULL,         -- RLD 身份
    -- 根节点（baselines）的 worker，同下方 hypothesis 的 worker 字段
    -- 节点的 worker：一个节点一个 worker 身份，从头负责到节点完成；会话丢失时用同一身份从恢复文档接手
    worker_id           TEXT,                  -- worker 身份 worker/<worker_id>；指派后不变（假说为 h<编号>，根节点为 root）
    worker_agent_id     TEXT,                  -- 当前 worker 会话的 agent ID（Claude Code 用 SendMessage 续接）
    worker_session_at   TEXT,                  -- 当前会话绑定的时间
    resume_doc_ids      TEXT_LIST,             -- 恢复 worker 所需的文档：节点文档、任务请求与交付等（自动维护，可追加）
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- 假说树节点
CREATE TABLE hypothesis (
    id                  TEXT PRIMARY KEY,      -- 例：H-0007；创建后不变
    project_id          TEXT NOT NULL,
    parent_id           TEXT,                  -- edge: CHILD_OF（→ hypothesis；顶层节点 → project）
    title               TEXT NOT NULL,
    statement           TEXT NOT NULL,         -- 一句话可证伪假说；完整内容见 doc
    doc_id              TEXT NOT NULL,         -- 假说文档
    candidate_id        TEXT,                  -- 发现阶段的候选（CAND-编号）；其查新与评审回执在建节点时核对
    status              TEXT NOT NULL CHECK (status IN (
                            'pending',         -- 待验证
                            'verifying',       -- 验证中
                            'expandable',      -- 验证完成，可拓展
                            'prunable'         -- 验证完成，可消灭
                        )),
    -- 实验结论决定节点状态：每个节点都必须有实质性代码改动和实验
    experiment_status   TEXT NOT NULL CHECK (experiment_status IN (
                            'todo',            -- 未开始
                            'running',         -- 代码改进与实验进行中
                            'no_gain',         -- 无提升：各项指标都不优于父节点
                            'beats_parent',    -- 优于父节点
                            'beats_sota',      -- 优于 SOTA：gate_seeds 个 seed，主指标效应超过最小实际收益（evaluation 重算）
                            'inconclusive'     -- 不确定：最新 evaluation 的 outcome 为 inconclusive（含达到 seed 上限仍接近门槛）
                        )),
    -- 实验优于 SOTA 后才由 RLD 复核；创建时的相关研究见 rel_references
    novelty_recheck     TEXT NOT NULL CHECK (novelty_recheck IN ('pending', 'pass', 'fail')),
    theory_recheck      TEXT NOT NULL CHECK (theory_recheck  IN ('pending', 'pass', 'fail')),
    priority            INTEGER NOT NULL DEFAULT 0,  -- 越大越优先；实验信号是第一推动因素
    -- 投入处置（与执行生命周期、实验证据分开记录；plans/design 06 §3）
    disposition         TEXT CHECK (disposition IN ('active', 'paused', 'retired')),  -- 空：旧记录，按 status 推断
    disposition_reason  TEXT,
    reconsider_when     TEXT,                  -- 复议条件
    -- 停滞计数（06 §5）
    direction           TEXT,                  -- 节点代表的研究方向（机制标签）；停滞的子树拒绝同方向的新子节点
    new_findings_streak INTEGER,               -- 连续几批没有新发现
    stall_state         TEXT CHECK (stall_state IN ('none', 'structural', 'human')),
    status_reason       TEXT,                  -- 当前状态的一句话理由；详细见最近 decision
    owner               TEXT NOT NULL,
    -- 节点的 worker：一个节点一个 worker 身份，从头负责到节点完成；会话丢失时用同一身份从恢复文档接手
    worker_id           TEXT,                  -- worker 身份 worker/<worker_id>；指派后不变（假说为 h<编号>，根节点为 root）
    worker_agent_id     TEXT,                  -- 当前 worker 会话的 agent ID（Claude Code 用 SendMessage 续接）
    worker_session_at   TEXT,                  -- 当前会话绑定的时间
    resume_doc_ids      TEXT_LIST,             -- 恢复 worker 所需的文档：节点文档、任务请求与交付等（自动维护，可追加）
    -- 关键时间戳：由写入代码自动记录，调用者不能设置
    created_at          TEXT NOT NULL,         -- 节点创建
    started_at          TEXT,                  -- 首次开始验证（待验证 → 验证中）；重新验证不改写
    first_experiment_at TEXT,                  -- 首次实验：本节点实验的第一个运行提交
    first_result_at     TEXT,                  -- 首次统计判定
    beats_sota_at       TEXT,                  -- 首次判定节点结论为优于 SOTA
    concluded_at        TEXT,                  -- 节点完成：最近一次转为可拓展或可消灭；重新验证时清空
    updated_at          TEXT NOT NULL
    -- 写入校验：
    --   创建时 ≥ project.min_related_work 篇现行 literature 文档（rel_references）
    --   status='pending'    ⇒ experiment_status='todo'，两项复核为 'pending'
    --   status='verifying'  ⇒ 节点已有代码分支，experiment_status 不是 'todo'
    --   experiment_status 设为结论 ⇒ 等于该节点最新已判定实验的 verdict（verdict 为 needs_rld 时由
    --                                RLD 选择并附决定文档），且该实验使用当前冻结框架
    --   *_recheck 只在 experiment_status='beats_sota' 后改变，依据 RLD 的 novelty/theory 文档
    --   status='expandable' ⇒ experiment_status 为 beats_parent 或 beats_sota
    --   status='prunable'   ⇒ 引用证据（实验、evaluation 或文档）并写复议条件，同时记一条 disposition=retired
    --                          的决定；从未实验的节点只能引用描述本节点的现行用户指令文档（用户决定放弃）
    --   评估字段只在 status='verifying' 时改变；任何变更都在同一事务写入 decision
    --   GO 资格由 evaluation 计算（get_eligibility）：最新 evaluation 仍适用、过门槛与保护指标，两项复核为 'pass'
    --   且绑定到该 evaluation 的代码；不读 experiment_status 等缓存字段
);

-- 实验：一个代码版本在若干 seed 上的评估；每个 seed 的作业由 run 记录
CREATE TABLE experiment (
    id                  TEXT PRIMARY KEY,      -- 例：E-0031
    project_id          TEXT NOT NULL,
    hypothesis_id       TEXT,                  -- edge: TESTS（基线实验为空）
    kind                TEXT NOT NULL CHECK (kind IN (
                            'method',          -- 被测方法
                            'baseline',        -- 基线（含 SOTA）
                            'ablation',        -- 消融/对照
                            'sanity'           -- 最小规模 sanity（03 §8，M0）：不计 seed、不评估
                        )),
    method_name         TEXT NOT NULL,
    design_doc_id       TEXT NOT NULL,         -- 实验设计文档
    stage               TEXT CHECK (stage IN ('screen', 'replicate', 'confirm')),  -- 三级流程（06 §2.2）；空 = screen
    estimated_node_h    REAL,                  -- 登记时的成本预估（全部 seed 的 node·h）；新实验必填
    milestone           TEXT CHECK (milestone IN ('M0', 'M1', 'M2', 'M3', 'M4')),  -- 03 §6 里程碑
    budget_pool         TEXT CHECK (budget_pool IN ('search', 'confirmation', 'repair')),  -- 预留计入的分项
    selection_rationale TEXT,                  -- 为什么现在做、结果怎样改变下一步（同一 claim 多轮不确定后必填）
    result_doc_id       TEXT,                  -- 统计结果文档（冻结统计代码的输出与解读）
    code_ref            TEXT NOT NULL,         -- 运行的 git commit；打标签 exp/<实验ID>，分支删除后仍可追溯
    harness_ref         TEXT,                  -- 判定时核对通过的冻结框架版本
    baseline_experiment_id TEXT,               -- 创建时固定的 SOTA 参照（节点实验）；之后父节点或 SOTA 变化不改它
    parent_experiment_id TEXT,                 -- 创建时固定的父节点参照（父节点最新已判定的方法实验）
    evaluation_id       TEXT,                  -- 当前的 evaluation（可重建的缓存；历史 evaluation 保留）
    config_path         TEXT,
    config_hash         TEXT,
    ablation_of         TEXT,                  -- 消融：被消融的实验（同节点）；与它代码和配置都相同即 no-op，拒绝
    source_review_id    TEXT,                  -- 消融：出题的 ablation_plan 评审文档
    code_review_waiver_doc_id TEXT,            -- 代码审查不可用时 RLD 放行的决定文档（03 §8）                  -- (kind, stage, method, request, config_path 内容) 的哈希；与 code_ref、seeds 一起去重
    keep                TEXT_LIST,             -- 判定后仍保留的产物类别（例：final_weights），登记实验时声明
    keep_reason         TEXT,                  -- 声明保留的理由（哪个后续实验要用这些产物）
    cleanup             JSON,                  -- 清理账本：键为第几次清理，值为时间、执行者、保留类别、逐项结果与释放字节数
    seeds               INTEGER_LIST NOT NULL, -- project.seeds 的前缀；首个实验 1 个 seed，按预算或判定扩展
    nodes               INTEGER NOT NULL,      -- 每个 seed 申请的节点数，≤ project.max_nodes
    walltime_s          INTEGER NOT NULL,      -- 每个 seed 申请的时长，≤ project.max_walltime_s
    verdict             TEXT CHECK (verdict IN (
                            'no_gain',         -- 各项指标都不优于父节点
                            'close',           -- 差不多：扩展到 gate_seeds 个 seed 再判定
                            'beats_parent',    -- 主指标优于父节点
                            'beats_sota',      -- gate_seeds 个 seed、主指标效应超过最小实际收益（接口重算）
                            'needs_rld'        -- 统计代码无法判定，交 RLD
                        )),                    -- 基线实验为空；扩展 seed 后清空，待重新判定
    metric_mean         REAL,                  -- 判定所用 seed 的主指标均值（规范单位，接口从 run 重算）
    metric_sd           REAL,                  -- 方法自身的样本 SD；n=1 时为空
    owner               TEXT NOT NULL,         -- 执行 worker
    created_at          TEXT NOT NULL,
    evaluated_at        TEXT
    -- 写入校验：
    --   seeds 数 ≤ 按 SOTA 首个 seed 成本 c 计算的筛选数（满足 n·c < screen_budget_node_h 的最大 n）；
    --   verdict 为 close 或 beats_parent 时可扩展到 gate_seeds；RLD 可随时扩展到 gate_seeds
    --   判定前：所有 seed 的 run 有效；code_ref 包含 harness_ref 且 harness_paths 无改动；
    --           method 实验的 code_ref 不同于节点分支基准
    --   seeds 少于 gate_seeds 时 verdict 只能是 no_gain、close、beats_parent、needs_rld
    --   verdict=no_gain 当且仅当与父节点比较的所有指标差值都 ≤ 0
    --   verdict=beats_parent ⇒ 主指标相对父节点的差值 > 0
    --   verdict=beats_sota ⇒ 与 SOTA 的比较 passes_gate
);

-- 节点的代码分支与 worktree：每个假说节点至多一条
CREATE TABLE branch (
    id                  TEXT PRIMARY KEY,      -- 例：BR-0007
    hypothesis_id       TEXT NOT NULL,         -- edge: BRANCH_OF（一个节点至多一条分支）
    repo_path           TEXT NOT NULL,         -- 代码仓库根
    name                TEXT NOT NULL,         -- 分支名，例：node/H-0007
    base_ref            TEXT NOT NULL,         -- 创建时的基准：父节点分支或 main
    base_commit         TEXT NOT NULL,
    worktree_path       TEXT,                  -- worktree 移除后为空
    owner               TEXT NOT NULL,         -- 当前唯一提交者：active 时为 worker，交还后为 RLD
    status              TEXT NOT NULL CHECK (status IN (
                            'active',          -- worker 在 worktree 中开发并提交
                            'returned',        -- 已交还 RLD，等待处置
                            'merged',          -- 已合并
                            'kept',            -- 保留分支（例如作为子节点基准）
                            'deleted'          -- 已删除分支
                        )),
    head_commit         TEXT,                  -- 交还时的最后提交
    merged_into         TEXT,                  -- 合并目标分支
    merge_commit        TEXT,
    created_at          TEXT NOT NULL,
    returned_at         TEXT,
    closed_at           TEXT
    -- 写入校验：
    --   status='returned'               ⇒ head_commit 非空，worktree 无未提交改动
    --   status IN (merged, kept, deleted) ⇒ worktree_path 为空（worktree 已移除）
    --   status='merged'                 ⇒ merged_into、merge_commit 非空
    --   status='deleted'                ⇒ 该节点所有 experiment.code_ref 已有 exp/<实验ID> 标签
    --   returned 之后的状态变更由 RLD 决定，并在同一事务写入 decision
);

-- 单个 seed 的运行
CREATE TABLE run (
    id                  TEXT PRIMARY KEY,      -- 例：E-0031/s42
    experiment_id       TEXT NOT NULL,         -- edge: PART_OF
    seed                INTEGER NOT NULL,
    job_id              TEXT,                  -- 调度系统作业 ID
    submission_key      TEXT,                  -- 当前 attempt 的提交身份（reservation）
    attempt             INTEGER NOT NULL DEFAULT 1,
    exec_status         TEXT NOT NULL CHECK (exec_status IN (
                            'planned', 'submitted', 'running',
                            'succeeded', 'failed', 'cancelled', 'unknown'
                        )),
    valid               BOOLEAN,               -- 该 seed 是否通过工程验收；为 true 时下列实测值必须齐全
    retracted_at        TEXT,                  -- 有效 run 事后被证明无效（retract_run）的时间；引用它的 evaluation 失效
    retracted_reason    TEXT,
    invalid_reason      TEXT,                  -- valid 为 false 时必填：验收不通过的原因（引用日志）
    attempts            JSON,                  -- 重新提交前各次 attempt 的记录，键为 attempt 编号；由接口写入
    metric_value        REAL,                  -- 最终主指标
    secondary           JSON,                  -- 其他指标的最终值，键 = project.secondary_metrics
    nodes_used          INTEGER,               -- 实际节点数
    walltime_used_s     INTEGER,               -- 实际墙钟时间；成本 = nodes_used × walltime_used_s
    curve_path          TEXT,                  -- 过程曲线文件（loss、显存、吞吐随步数）
    log_path            TEXT,
    output_path         TEXT,
    started_at          TEXT,
    finished_at         TEXT,
    -- 产物导入（import_run_result）：冻结解析器从 manifest 读出的指标与身份
    manifest_path       TEXT,                  -- 运行 manifest（JSON），相对研究根目录
    manifest            JSON,                  -- manifest 中配对与协议核对用的字段（seed、数据版本、计数等）
    evidence_paths      TEXT_LIST,             -- 重算所需的最小证据（指标文件、原始评分材料）；清理不得删除
    import_record       JSON                   -- 解析器版本、文件哈希、导入时间与执行者；同一 attempt 重复导入幂等
);

-- 统计计算记录：由接口从登记的 run 重算，调用者不能提供权威数字
CREATE TABLE evaluation (
    id                  TEXT PRIMARY KEY,      -- 例：EV-0012
    experiment_id       TEXT NOT NULL,         -- edge: EVALUATES
    result_revision     INTEGER NOT NULL,      -- 该实验的第几次计算
    run_attempt_refs    TEXT_LIST NOT NULL,    -- 参与计算的 run 与 attempt，例：E-0002/s42@1
    input_revisions     JSON NOT NULL,         -- 每个 run 参与计算的数值与导入哈希
    pair_keys           JSON,                  -- 每个比较实际配对的键
    method_code_ref     TEXT NOT NULL,
    harness_ref         TEXT NOT NULL,
    harness_paths       TEXT_LIST,             -- 当时冻结的框架文件集合；更改即失效
    protocol_doc_id     TEXT,
    metric_spec_doc_id  TEXT,                  -- 为空：兼容规范（旧项目，legacy_unverified）
    baseline_experiment_id TEXT,
    baseline_evaluation_id TEXT,
    parent_experiment_id TEXT,
    parent_evaluation_id TEXT,
    result_doc_id       TEXT,
    metrics             JSON NOT NULL,         -- 每个指标：规范单位的逐 run 值、均值、SD（n=1 时为空并说明）
    comparisons         JSON,                  -- 每个比较（sota/parent）：配对数、每个指标的效应、gate 与保护指标
    verdict             TEXT,                  -- 兼容期调用者给出的判定（经核对；新流程可为空）
    outcome             TEXT CHECK (outcome IN ('positive_signal', 'negative_signal', 'inconclusive', 'invalid')),
                                               -- 确定性结论：主指标相对参照的效应与最小实际收益（06 §2.1）
    outcome_reason      TEXT,
    stage               TEXT CHECK (stage IN ('screen', 'replicate', 'confirm')),
    gate_passed         BOOLEAN,               -- 与 SOTA 比较：配对数达标且主指标效应超过最小实际收益
    guardrails_passed   BOOLEAN,               -- 有 allowed_regression 的指标都没有超额退化
    eval_type           TEXT CHECK (eval_type IN (
                            'real_gt', 'synthetic_proxy', 'self_supervised_proxy', 'simulation_only', 'human_eval'
                        )),
    limitations         TEXT_LIST,
    verification_level  TEXT NOT NULL CHECK (verification_level IN (
                            'record_recomputed',   -- 从登记的 run 数值重算
                            'artifact_imported',   -- 全部 run 经 manifest 与冻结解析器导入
                            'legacy_unverified'    -- 没有指标规范的旧项目：只能查看，不支持新规则下的 GO
                        )),
    artifact_refs       TEXT_LIST,
    statistics_version  TEXT NOT NULL,
    parser_version      TEXT,
    inputs_digest       TEXT NOT NULL,         -- 输入与依据（run、参照、代码、框架、协议、规范）的摘要
    fingerprint         TEXT NOT NULL,         -- inputs_digest 加判定与结果文档；相同的重复计算返回同一条记录
    supersedes_evaluation_id TEXT,
    migrated            BOOLEAN,               -- 由 migrate_evaluations 为旧判定补记：只作历史，不支持新规则下的 GO
    created_by          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

-- 预算预留（05 §4）：一条对应一个实际可计费的调度分配；记账状态受约束更新
CREATE TABLE reservation (
    id                  TEXT PRIMARY KEY,      -- 例：RS-0004
    project_id          TEXT NOT NULL,
    submission_key      TEXT NOT NULL,         -- 项目内唯一的提交身份；同一 key 再次预留返回同一条
    run_attempt_refs    TEXT_LIST NOT NULL,    -- 这次分配运行的 run 与 attempt（一个作业可跑多个 seed）
    budget_pool         TEXT NOT NULL CHECK (budget_pool IN ('search', 'confirmation', 'repair')),
    resource_class      TEXT NOT NULL,         -- 资源类别；初版只有 node（node-seconds）
    reserved_units      INTEGER NOT NULL,      -- 申请资源 × walltime 上限，向上取整
    actual_units        INTEGER,               -- 结算的实际用量；可超过预留（如实记录）
    accounting_status   TEXT NOT NULL CHECK (accounting_status IN ('reserved', 'held_unknown', 'settled', 'released')),
    submission_phase    TEXT NOT NULL CHECK (submission_phase IN ('intent', 'claimed', 'attached')),
    claim_generation    INTEGER NOT NULL DEFAULT 0,  -- 领取次数；只有最新一次领取的执行者能写回作业
    job_id              TEXT,
    platform_profile    TEXT,
    accounting_ref      TEXT,                  -- 结算依据（调度器用量文件），相对研究根目录
    accounting_sha256   TEXT,
    overrun             BOOLEAN,               -- 实际用量超过预留或剩余预算
    note                TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    settled_at          TEXT
);

-- 未决问题账本（06 §6）：复核发现、STAT_MISMATCH、协议不匹配、代码审查 CRITICAL 等；只追加
CREATE TABLE obligation (
    id                  TEXT PRIMARY KEY,      -- 例：OB-0003
    about               TEXT NOT NULL,         -- 节点、实验或 evaluation 的 ID
    source              TEXT NOT NULL,         -- 来源：review 文档 ID 或错误码
    pattern             TEXT NOT NULL,         -- 来源内的问题类别
    fingerprint         TEXT NOT NULL,         -- 来源类别 + 模式 + 证据片段的摘要；同一指纹再次出现不新增
    severity            TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'MAJOR', 'MINOR')),  -- 只升不降
    status              TEXT NOT NULL CHECK (status IN ('OPEN', 'RESOLVED', 'WAIVED')),
    claim               TEXT NOT NULL,
    evidence_excerpt    TEXT,
    history             JSON,                  -- 升级、重开、消失与重现的记录
    resolution          JSON,                  -- RESOLVED：修复类型、证据文件与哈希、核验者
    waiver              JSON,                  -- WAIVED：用户指令文档
    disappearance       JSON,                  -- 从后续报告中消失（UNRESOLVED_DISAPPEARANCE），仍为 OPEN
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- 文档索引：正文在文档库，库中只存定位与摘要
CREATE TABLE document (
    id                  TEXT PRIMARY KEY,      -- 例：D-0120
    path                TEXT NOT NULL,         -- 相对文档库根的路径
    version             INTEGER NOT NULL,      -- 被引用后不原地修改，改动写新版本
    doc_type            TEXT NOT NULL CHECK (doc_type IN (
                            'goal', 'min_setup', 'hypothesis',
                            'novelty', 'theory', 'literature',
                            'experiment_design', 'experiment_result',
                            'decision',
                            'user_instruction', 'task_request', 'task_delivery',
                            'workflow', 'report', 'config',
                            'protocol', 'metric_spec',
                            'review',          -- 跨模型非交互评审（review_call.py，作者只能是 reviewer）
                            'finding',         -- 研究发现（08 §1.1：事实与解释分开，带证据与局限）
                            'lesson',          -- 运行经验（08 §1.2：症状、根因与状态、已验证的修复、适用范围、反例）
                            'other'
                        )),
    title               TEXT NOT NULL,
    summary             TEXT,                  -- ≤ 300 字的摘要，供消息引用和 HTML 预览
    status              TEXT NOT NULL CHECK (status IN (
                            'draft',           -- 草稿
                            'current',         -- 现行有效（用户指令：生效中）
                            'superseded'       -- 已被新版本或新指令取代
                        )),
    author_role         TEXT NOT NULL CHECK (author_role IN (
                            'user', 'ui', 'rld', 'worker', 'assistant', 'web_builder', 'reviewer'
                        )),
    author_id           TEXT NOT NULL,
    sha256              TEXT,
    review_kind         TEXT,                  -- review：triage、novelty_precheck、critical_review、proposal_review、ablation_plan、code_review、candidate_recheck
    review_result       TEXT,                  -- review：kind 的结论（candidate_recheck 的 pass/fail/uncertain/not_applicable，novelty 的 verdict 等）
    review_dimension    TEXT,                  -- candidate_recheck：numbers、protocol、method_code、novelty、theory
    review_backend      TEXT,                  -- pi | claude_code
    reviewer_model      TEXT,                  -- observed 的 provider/model
    basis_evaluation_id TEXT,                  -- candidate_recheck 所复核的 evaluation
    basis_code_ref      TEXT,                  -- 该 evaluation 的代码版本（只核实现的维度按它复用）
    review_session      TEXT,                  -- 评审会话（RV-编号）；同会话续接写新版本
    review_about        TEXT,                  -- 评审对象不是数据库实体时（发现阶段的候选 CAND-编号）
    created_at          TEXT NOT NULL
);

-- 决定：所有节点状态、维度状态、优先级和项目状态变更的追加式审计记录
CREATE TABLE decision (
    id                  TEXT PRIMARY KEY,      -- 例：DEC-0210
    target_id           TEXT NOT NULL,         -- hypothesis、project 或 branch；edge: DECIDES
    field               TEXT NOT NULL CHECK (field IN (
                            'status', 'experiment_status', 'novelty_recheck',
                            'theory_recheck', 'priority', 'project_status',
                            'branch_status', 'run_validity', 'disposition', 'findings'
                        )),
    from_value          TEXT,
    to_value            TEXT NOT NULL,
    reason              TEXT NOT NULL,         -- 一句话理由
    doc_id              TEXT,                  -- 详细理由文档（节点状态和项目状态变更必填）
    decided_by          TEXT NOT NULL,         -- RLD 身份；用户指令导致的变更另用 rel_based_on 指向指令文档
    decided_at          TEXT NOT NULL
    -- 依据的 experiment/document 用 rel_based_on 记录
);

-- 委派任务：agent 之间的工作单元；消息只引用 task 与文档
CREATE TABLE task (
    id                  TEXT PRIMARY KEY,      -- 例：T-0088
    kind                TEXT NOT NULL CHECK (kind IN (
                            'harness', 'literature', 'experiment',
                            'analysis', 'web_build', 'cleanup', 'other'
                        )),
    target_id           TEXT,                  -- hypothesis、project（根节点）或 experiment；edge: FOR
    status              TEXT NOT NULL CHECK (status IN (
                            'open', 'in_progress', 'delivered',
                            'accepted', 'rejected', 'cancelled'
                        )),
    assignee_role       TEXT NOT NULL CHECK (assignee_role IN (
                            'worker', 'assistant', 'web_builder'
                        )),
    assignee_id         TEXT,
    request_doc_id      TEXT NOT NULL,         -- 委派说明文档
    delivery_doc_id     TEXT,                  -- 交付文档
    accepted_by         TEXT,                  -- 验收者（不能是 assignee）
    accepted_evidence   TEXT_LIST,             -- 验收依据：evaluation、决定或文档 ID（plans/design 13 §2.1 accept）
    failure_log         JSON,                  -- 失败预算（03 §8）：{entries: [{root_cause, remedy: patch|rewrite|blocked, by, at}]}
    blocked_reason      TEXT,                  -- 两次重写仍同样失败：任务阻塞，待 RLD 决定（unblock_task）
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 多值关系（边类型）。source/target 为节点 id；其余列为边属性。
-- ---------------------------------------------------------------------------

-- 实验与父节点/SOTA 的配对比较，由冻结统计代码计算、随判定一起写入
CREATE TABLE rel_compared_with (               -- edge: COMPARED_WITH（experiment → experiment）
    source_id           TEXT NOT NULL,         -- 被测实验
    target_id           TEXT NOT NULL,         -- 父节点最新已判定实验，或 SOTA 实验
    role                TEXT NOT NULL CHECK (role IN ('parent', 'sota')),
    n_paired            INTEGER NOT NULL,      -- 同 seed 配对数 = 两个实验 seed 的交集大小
    delta_mean          REAL NOT NULL,         -- 主指标的效应，按优劣方向折算，正值 = 更好；按指标规范为规范单位的
                                               -- 配对差均值，或相对参照均值的比例（旧项目：百分点差或相对百分比差）
    delta_sd            REAL,
    deltas              JSON NOT NULL,         -- 其他指标的配对差均值（同样正值 = 更好），键 = secondary_metrics
    passes_gate         BOOLEAN,               -- 接口计算：role='sota' 时 n_paired >= gate_seeds（或协议 min_pairs）且
                                               -- 主指标效应超过 minimum_practical_gain（比较方式由协议定）
    PRIMARY KEY (source_id, target_id, role)
);

-- 执行依赖：复用父实验的产物（权重、缓存等）
CREATE TABLE rel_depends_on (                  -- edge: DEPENDS_ON（experiment → experiment）
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    artifact            TEXT,                  -- 依赖的产物说明或路径
    PRIMARY KEY (source_id, target_id)
);

-- 创建节点时参考的相关研究（缓存的 literature 文档）
CREATE TABLE rel_references (                  -- edge: REFERENCES（hypothesis → document）
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

-- 节点间非父子关系
CREATE TABLE rel_related (                     -- edge: RELATED（hypothesis → hypothesis）
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN (
                            'competes',        -- 竞争解释
                            'shares_control',  -- 共享对照
                            'variant_of'       -- 同一想法的变体（非派生）
                        )),
    PRIMARY KEY (source_id, target_id, kind)
);

-- 上述 *_doc_id 之外的补充文档（文献笔记、讨论、附加分析等）与所描述对象的关系
CREATE TABLE rel_describes (                   -- edge: DESCRIBES（document → 任意节点）
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

-- 文档版本链
CREATE TABLE rel_supersedes (                  -- edge: SUPERSEDES（新 document → 旧 document）
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

-- 决定的依据
CREATE TABLE rel_based_on (                    -- edge: BASED_ON（decision → experiment/document/evaluation）
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

-- ---------------------------------------------------------------------------
-- 索引（LatticeDB 属性索引 / 全文索引）
-- ---------------------------------------------------------------------------
-- 属性索引：所有 label 的 id；evaluation.fingerprint；hypothesis.status、hypothesis.project_id、
--           experiment.project_id、experiment.verdict、document.path、task.status、
--           branch.status
--           （以边保存的关系通过边遍历查询，不建属性索引）
-- 全文索引：hypothesis.statement、document.summary
