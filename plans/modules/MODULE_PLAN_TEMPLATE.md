# <模块> 模块计划

## 1. 目标

本模块解决 Runtime 中的什么问题。

## 2. 当前 V0 参考

旧实现在哪里，哪些可以复用，哪些不应该继续带入。

## 3. 当前范围

初版做什么、不做什么，以及哪些延后到后续版本。

## 4. Runtime 边界

输入、输出、依赖，以及本模块明确不负责的职责。

## 5. 数据模型 / 存储

本模块需要的数据存放在哪里：SQLite 表、repository、JSON / JSONL 文件、普通日志文件、fixture、migration 或 request-local 状态。只有业务事实或适合关系查询的数据才默认进入 SQLite。

## 6. 对外接口

暴露给其他模块的类型、函数、service、tool 或 CLI 命令。

## 7. 失败模式

预期错误、权限问题、恢复行为，以及需要写入 event JSONL、LLM JSONL 或 normal application log 的内容。

## 8. 测试和 Eval

单元测试、集成测试、eval 场景，以及 event / LLM / normal log 的验证点。

## 9. 文档更新

需要更新 `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md`、`docs/RUNTIME_CONCEPTS.md` 和 `docs/AGENT_LEARNING_LINKS.md` 的哪些内容。

如果本模块包含新的核心 Agent 概念或重要学习点，需要先列出准备沉淀的重点方向并向用户确认；确认后再同步更新 `docs/AGENT_LEARNING_LINKS.md`，补充权威官方文档、specification 或高质量官方博客链接。`docs/RUNTIME_CONCEPTS.md` 只写本项目解释和面试讲法，不直接维护外部链接。若不需要新增链接，应在模块计划或收口说明中明确说明。

## 10. 实施步骤

按执行顺序拆分的小实施步骤。
