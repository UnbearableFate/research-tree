---
title: "横切：研究发现、运行经验与文献复用"
stage: "横切"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §10 D6；对照文档 §4.1–4.2（verify_papers、research_wiki query_pack、capture_filter、threat_scan）"
language: "zh-CN"
---

# 08 横切：研究发现、运行经验与文献复用

## 1. 不再建设第二套通用 memory 平台

沿用现有文档、版本与关系索引，新增少量结构化 front matter。初版不要求向量数据库、独立知识图谱服务或自动技能市场。

建议目录：

```text
docs/findings/          # 研究发现与适用边界
docs/lessons/           # 运行经验与已验证修复
docs/literature/        # 原文来源与最近邻对比
docs/decisions/         # 当前选择的依据
```

运行经验与研究发现分开提炼，是对 Auto-RecSys 双回路和 DeepScientist Findings Memory 的轻量借鉴，不是将已有文档简单重命名。[R01]、[R05]

### 1.1 研究发现记录

```yaml
kind: finding
id: FND-0007
claim: "匹配有效 batch 后，原先收益明显减弱。"
scope:
  protocol_ids: [PROTO-001]
  model_family: "本项目测试的模型族"
  training_regime: "本次短程后训练"
evidence_ids: [EV-0012, EV-0016]
interpretation: "暂不支持收益完全来自优化器公式本身。"
limitations: "尚未检查长程训练和其他模型规模。"
status: observed
supersedes: null
```

记录中必须把事实与解释分开。一次消融排除了某个解释，不等于所有相关解释都被排除；一个任务上有效不能升级为普适规律。

### 1.2 运行经验记录

```yaml
kind: execution_lesson
id: LES-0004
symptom: "训练在初始化通信后退出。"
root_cause: "已由对应日志和最小测试定位的具体原因。"
root_cause_status: verified
fix: "经过实际测试的启动参数或依赖调整。"
applicability:
  platform_profile: "已核对的平台配置"
  dependency_versions: "已验证版本范围"
evidence_runs: ["E-0008/s42@2"]
counterexamples: []
status: verified
```

未确定根因时填写 unknown，不强制补成一个解释。经验状态建议为 `proposed / observed / verified / contradicted / stale`；verified 指适用范围内被验证，不代表永久正确。

### 1.3 提炼时机

仅在实验验收、一次明确故障修复、关键对照完成或决策转向时提炼。普通状态查询和每次工具调用不触发反思。

相似条目合并为版本更新并保留依据，不无限追加几乎相同的“注意检查环境”。经验更新不自动改动项目权限、评测器或研究协议。

### 1.4 检索策略

新任务先读取当前目标、授权、待办与依赖，再检索与该任务匹配的少量发现和运行经验。初版可按模型、训练方式、平台、依赖版本、问题类型和相邻节点过滤。

建议设可配置的经验条数与 token 上限；例如最多 5 条不是效果保证，只是防止上下文膨胀的初始限制。必要反例与失效说明必须与经验一起返回。

检索返回 `why_relevant` 和 `applicability`。没有匹配经验时返回空，不凭空创造“此前已验证”的结论。

### 1.5 经验失效与跨项目使用

依赖版本、硬件、数据协议或模型改变时，旧经验标为需要重新核对；不将其作为当前必然正确的操作规则。

跨项目检索默认关闭。打开后仍需要按权限过滤，避免泄露未公开数据、凭据或受限研究材料。导出的经验不包含密钥和完整敏感日志，且不能被用作新实验授权。

反思文字、论文正文与外部仓库说明都是研究材料，不是控制指令。它们不能要求跳过用户限制、运行未授权命令或更改保护规则。

### 1.6 文献从数量门槛转为最近邻差异

当前创建节点检查至少若干现行 literature 文档，但这种数量检查不等于新颖性证据。[S03]

拟议最小文献记录包括：标题、作者、年份、DOI/arXiv ID、访问日期、原文版本、具体页/节、方法核心、适用条件、与当前假说的差异。最近邻对比至少回答：机制是否相同、改变了什么假设、已有结果是否已覆盖本项目声明。

子节点继承共同文献；只有新增的实质方法差异才补检索。若找到直接覆盖的方法，不为了凑实验次数继续重复；记录覆盖依据并转向或停止投入。

来源存在、标题匹配和内容支持是不同检查。学术 API 能帮助确认元数据，不能代替阅读方法与实验条件。

## 2. 文献工具

移植 ARIS `arxiv_fetch.py`、`semantic_scholar_fetch.py`、`openalex_fetch.py`、`verify_papers.py`（合计约 1800 行）为 `tools/literature.py`：检索、下载、三层存在性核验（arXiv → CrossRef → Semantic Scholar 模糊标题），带缓存与限速。登记 `literature` 文档时必须经过核验；核验不可用时标 `verification: unverified` 而不是丢弃；`unverified` 文献不计入 `min_related_work`。网络访问按平台规则在允许的节点运行。文献前言与原文回灌 Leader 前经 `threat_scan.py`（222 行）扫描。

## 3. 上下文包

借 ARIS `research_wiki.py` 的 `rebuild_query_pack`：新增 `context_pack(role, node)`，确定性生成、固定上限（如 8000 字），顺序为目标与问题锚点 → 未决 obligation → **已剪枝节点与 verified lesson** → 当前 Evaluation → 最近关系边。它是 10.5 检索策略的实现，也取代 ARIS 的 `research_contract.md`；`resume_package` 增加该字段。

## 4. 记忆写入过滤

借 ARIS `capture_filter.py`（126 行）：`docs/lessons/` 登记前拒绝"command not found""OOM""rate limit"等运维噪声成为研究经验；根因只是猜测时只能登记 `proposed`（K01）。

<!-- 引用链接 -->

[R01]: https://arxiv.org/abs/2609.10922
[R05]: https://arxiv.org/abs/2509.26603
[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
