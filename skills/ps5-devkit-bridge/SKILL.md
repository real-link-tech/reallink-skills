---
name: ps5-devkit-bridge
description: Interact with a connected PS5 DevKit — send UE console commands, browse/read files (logs, crashes, memreports), and upload/download files. Use this skill when the user mentions PS5 commands, prospero-ctrl, devkit commands, UE console commands on PS5, "send to PS5", "open map on PS5", "run on PS5", stat fps/unit on PS5, PS5 dev kit logs, PS5 devlog, dev kit files, reading PS5 logs, PS5 crash logs, "读PS5日志", "看调试机日志", "调试机文件", "devkit日志", PS5 saved directory, or wants to check what happened on a connected PS5 test kit. Also use when the user provides a network path like \\192.168.x.x or A:\192.168.x.x pointing to a dev kit. DO NOT use for local log files, PC builds, or logs already copied to the local machine.
---

# PS5 DevKit Bridge

Unified skill for interacting with a connected PS5 DevKit via `prospero-ctrl`.

## Tool path

```
PROSPERO_CTRL="/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe"
```

All bash examples below use this path. Abbreviate as `$PCTL` in commentary.

## Capabilities

| Task | Method |
|------|--------|
| Send UE console commands | `process console` |
| Browse/read files on DevKit | `filesystem map` → read via mapped drive |
| Download files to local | `filesystem get` |
| Upload files to DevKit | `filesystem put` |
| List/manage targets | `target list`, `target info` |
| App lifecycle | `application start/kill`, `power reboot` |
| Screenshot | `target screenshot` |

---

## A — Filesystem access (browse, read, download, upload)

### Step 1 — Ensure drive is mapped

Before browsing or reading files, ensure the DevKit filesystem is mapped to a local drive letter.

**Detect existing mapping:**

```bash
# Check if any drive is already mapped to a PS5 devkit
net use 2>/dev/null | grep -i "prosper\|playstation\|PS5"
```

If that returns nothing, check common drive letters directly:

```bash
# Try to access known default paths — test A: first, then other common letters
for drive in A Z Y; do
  if ls "${drive}:/" >/dev/null 2>&1; then
    # Check if this looks like a devkit (has devlog directory)
    if ls "${drive}:/"*"/devlog" >/dev/null 2>&1; then
      echo "Found devkit on ${drive}:"
      ls "${drive}:/"
      break
    fi
  fi
done
```

**If no mapping found, map it automatically:**

```bash
"/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" filesystem map A:
```

Then verify:

```bash
ls "A:/"
```

If mapping fails, tell the user and suggest:
- Check the dev kit is powered on and connected
- Verify the IP with `prospero-ctrl target list`
- Try a different drive letter if A: is occupied

**Once mapped, determine the base Saved path:**

The DevKit IP appears as a directory under the mapped drive root. The standard Saved path is:

```
<DRIVE>:\<IP>\devlog\app\projectpbz\projectpbz\saved
```

Discover the actual IP dynamically:

```bash
# List the mapped drive root to find the IP directory
ls "A:/"
# Typically shows something like: 192.168.104.17/
```

Then construct the full path from what's found.

### Step 2 — Browse and read files

Once the mapped drive is confirmed, browse and read files directly:

```bash
BASE="A:/192.168.104.17/devlog/app/projectpbz/projectpbz/saved"

# List top-level contents
ls "$BASE"

# Recent logs
ls -lt "$BASE/Logs/" 2>/dev/null | head -20

# Crash reports
ls -lt "$BASE/Crashes/" 2>/dev/null | head -20

# Memory reports
find "$BASE" -maxdepth 2 -name "*.memreport" -o -name "*.memreport.txt" 2>/dev/null | head -20

# Profiling data
ls -lt "$BASE/Profiling/" 2>/dev/null | head -20
```

Present a summary organized by category:
- **Logs** — `.log` files with timestamps and sizes
- **Crashes** — crash report directories
- **Memory Reports** — `.memreport` files
- **Profiling** — CSV traces, stat files
- **Other** — anything else noteworthy

Then ask the user which file(s) they want to examine (or proceed directly if they already specified).

### Step 3 — Read file content intelligently

Auto-detect the file type and handle appropriately:

#### UE5 Log Files (`.log`)

Log files can be very large. Read intelligently:

1. **Quick overview** — last 200 lines for recent activity:
   ```bash
   tail -200 "<file_path>"
   ```

2. **Error/warning scan**:
   ```bash
   grep -n -i "error\|fatal\|critical\|assert\|crash\|exception" "<file_path>" | tail -50
   grep -n "Warning:" "<file_path>" | tail -30
   ```

3. **Startup info** — if interested in boot/launch:
   ```bash
   head -100 "<file_path>"
   ```

Present: session time range, map loaded, errors/warnings grouped by type, key events.

