1. 使用`codegraph`的能力获取代码库知识, 并使用`codegraph sync`保持更新
2. 自行管理git仓库状态
3. 实施 `plans/research-tree-implementation-and-real-scenarios.md` 时，每个阶段末 Claude Code（claude-haiku-5-5，effort medium）与 Codex（gpt-6-luna，reasoning medium；以实施文档 §2.2 模型矩阵为准）都必须在全新虚构项目中运行该阶段的真实场景；阶段评审与终审用 claude-fable-5-1 high 新会话（`scripts/stage_review.py`）。正常场景使用真实测量，替身与预设数值只用于 REG。
