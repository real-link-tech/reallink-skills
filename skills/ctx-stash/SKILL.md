---
name: ctx-stash
description: "Context clipboard — save and load conversation context across sessions. TRIGGER when user wants to: save/stash current context, load/restore context from another session, list saved contexts, or clean up old contexts. Also trigger for: '保存上下文', '加载上下文', '存一下当前进展', '读取之前的结论'. Sub-commands: save, load, list, rm"
user-invocable: true
args: "[subcommand] [args...]"
---

# ctx-stash — 上下文剪贴板

轻量的跨会话上下文存取。随时存、随时取、自动清理。

## 命令

| 命令 | 缩写 | 功能 |
|------|------|------|
| `/ctx-stash save [name]` | `/ctx-stash s [name]` | 存当前上下文 |
| `/ctx-stash load <id\|name>` | `/ctx-stash l <id\|name>` | 注入上下文到当前会话 |
| `/ctx-stash list` | `/ctx-stash ls` | 列出所有已存上下文 |
| `/ctx-stash rm <id\|name>` | `/ctx-stash d <id\|name>` | 删除指定上下文 |

无参数调用 `/ctx-stash` 等同于 `list`。

解析第一个参数判断子命令（支持缩写）：
- `s` / `save` → save
- `l` / `load` → load
- `ls` / `list` → list
- `d` / `rm` / `delete` / `remove` → rm
- 纯数字（如 `3`）→ 视为 `load 3`
- 无参数 → list

---

## 存储结构

存储目录：`.claude/skills/ctx-stash/stashes/`（skill 内部）

每个上下文是一个 `.md` 文件，文件名格式 `<id>-<name>.md`：

```
.claude/skills/ctx-stash/stashes/
  1-auth-analysis.md
  2-api-review.md
  3-bug-investigation.md
```

文件内容使用 frontmatter 存元数据：

```markdown
---
id: 1
name: auth-analysis
created: 2026-03-19T10:30:00
accessed: 2026-03-19T14:00:00
mode: summary
---

<上下文内容>
```

字段说明：
- `id`: 自增数字，用于快速引用
- `name`: 短标签，用于语义引用
- `created`: 创建时间
- `accessed`: 上次 load 时间，驱动自动清理
- `mode`: `full`（原样详尽导出）或 `summary`（AI 总结精华）

---

## 自动清理（每次命令执行前）

**在执行任何子命令之前**，先静默扫描 `.claude/skills/ctx-stash/stashes/` 下所有 `.md` 文件：

1. 读取每个文件的 frontmatter 中的 `accessed` 字段
2. 如果 `accessed` 距今超过 **7 天**，删除该文件
3. 清理失败静默跳过，不影响主命令
4. 清理后不重新编号（ID 可能有空洞，这是预期行为）

实现方式：
- 用 Glob 工具列出 `.claude/skills/ctx-stash/stashes/*.md`
- 逐个读取 frontmatter，解析 `accessed` 日期
- 用 Bash `date` 命令计算天数差，或直接在脑中计算日期差
- 超期则用 Bash `rm` 删除

---

## 快捷引用规则

load 和 rm 的参数解析规则（按优先级）：

1. **纯数字**：`/ctx-stash l 3` → 匹配 `id: 3` 的文件
2. **名称精确匹配**：`/ctx-stash l auth-analysis` → 匹配 `name: auth-analysis`
3. **名称前缀匹配**：`/ctx-stash l auth` → 匹配第一个 `name` 以 `auth` 开头的文件
4. **找不到**：列出所有可用上下文供用户选择

---

## Sub-command: save

存当前对话上下文。

### 流程

1. **确定名称**：使用参数中的 name；如未提供，用 AskUserQuestion 询问。名称应为简短英文 slug（如 `auth-analysis`）。

2. **选择模式**：用 AskUserQuestion 询问导出模式：
   - **总结模式**（summary，推荐）：提取关键发现、决策、相关文件、代码片段、未解决问题
   - **完整模式**（full）：详尽记录所有讨论内容、完整代码片段、文件路径、推理过程

