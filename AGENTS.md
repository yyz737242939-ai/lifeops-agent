# AGENTS.md

## 仓库协作约定

- 本仓库既是 Agent Runtime 机制学习项目，也是 LifeOps 个人生活管理产品的早期版本。
- 开始规划或修改前，先阅读 `PROJECT_CONTEXT.md` 了解当前事实，再阅读 `LEARNING_PROGRESS.md` 了解当前学习主线和下一步。
- 本文件保持简洁。稳定的项目事实写入 `PROJECT_CONTEXT.md`，未来的学习计划和推进顺序写入 `LEARNING_PROGRESS.md`。
- `LEARNING_PROGRESS.md`随着项目的推进以及计划内的功能实现，可以被实时更改。将实现的计划目标删掉，并添加到`PROJECT_CONTEXT.md`。
- `PROJECT_CONTEXT.md`用于快速了解项目架构以及记录项目的重要功能推进全过程，是后续生成学习报告的历史参考资料，因此要尽可能的把重点全标明出来
- 一般来说，当用户下达指令开始做某一个功能的时候，更新完代码后相应的功能就需要记录到`PROJECT_CONTEXT.md`
- 重要的阶段更新需写进CHANGELOG.md，具体格式参考文件本身。这里的阶段更新比`PROJECT_CONTEXT.md`中的功能实现要更大
- 所有重要学习内容、关键设计理解、实现变更和验证结果都需要留下记录。这些记录未来会被整理成一份 Agent 学习报告，用来囊括学习过程中的知识点并服务于面试复盘；当前阶段只需要持续、准确地记录，不需要提前整理成报告正文。
- 本仓库的 Markdown 文件使用 UTF-8 编码。

## 项目背景

- LifeOps Agent 的长期方向是成为真实可用的个人生活管理 Agent。
- 这个项目也承担学习目的：通过亲自实现关键 Runtime 机制，理解 Agent 如何处理工具、上下文、状态、副作用、安全和可靠性。
- 产品目标和学习目标应互相强化。优先选择能让助手更安全、更可观察、更可恢复、更适合真实用户数据的设计。
- 教学和实现代码应主动参考成熟、热门的 Agent 框架、产品和开源项目，例如 OpenClaw、Claude Code、OpenHands、LangGraph 等；优先学习其 Runtime 边界、工具执行、上下文管理、权限控制、可观测性和恢复机制。对非开源或无法直接验证源码的产品，只参考公开文档、公开行为和可复现实验，不臆测内部实现。

## 常用命令

```powershell
# 运行 Agent
uv run python main.py

# 查看日志
uv run python log_viewer.py

# 运行测试
uv run python -m unittest discover -s tests -v
```

## 工程规则

- 优先做小而可观察的改动，避免大范围重写。
- 用户数据安全优先。任何业务写入都必须来自用户当前输入的明确授权。
- 不要只凭模型文本判断成功。Runtime 状态和成功的 WRITE Action 才是“已保存/已修改”的事实来源。
- 保持 Skill、Tool、Capability、Context、Runtime State 和业务 Memory 的边界清晰。
- 借鉴外部成熟项目时，先提炼其核心机制和适用原因，再按本仓库当前阶段做小规模、可解释的实现；避免为了“像某个框架”而引入过大的抽象、依赖或平台化复杂度。
- 修改 Runtime 行为、Context 处理、写入安全或工具执行时，添加或更新聚焦的回归测试。
- 不确定当前范围时，以 `PROJECT_CONTEXT.md` 和 `LEARNING_PROGRESS.md` 为准；不要把阶段性计划写死在本文件中。

## 完成标准

- 已实现用户请求的行为，或清楚说明阻塞点。
- 已运行相关测试或检查；如果没有运行，需要说明原因。
- 当行为、架构、命令、当前学习计划、关键学习结论或实现取舍发生变化时，同步更新文档，确保后续可追溯到“学到了什么、为什么这样改、验证结果是什么”。