#### Crash Reports (`Crashes/` directory)

Read `CrashReport.log` or `CrashContext.runtime-xml` and present:
- The crash callstack (lines with `!` separating module and function)
- The assertion or error message
- The thread that crashed
- Relevant context from surrounding log lines

#### Memory Reports (`.memreport`)

For quick look: OS Physical Memory, peak memory, top LLM tag consumers, red flags.
For full analysis, suggest the `memreport-analyze` skill.

#### Profiling Data (`.csv`, `.ue4stats`)

For CSV: header, summary statistics, spikes/anomalies.
For stat files: key performance counters, problematic values.

### Step 4 — Download/upload files (CLI)

For downloading or uploading files, use `prospero-ctrl filesystem` directly:

```bash
# Download a file from DevKit to local
"/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" filesystem get "/devlog/app/projectpbz/projectpbz/saved/Logs/ProjectPBZ.log" "C:/temp/ProjectPBZ.log"

# Download a directory
"/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" filesystem get "/devlog/app/projectpbz/projectpbz/saved/Crashes/" "C:/temp/Crashes/"

# Upload a file to DevKit
"/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" filesystem put "C:/local/file.txt" "/data/file.txt"
```

Add `/target:<ip>` if targeting a specific device.

Note: target paths are **unix-style** (e.g., `/devlog/...`), not Windows paths.

---

## B — Send UE console commands

### Step 1 — Find the running process PID

```bash
"/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" process list
```

With a specific target:

```bash
"/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" process list /target:<ip>
```

Output looks like:

```
- PID: 0x00000054
  Name: eboot.bin
  TitleId: TEST23576
  ...
```

Extract the **PID** (e.g. `0x00000054`). If multiple processes, pick the game process (one with a TitleId).

### Step 2 — Send the command

```bash
echo "<command>" | "/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" process console <PID>
```

With a specific target:

```bash
echo "<command>" | "/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" process console <PID> /target:<ip>
```

### Step 3 — Handle the output

`process console` streams TTY output and won't terminate on its own. Use a timeout:

```bash
timeout 10 bash -c 'echo "<command>" | "/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe" process console <PID>'
```

Or use Bash tool's `run_in_background` + `TaskOutput` with a timeout, then `TaskStop`.

### Examples

```bash
# Open a map
echo "open pbz_xigu_wp" | "$PCTL" process console 0x00000054

# Show FPS stats
echo "stat fps" | "$PCTL" process console 0x00000054

# Teleport (project-specific GM command)
echo "gm_teleporttolocation (X=-71637.157268,Y=149619.646704,Z=63.147158)" | "$PCTL" process console 0x00000054

# Any UE console command
echo "stat unit" | "$PCTL" process console 0x00000054
echo "r.ScreenPercentage 75" | "$PCTL" process console 0x00000054
echo "showflag.postprocessing 0" | "$PCTL" process console 0x00000054
```

---

## C — Other useful commands

| Task | Command |
|------|---------|
| List targets | `prospero-ctrl target list` |
| Target info | `prospero-ctrl target info /target:<ip>` |
| List packages | `prospero-ctrl package list` |
| List apps | `prospero-ctrl application list` |
| Start app | `prospero-ctrl application start <TitleId>` |
| Kill app | `prospero-ctrl application kill <TitleId>` |
| Screenshot | `prospero-ctrl target screenshot <file.png>` |
| Reboot | `prospero-ctrl power reboot` |
| Console log | `prospero-ctrl target console` |
| List files on DevKit | `prospero-ctrl filesystem list <target_path>` |
| Map filesystem | `prospero-ctrl filesystem map <drive>` |
| Unmap filesystem | `prospero-ctrl filesystem unmap` |

---

## Important notes

- The PID changes every time the application restarts. Always re-check with `process list` if unsure.
- `process console` blocks indefinitely streaming TTY output. Always use a timeout or background task pattern.
- The default target is used if `/target:` is not specified. Check `prospero-ctrl target list` to see which device is default.
- Commands via `process console` are UE console commands — anything you'd type in the UE console (`~` key) works.
- Filesystem target paths are unix-style (`/devlog/...`), not Windows paths.
- The DevKit IP (e.g. `192.168.104.17`) may change between kits — always verify dynamically.
- Large files (>10MB) should be sampled rather than read in full — use head/tail/grep.
- The user may refer to the DevKit as "调试机", "测试机", or just "PS5".

## Follow-up suggestions

After presenting content, offer relevant follow-ups:
- **For logs with errors**: "Want me to search for more context around these errors?"
- **For crash reports**: "Want me to look for this crash pattern in the log files too?"
- **For memreports**: "Want me to run the full memreport-analyze skill for a detailed HTML report?"
- **For performance data**: "Want me to look for correlation with specific game events in the logs?"