3. **生成上下文内容**：回顾当前对话，根据模式生成内容：

   **summary 模式内容结构**：
   ```markdown
   ## Key Findings
   - <关键发现>

   ## Decisions Made
   - **<决策>**: <原因>

   ## Relevant Files
   - `<path>` — <为什么相关>

   ## Code Snippets
   <重要代码片段>

   ## Open Questions
   - <未解决问题>
   ```

   **full 模式内容结构**：
   ```markdown
   ## Discussion Summary
   <完整讨论过程>

   ## All Findings
   - <所有发现，含推理过程>

   ## Files Examined
   - `<path>` — <详细说明>

   ## Complete Code Snippets
   <所有相关代码>

   ## Decisions & Reasoning
   - **<决策>**: <完整推理>

   ## Open Questions
   - <未解决问题>
   ```

4. **分配 ID**：扫描现有文件，取最大 ID + 1（目录为空则从 1 开始）。

5. **写入文件**：创建 `.claude/skills/ctx-stash/stashes/` 目录（如不存在），写入 `<id>-<name>.md`，frontmatter 中 `created` 和 `accessed` 均设为当前时间。

6. **输出确认**：
   ```
   已保存 #<id> <name>（<mode>模式），其他会话用 /ctx-stash l <id> 加载
   ```

---

## Sub-command: load

注入已保存的上下文到当前对话。

### 流程

1. **解析参数**：按快捷引用规则查找目标文件。

2. **找不到则列出**：输出可用上下文列表，让用户选择。

3. **读取文件**：读取目标 `.md` 文件的完整内容。

4. **更新 accessed**：将 frontmatter 中的 `accessed` 更新为当前时间，写回文件。

5. **输出到对话**（关键：必须 print 出来，让内容进入对话上下文）：

   - 如果内容不超过 200 行，直接输出全文：
     ```
     📋 加载上下文 #<id> <name>（<mode>模式）：

     <完整上下文内容（不含 frontmatter）>
     ```

   - 如果超过 200 行，先输出摘要，然后用 AskUserQuestion 询问是否要全文：
     ```
     📋 上下文 #<id> <name> 共 <N> 行，以下是摘要：

     <前 50 行 + "..." + 最后 20 行>
     ```
     询问："该上下文较长（<N>行），要查看全文还是摘要就够了？"

6. **确认**：简要说明加载了什么上下文。

---

## Sub-command: list

列出所有已保存的上下文。

### 流程

1. 扫描 `.claude/skills/ctx-stash/stashes/*.md`，读取每个文件的 frontmatter。

2. 如果没有文件，输出：
   ```
   暂无保存的上下文。用 /ctx-stash s <name> 保存当前对话上下文。
   ```

3. 输出表格（按 ID 排序）：

   ```
   #  名称              模式    创建时间          上次访问
   1  auth-analysis     总结    03-19 10:30      03-19 14:00
   2  api-review        完整    03-18 09:00      03-19 11:00
   3  bug-investigation 总结    03-17 16:00      03-17 16:00  ⚠ 5天未访问
   ```

   - 模式显示为中文：`summary` → `总结`，`full` → `完整`
   - 超过 5 天未访问的加 `⚠ <N>天未访问` 警告
   - 7 天以上的已被自动清理，不会出现在列表中

---

## Sub-command: rm

删除指定的上下文。

### 流程

1. **解析参数**：按快捷引用规则查找目标文件。无参数或找不到则列出可用上下文让用户选择。

2. **删除文件**：用 Bash `rm` 删除目标文件。

3. **输出确认**：
   ```
   已删除 #<id> <name>
   ```

---

## 实现注意事项

- **目录创建**：save 时如果 `.claude/skills/ctx-stash/stashes/` 不存在，先 `mkdir -p` 创建
- **frontmatter 解析**：用 `---` 分隔符提取 YAML frontmatter，手动解析 key-value
- **时间格式**：frontmatter 中用 ISO 8601（`2026-03-19T10:30:00`），显示时用短格式（`03-19 10:30`）
- **ID 分配**：扫描所有文件名中的数字前缀，取 max + 1
- **文件名安全**：name 只允许 `[a-z0-9-]`，其他字符替换为 `-`
- **并发安全**：不需要锁，文件操作天然幂等
