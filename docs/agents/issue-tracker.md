# Issue Tracker：GitHub

本仓库的 issue 和 PRD 存放在 GitHub Issues 中。使用 `gh` CLI 处理 issue 操作。

PR 也作为请求入口：是。外部 PR 可以使用与 issue 相同的 triage 标签和状态。

当 skill 要求“publish to the issue tracker”时，创建 GitHub issue。
当 skill 要求“fetch the relevant ticket”时，运行 `gh issue view <number> --comments`。

需要时使用 `git remote -v` 推断 GitHub 仓库。
