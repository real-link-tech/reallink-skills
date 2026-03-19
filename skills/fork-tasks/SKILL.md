---
name: fork-tasks
description: "Multi-session task coordination. TRIGGER when user wants to: split/fork work into parallel sub-tasks, start working on an assigned sub-task, finish/complete a sub-task, collect/gather results from sub-tasks, share/export findings to another session, or import/inject/load context from another session. Also trigger when user says things like: '拆成几个任务并行做', '把这个结论分享给另一个会话', '读一下另一个会话的结论', '汇总子任务结果', '接一下这个任务'. Sub-commands: fork, pickup, complete, collect, share, inject"
user-invocable: true
args: "[subcommand] [args...]"
---

# Fork Tasks Skill

多会话任务协调。根据第一个参数判断子命令：

| 调用方式 | 子命令 | 功能 |
|----------|--------|------|
| `/fork-tasks` | **fork** (默认) | 拆分任务、启动子会话 |
| `/fork-tasks pickup <task-path>` | **pickup** | 接收并开始子任务 |
| `/fork-tasks complete [task-path]` | **complete** | 提交子任务结论 |
| `/fork-tasks collect [session-name]` | **collect** | 汇总所有子任务结果 |
| `/fork-tasks share [name]` | **share** | 导出当前会话发现供其他会话使用 |
| `/fork-tasks inject <name-or-path>` | **inject** | 注入其他会话的共享上下文 |

如果参数不匹配任何子命令，提示用户可用的子命令列表。

---

## 状态管理

**status 文件是唯一的状态来源（single source of truth）**。

- 每个子任务的状态存储在 `tasks/<task-id>/status` 文件中，内容为 `pending`、`in_progress` 或 `done`
- `manifest.json` 仅作为会话级元数据（session name、created time、task 列表），**不存储任务状态**
- 需要检查任务状态时，始终读取 status 文件
- session 级状态（active/completed）仍存在 manifest.json 中

---

## Sub-command: fork (默认)

拆分当前任务为多个子任务，启动并行子会话。

### 流程

1. **确定子任务**：询问用户要拆成哪些子任务，或根据当前对话上下文建议拆分方案。

2. **创建 Session 名称**：格式 `<slug>-<YYYY-MM-DD>`（如 `auth-refactor-2026-03-18`），确认后使用。

3. **提取共享上下文**：总结当前对话的关键发现，写入 `context.md`。

4. **创建文件结构**，位于 `.claude/fork-tasks/<session>/`：

```
manifest.json          — 会话元数据（不含任务状态）
context.md             — 共享上下文
tasks/
  01-<slug>/
    task.md            — 子任务描述
    status             — "pending"
  02-<slug>/
    ...
```

**manifest.json**（注意：不含 task status 字段）：
```json
{
  "session": "<session-name>",
  "created": "<ISO timestamp>",
  "status": "active",
  "tasks": [
    { "id": "01-<slug>", "title": "<title>" },
    { "id": "02-<slug>", "title": "<title>" }
  ]
}
```

**task.md**：
```markdown
# Task: <title>

## Objective
<目标>

## Context
<任务专属上下文>

## Relevant Files
- <相关文件路径>

## Acceptance Criteria
- <完成标准>

## Notes
<补充说明>
```

5. **启动子会话**：为每个子任务生成 `.ps1` 启动脚本并执行。

启动脚本模板：

**重要**：不要在 prompt 中内联展开 context.md 和 task.md 的内容！PowerShell here-string `@"..."@` 会展开变量，将完整文件内容塞入命令行参数，极易超出长度限制导致截断。正确做法是用短 prompt 让子会话自己读取文件。

```powershell
$taskPath = ".claude/fork-tasks/<session>/tasks/<task-id>"
Set-Content "$taskPath/status" "in_progress" -NoNewline

$prompt = @"
你正在执行一个 fork 子任务。请先读取以下两个文件获取上下文和任务描述：

1. .claude/fork-tasks/<session>/context.md（共享上下文）
2. .claude/fork-tasks/<session>/tasks/<task-id>/task.md（你的任务）

<对任务的一句话概述>。用中文讨论。完成后执行 /fork-tasks complete $taskPath
"@

cd <project-dir>
claude $prompt
```

保存到 `.claude/fork-tasks/<session>/launch-<task-id>.ps1`，然后启动：
```bash
powershell -Command "Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', '<script-path>'"
```

6. **报告**：输出 session 名称、子任务列表，提醒用户子会话完成后执行 `/fork-tasks collect <session-name>`。

---

## Sub-command: pickup <task-path>

在子会话中接收并开始一个子任务。

**参数**：`<task-path>` — 子任务目录路径（如 `.claude/fork-tasks/auth-refactor-2026-03-18/tasks/01-review-endpoints`）。未提供则询问。

### 流程

1. **读取任务文件**：
   - `<task-path>/task.md` — 任务描述
   - 从 `<task-path>` 向上查找同级的 `context.md`（遍历父目录直到找到，不依赖固定层级）
   - `<task-path>/status` — 如果是 `done`，告知用户并询问是否重做

