# Runtime 概念

本文档是 Runtime 的详细学习和面试手册。

每个概念使用以下模板：

```markdown
## <概念 / 模块>

### 解决什么问题

### 核心概念

### 当前 runtime 实现

### 输入 / 输出 / 不负责什么

### 常见失败模式

### 如何测试和观察

### 面试解释

### 延伸学习
- 官方文档
- 框架文档
- 项目文件
```

## 必需章节

- Agent Loop
- Intent Layer
- Policy / Permission Layer
- Tool System
- Capability
- Write Safety
- LangGraph Orchestrator
- LangChain Adapter
- Planner
- Executor
- Task State
- Task vs Plan
- Context Engine
- Memory
- Recovery
- MCP
- Calendar External Tool
- DAG Scheduler
- Eval Harness
- Inspector / Debugger
- Observability
- SQLite Local Persistence

## 官方参考

LangGraph 和 LangChain：

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph low-level concepts: https://langchain-ai.github.io/langgraph/concepts/low_level/
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangChain overview: https://docs.langchain.com/oss/python/langchain/overview
- LangChain tools: https://docs.langchain.com/oss/python/langchain/tools

MCP：

- MCP introduction: https://modelcontextprotocol.io/docs/getting-started/intro
- MCP specification: https://modelcontextprotocol.io/specification
- MCP tools: https://modelcontextprotocol.io/docs/concepts/tools
- MCP resources: https://modelcontextprotocol.io/docs/concepts/resources

当前 runtime 项目参考：

- `plans/RUNTIME_REFACTOR_PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/MIGRATION_INDEX.md`