2. **更新状态**：写 `in_progress` 到 `<task-path>/status`。

3. **展示任务**：输出标题、目标、上下文、相关文件、完成标准。

4. **开始工作**。

5. **完成提示**：工作完成时提醒用户执行 `/fork-tasks complete <task-path>`。

---

## Sub-command: complete [task-path]

完成子任务，写入结构化结论。

**参数**：`[task-path]`（可选）。未提供则扫描 `.claude/fork-tasks/*/tasks/*/status` 查找 `in_progress` 的任务。找到一个直接用，多个则询问。

### 流程

1. **定位任务**。

2. **总结工作**：回顾对话，提取结论、修改文件、决策、遗留问题。

3. **写 result.md** 到 `<task-path>/result.md`：

```markdown
# Result: <task title>

## Status
Completed on <date/time>

## Summary
<1-3 段总结>

## Key Conclusions
- <结论>

## Files Modified
- `<path>` — <改了什么>

## Key Decisions
- **<决策>**: <原因>

## Remaining Issues
- <遗留问题，或 "None">
```

4. **更新状态**：写 `done` 到 `<task-path>/status`。

5. **通知**：告诉用户任务完成，回主会话执行 `/fork-tasks collect <session-name>`。

---

## Sub-command: collect [session-name]

汇总所有子任务结果。

**参数**：`[session-name]`（可选）。未提供则扫描 `.claude/fork-tasks/` 查找 `"status": "active"` 的 session。找到一个直接用，多个则询问。

### 流程

1. **定位 Session**：读取 `manifest.json`，获取任务列表。

2. **检查状态**：读取每个任务的 `status` 文件。如有未完成的，警告用户并询问是否继续。

3. **读取结果**：读取所有 `done` 任务的 `result.md`。如果某个 `done` 任务缺少 result.md，标记为错误。

4. **输出汇总到对话**（不写文件，直接输出）：

```
# Fork Session Summary: <session-name>

## Overview
共 <N> 个子任务，<M> 完成，<K> 未完成。

## Task Results
### <task-id>: <title>
<summary, conclusions, files, decisions>
---
...

## Cross-Task Analysis
### All Modified Files
<去重列表>
### Potential Conflicts
<被多个子任务修改的文件>
### Consolidated Remaining Issues
<合并的遗留问题>

## Next Steps
<建议的后续动作>
```

5. **清理**：如果所有任务都 `done`，将 `manifest.json` 的 status 设为 `"completed"`，然后删除整个 session 目录。

---

## Sub-command: share [name]

导出当前会话的关键发现到共享文件。默认导出所有重要内容，不询问"想分享什么"。

**参数**：`[name]`（可选）— 简短标签（如 `api-analysis`）。未提供则询问名称。

### 流程

1. **总结当前对话**：提取关键发现、相关文件、决策、代码片段、未解决问题。

2. **写入共享文件** `.claude/fork-tasks/shared/<name>.md`：

```markdown
# Shared Context: <name>

Exported: <date/time>
Source session: <会话简述>

## Key Findings
- <发现>

## Relevant Files
- `<path>` — <为什么相关>

## Decisions Made
- **<决策>**: <原因>

## Code Snippets
<重要代码片段>

## Open Questions
<未解决的问题>
```

3. **报告**：输出文件路径，告诉用户在其他会话中执行 `/fork-tasks inject <name>`。

### 注意
- 如果 `<name>.md` 已存在，询问覆盖还是换名
- 要详尽——接收方会话对这个对话零上下文
- 如果参数包含 `.md` 后缀，自动去掉（统一用 bare name）

---

## Sub-command: inject <name-or-path>

导入其他会话的共享上下文到当前对话。

**参数**：`<name-or-path>`：
- 不含 `/` 的 bare name（如 `api-analysis`，有无 `.md` 后缀均可）→ 解析为 `.claude/fork-tasks/shared/<name>.md`
- 含 `/` 的路径 → 直接使用

未提供参数则列出 `.claude/fork-tasks/shared/` 中所有文件供选择。

### 流程

1. **解析文件路径**。文件不存在则列出可用的 shared contexts。

2. **读取文件**。

3. **输出到对话**（关键：必须 print 到对话中，不能只是静默读取）：

   > **Injected context from `<name>`:**
   >
   > <完整文件内容>

4. **确认**：简要说明注入了什么。

### 注意
- 超过 200 行的文件先总结，问用户要全文还是摘要
- 注入后 shared 文件保留不删

---

## 自动清理规则

每次任意子命令执行前，静默执行清理：

- 删除 `manifest.json` 中 `"status": "completed"` 的 session 目录
- 删除 `.claude/fork-tasks/shared/` 中 `Exported:` 日期超过 7 天的文件
- **不动**：`active` 状态的 session、`in_progress`/`pending` 的 task
- `collect` 完成后立即删除整个 session 目录（内容已输出到对话）
- `inject` 后不删 shared 文件（可能多个会话需要）
- 清理失败静默跳过，不影响主命令
- `manifest.json` 解析失败时跳过该 session，不删不改
