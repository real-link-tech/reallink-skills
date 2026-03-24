---
name: ps5-devkit-bridge
description: Full PS5 DevKit management via prospero-ctrl — install/uninstall packages, send UE console commands, browse/read files (logs, crashes, memreports), upload/download files, manage app lifecycle (start/kill/suspend/resume), power control (on/off/reboot/rest-mode/safe-mode), target management, screenshot/video capture, save data, diagnostics, controller record/playback, network config, user management, workspace, PlayGo, and process dumps. Use this skill when the user mentions PS5 commands, prospero-ctrl, devkit commands, UE console commands on PS5, "send to PS5", "open map on PS5", "run on PS5", stat fps/unit on PS5, PS5 dev kit logs, PS5 devlog, dev kit files, reading PS5 logs, PS5 crash logs, PS5 package install, PS5 deploy, "装包", "安装包体", "卸载", "读PS5日志", "看调试机日志", "调试机文件", "devkit日志", PS5 saved directory, PS5 screenshot, PS5 video capture, PS5 save data, PS5 controller playback, PS5 workspace, PS5 diagnostics, PS5 network, PS5 user management, or wants to interact with a connected PS5 test kit. Also use when the user provides a network path like \\192.168.x.x or A:\192.168.x.x pointing to a dev kit. DO NOT use for local log files, PC builds, or logs already copied to the local machine.
---

# PS5 DevKit Bridge

Unified skill for interacting with a connected PS5 DevKit via `prospero-ctrl`.

## Tool path

```
PROSPERO_CTRL="/c/Program Files (x86)/SCE/Prospero/Tools/Target Manager Server/bin/prospero-ctrl.exe"
```

All bash examples below use this path. Abbreviate as `$PCTL` in commentary.

## Capabilities

| Category | Tasks | Key Commands |
|----------|-------|-------------|
| Package management | Install, uninstall, list, slot management, entitlements | `package install/uninstall/list/slot-info` |
| UE console commands | Send any UE console command to running game | `process console` |
| Filesystem | Browse, read, download, upload, delete files on DevKit | `filesystem map/get/put/list/delete` |
| App lifecycle | Start, kill, suspend, resume, info | `application start/kill/suspend/resume/info` |
| Power | On, off, reboot, rest-mode, safe-mode | `power on/off/reboot/rest-mode/safe-mode` |
| Target management | Add, find, connect, list, info, set-default, update firmware | `target add/find/list/info/update` |
| Screenshot & video | Capture screenshots and video recordings | `target screenshot/video` |
| Save data | List, export, import, delete save data | `savedata list/export/import/delete` |
| Diagnostics | Health check, system dump, collect logs, monitor, pcap | `diagnostics health-check/system-dump/collect-logs` |
| Process | List, info, kill, spawn, dump, kernel objects | `process list/info/kill/spawn`, `process-dump trigger/view` |
| Controller | Record and playback controller input | `controller record/playback` |
| Network | IP config, DevLAN settings, network emulation, packet capture | `network ip-config/set-devlan-settings` |
| User | Create, login, logout, PSN association | `user create/login/logout/psn-associate` |
| Workspace | Create, deploy, destroy standalone workspaces | `workspace create/deploy/destroy` |
| PlayGo | Streaming install simulation and chunk management | `playgo start-transfer/set-chunk-status` |
| Settings | Export/import target settings, release check mode | `settings export/import/set-release-check-mode` |

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

### Step 4 — Download/upload/delete files (CLI)

For downloading, uploading, or deleting files, use `prospero-ctrl filesystem` directly:

```bash
# Download a file from DevKit to local
"$PCTL" filesystem get "/devlog/app/projectpbz/projectpbz/saved/Logs/ProjectPBZ.log" "C:/temp/ProjectPBZ.log"

# Download a directory
"$PCTL" filesystem get "/devlog/app/projectpbz/projectpbz/saved/Crashes/" "C:/temp/Crashes/"

# Upload a file to DevKit
"$PCTL" filesystem put "C:/local/file.txt" "/data/file.txt"

# List files on DevKit (without mapping)
"$PCTL" filesystem list "/devlog/app/projectpbz/projectpbz/saved/Logs/"

# Delete a file on DevKit
"$PCTL" filesystem delete "/data/old_file.txt"

# Delete a directory recursively
"$PCTL" filesystem delete "/data/old_dir/" /recursive

# Unmap the filesystem when done
"$PCTL" filesystem unmap
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

## C — Package management (install, uninstall, list, slots, entitlements)

### Install a package (.pkg)

```bash
# Install a package onto the default target
"$PCTL" package install "C:/path/to/game.pkg"

# Install into a specific slot (0-15)
"$PCTL" package install "C:/path/to/game.pkg" /slotId:1

# Install on a specific target
"$PCTL" package install "C:/path/to/game.pkg" /target:<ip>
```

The `<path>` is a **local host PC path** to the `.pkg` file. If a slot is specified and it's not the current slot, the system will automatically switch to it.

### List installed packages

```bash
"$PCTL" package list
"$PCTL" package list /target:<ip>
```

### Uninstall

```bash
# Uninstall all packages for a TitleId
"$PCTL" package uninstall <titleId>

# Uninstall only the patch
"$PCTL" package uninstall <titleId> /type:PATCH

# Uninstall only additional content
"$PCTL" package uninstall <titleId> /type:AC

# Uninstall specific additional content by contentId
"$PCTL" package uninstall <titleId> /type:AC /contentId:<contentId>

# Uninstall from a specific slot
"$PCTL" package uninstall <titleId> /slotId:1

# Uninstall ALL (base + patch + AC)
"$PCTL" package uninstall <titleId> /type:ALL
```

### Slot management

Slots (0-15) allow multiple versions of the same package to coexist on the DevKit.

```bash
# View all slot info for a content
"$PCTL" package slot-info <contentId>

# Switch which slot is active
"$PCTL" package set-current-slot <contentId> <slotId>

# Link one slot to another (share reference package)
"$PCTL" package link <contentId> <srcSlotId> <dstSlotId>

# Rebase all packages into a single remastered package
"$PCTL" package rebase <contentId>
"$PCTL" package rebase <contentId> /slotId:2
```

### Move packages between storage

```bash
# Move to internal storage
"$PCTL" package move <titleId> INTERNAL

# Move to USB extended storage
"$PCTL" package move <titleId> EXTERNAL

# Move to M.2 SSD
"$PCTL" package move <titleId> M2
```

### Content configuration

```bash
# List available content configs
"$PCTL" package list-content-config <contentId>

# Switch content config
"$PCTL" package switch-content-config <contentId> <label>
```

### Entitlements

```bash
# List all entitlements
"$PCTL" package entitlement-list

# List entitlements for a specific title
"$PCTL" package entitlement-list /titleId:<titleId>

# Show entitlement details
"$PCTL" package entitlement-details

# Enable/disable/delete entitlements
"$PCTL" package entitlement-enable <contentId>
"$PCTL" package entitlement-disable <contentId>
"$PCTL" package entitlement-delete <contentId>
```

---

## D — Application lifecycle

### Start/stop applications

```bash
# Start an installed application by TitleId
"$PCTL" application start <titleId>

# Start with arguments passed to the application
"$PCTL" application start <titleId> /args -arg1 -arg2

# Start with a different ELF (host path)
"$PCTL" application start <titleId> /elf:"C:/path/to/custom.elf"

# Start with ELF from within the package
"$PCTL" application start <titleId> /elf:"custom.elf" /elfPathFormat:PACKAGE

# Start with flexible memory override (in MiB)
"$PCTL" application start <titleId> /flexibleMemory:512

# Start with extended direct memory override
"$PCTL" application start <titleId> /extendedDirectMemory:256

# Start with workspace overlay (overlays files from a standalone workspace)
"$PCTL" application start <titleId> /workspaceOverlay:<workspace>

# Start non-debuggable
"$PCTL" application start <titleId> /nodebug

# Kill an application
"$PCTL" application kill <titleId>

# Suspend an application
"$PCTL" application suspend <titleId>

# Resume a suspended application
"$PCTL" application resume <titleId>
```

`<application>` can be a Title ID, Application ID, Application Name, or Process ID.

### Info and listing

```bash
# List debuggable applications
"$PCTL" application list

# Detailed info about a specific application
"$PCTL" application info <application>
```

### Application data management

```bash
# Mount application data (for access from host PC)
"$PCTL" application mount-data <titleId>
"$PCTL" application mount-data <titleId> /fingerprint:<fingerprint>

# Unmount application data
"$PCTL" application unmount-data <titleId>

# Delete application data (trophy/UDS)
"$PCTL" application delete-data TROPHY CONSOLE
"$PCTL" application delete-data UDS ALL /user:<id-or-name>

# Trigger a system event (e.g., deeplink)
"$PCTL" application system-event <application> /link:<psgm_url>
```

---

## E — Power management

```bash
# Power on
"$PCTL" power on

# Power off (graceful)
"$PCTL" power off

# Force power off
"$PCTL" power off /force

# Reboot
"$PCTL" power reboot

# Enter rest mode
"$PCTL" power rest-mode

# Safe mode — interactive menu
"$PCTL" power safe-mode MENU

# Safe mode — factory reset (option 7)
"$PCTL" power safe-mode INITIALIZE

# Safe mode — reinstall system software (option 8)
"$PCTL" power safe-mode REINSTALL
"$PCTL" power safe-mode REINSTALL /pup:"C:/path/to/PS5UPDATE.PUP"
```

---

## F — Target management

### Add and discover targets

```bash
# Find targets on network
"$PCTL" target find

# Find targets in IP range
"$PCTL" target find /start:192.168.1.1 /end:192.168.1.254 /subnet:255.255.255.0

# Add a target
"$PCTL" target add <ip_or_hostname>

# Add with authentication key
"$PCTL" target add <ip> /key:<32-char-key>

# Delete a target
"$PCTL" target delete /target:<ip>
```

### Connect/disconnect

```bash
# Connect to default target
"$PCTL" target connect

# Force connect (steal from another host)
"$PCTL" target connect /force

# Disconnect
"$PCTL" target disconnect
```

### Info and management

```bash
# List all targets
"$PCTL" target list

# Update target info cache
"$PCTL" target list /update

# Detailed target info
"$PCTL" target info

# Set default target
"$PCTL" target set-default <ip>

# Get current default
"$PCTL" target get-default

# Set system name
"$PCTL" target name "MyDevKit" /target:<ip>

# Locate target (beep/flash)
"$PCTL" target locate
"$PCTL" target locate /mode:AUDIO
"$PCTL" target locate /mode:VISUAL
```

### Firmware update

```bash
# Update system software from local file
"$PCTL" target update "C:/path/to/PS5UPDATE.PUP"

# Update from URL
"$PCTL" target update "http://server/PS5UPDATE.PUP"

# Update communication processor firmware
"$PCTL" target update-cp "C:/path/to/cpfw.bin"
```

### Screenshot

```bash
# Capture a screenshot (format determined by extension)
"$PCTL" target screenshot "C:/captures/screen.png"

# Game image only
"$PCTL" target screenshot "C:/captures/game.png" /mode:GAME

# System UI only
"$PCTL" target screenshot "C:/captures/system.png" /mode:SYSTEM

# Supported formats: .png, .jpg, .jpeg, .bmp, .tga, .jxr, .exr
```

### Video capture

```bash
# Capture video (Ctrl+C to stop)
"$PCTL" target video "C:/captures/gameplay.mp4"

# With custom settings
"$PCTL" target video "C:/captures/gameplay.mp4" /resolution:1080p /frame-rate:60 /bandwidth:15000

# Capture for a specific duration
"$PCTL" target video "C:/captures/clip.mp4" /length:30s

# HDR capture at 4K
"$PCTL" target video "C:/captures/hdr.mp4" /resolution:2160p /hdr

# Ring buffer (continuous recording, last N minutes)
"$PCTL" target video "C:/captures/buffer.mp4" /limit-buffer:10

# Available resolutions: 360p, 540p, 720p, 1080p, 1440p, 2160p
# Frame rates: 30, 60
```

### Target console log

```bash
# Stream live console output
"$PCTL" target console

# With timestamps
"$PCTL" target console /timestamp

# Include historical output
"$PCTL" target console /history

# Specific output channel
"$PCTL" target console /channel:STDOUT
"$PCTL" target console /channel:STDERR
```

### M.2 SSD management

```bash
# Check M.2 status
"$PCTL" target m2-status

# Format M.2 SSD
"$PCTL" target m2-format <encryptionKey>

# Mount M.2 SSD
"$PCTL" target m2-mount <encryptionKey>
```

### Authentication & encryption

```bash
# Set authentication key for a target
"$PCTL" target set-authentication-key <32-char-key>

# Remove authentication key
"$PCTL" target unset-authentication-key

# Set TLS certificates for encrypted communication
"$PCTL" target set-encryption-certificates <clientCert> <clientKey> <rootCert>

# Remove encryption overrides
"$PCTL" target unset-encryption-certificates
```

### File serving

```bash
# Set the file serving root directory
"$PCTL" target set-fileserving-root "C:/GameData"
```

### Target activation

```bash
# Activate immediately via internet
"$PCTL" target activate-now
```

---

## G — Save data management

```bash
# List all save data
"$PCTL" savedata list

# List and validate (checks for corruption)
"$PCTL" savedata list /validate

# Export save data to host
"$PCTL" savedata export <titleId> "C:/saves/"

# Export specific directories
"$PCTL" savedata export <titleId> "C:/saves/" /directory:saveDir1 /directory:saveDir2

# Export raw (unencrypted) save data
"$PCTL" savedata export-raw <titleId> "C:/saves/" /fingerprint:<fingerprint>
"$PCTL" savedata export-raw <titleId> "C:/saves/" /keystone:"C:/path/to/keystone"

# Import save data from host
"$PCTL" savedata import "C:/saves/"

# Import specific directories
"$PCTL" savedata import "C:/saves/" /directory:saveDir1

# Import raw (unencrypted) save data
"$PCTL" savedata import-raw <titleId> "C:/saves/" /fingerprint:<fingerprint>

# Delete save data
"$PCTL" savedata delete <titleId>

# Delete specific directories
"$PCTL" savedata delete <titleId> /directory:saveDir1
```

---

## H — Diagnostics

### Quick checks

```bash
# Health check (quick)
"$PCTL" diagnostics health-check

# Health check (full, may take longer and change target state)
"$PCTL" diagnostics health-check /mode:full

# Monitor target notifications (live stream)
"$PCTL" diagnostics monitor

# Show stream usage info
"$PCTL" diagnostics show-usage

# List applications using Target Manager Server
"$PCTL" diagnostics clients

# Version info
"$PCTL" diagnostics version

# List installed SDK tools
"$PCTL" diagnostics installed-tools
```

### Log collection

```bash
# Collect all tool logs into a zip
"$PCTL" diagnostics collect-logs "C:/diagnostics/logs.zip"

# Start verbose logging for specific tools
"$PCTL" diagnostics start-logging /tool:TM-SERVER /tool:DEBUGGER

# Stop verbose logging
"$PCTL" diagnostics stop-logging

# Clear logs
"$PCTL" diagnostics clear-logs
```

### Dumps

```bash
# System coredump (target will power off)
"$PCTL" diagnostics system-dump

# Communication Processor dump
"$PCTL" diagnostics cp-dump "C:/diagnostics/cp.log"

# HDMI diagnostic dump
"$PCTL" diagnostics hdmi-dump "C:/diagnostics/hdmi.bin"

# I/O controller dump
"$PCTL" diagnostics io-dump "C:/diagnostics/io.log"

# Workspace diagnostic dump (target will reboot)
"$PCTL" diagnostics workspace-dump

# Dump title metadata (for SIE support)
"$PCTL" diagnostics dump-title-metadata "C:/diagnostics/metadata.bin"
```

### Network packet capture

```bash
# Start packet capture
"$PCTL" diagnostics pcap-begin "C:/captures/traffic.pcap"

# With rotating files
"$PCTL" diagnostics pcap-begin "C:/captures/file1.pcap" /file2:"C:/captures/file2.pcap" /size:100

# Stop capture
"$PCTL" diagnostics pcap-end
```

### Debug agent logging

```bash
# Get current debug agent logging config
"$PCTL" diagnostics get-debug-agent-logging

# Set debug agent logging
"$PCTL" diagnostics set-debug-agent-logging VERBOSE TTY

# Filesystem agent logging
"$PCTL" diagnostics get-filesystem-agent-logging
"$PCTL" diagnostics set-filesystem-agent-logging VERBOSE TTY

# Server logging level
"$PCTL" diagnostics get-server-logging-level
"$PCTL" diagnostics set-server-logging-level FULL
```

### Workspace performance testing

```bash
# Full performance test
"$PCTL" diagnostics workspace-performance FULL

# Network only
"$PCTL" diagnostics workspace-performance NETWORK

# Workspace write speed
"$PCTL" diagnostics workspace-performance WORKSPACE
```

---

## I — Process management

### Basic operations

```bash
# List all running processes
"$PCTL" process list

# Process info (all details)
"$PCTL" process info

# Show specific info types
"$PCTL" process info /show:MODULES /show:THREADS
"$PCTL" process info /show:VIRTUALMEMORY
# Options: ALL, BASIC, MODULES, THREADS, FILES, VIRTUALMEMORY

# Kill a process
"$PCTL" process kill
"$PCTL" process kill /process:0x00000054

# View socket info for a process
"$PCTL" process sockets /process:0x00000054

# View kernel objects
"$PCTL" process objects 0x00000054 ALL
# Object types: ALL, SYNC, ULT-RUNTIMES, FIBER, JOBMANAGER, FILES

# View AMM/APR command buffers
"$PCTL" process command-buffers AMM /process:0x00000054
"$PCTL" process command-buffers APR /process:0x00000054
```

### Spawn a process

```bash
# Spawn an ELF from host PC
"$PCTL" process spawn "C:/path/to/game.elf"

# With a workspace
"$PCTL" process spawn "C:/path/to/game.elf" /workspace:<name>

# With GP5 file for working directory layout
"$PCTL" process spawn "C:/path/to/game.elf" /gp5File:"C:/path/to/project.gp5"

# With arguments
"$PCTL" process spawn "C:/path/to/game.elf" /args -arg1 value1

# With flexible/extended memory override
"$PCTL" process spawn "C:/path/to/game.elf" /flexibleMemory:512 /extendedDirectMemory:256

# Non-debuggable
"$PCTL" process spawn "C:/path/to/game.elf" /nodebug

# With on-demand mirroring
"$PCTL" process spawn "C:/path/to/game.elf" /mirrorMode:ON-DEMAND

# Can also use a .ps5launch JSON file
"$PCTL" process spawn "C:/path/to/config.ps5launch"
```

### Process dumps

```bash
# Trigger a process dump
"$PCTL" process-dump trigger 0x00000054 "C:/dumps/" FULL
"$PCTL" process-dump trigger 0x00000054 "C:/dumps/" MINI

# View a dump file
"$PCTL" process-dump view "C:/dumps/dump.bin"
"$PCTL" process-dump view "C:/dumps/dump.bin" /show:THREADS /show:MODULES

# View console output from dump
"$PCTL" process-dump console "C:/dumps/dump.bin"

# Extract data from dumps
"$PCTL" process-dump extract-userdata "C:/dumps/dump.bin" "C:/dumps/userdata.bin"
"$PCTL" process-dump extract-userfiles "C:/dumps/dump.bin" "C:/dumps/userfiles/"
"$PCTL" process-dump list-userfile "C:/dumps/dump.bin"
"$PCTL" process-dump extract-user-string "C:/dumps/dump.bin"
"$PCTL" process-dump extract-structured-userdata "C:/dumps/dump.bin" /output:"C:/dumps/data.json"
"$PCTL" process-dump extract-controller-data "C:/dumps/dump.bin" "C:/dumps/controller.bin"
```

---

## J — Controller record & playback

```bash
# Record controller input (Ctrl+C to stop)
"$PCTL" controller record "C:/captures/input.bin"

# Record specific devices
"$PCTL" controller record "C:/captures/input.bin" /device:CONTROLLER
"$PCTL" controller record "C:/captures/input.bin" /device:KEYBOARD /device:MOUSE
# Options: ALL, CONTROLLER, MOUSE, KEYBOARD, VRCONTROLLER

# Playback recorded input
"$PCTL" controller playback "C:/captures/input.bin"

# Playback without skipping to first timestamp
"$PCTL" controller playback "C:/captures/input.bin" /noskip

# Convert capture to/from JSON
"$PCTL" controller capture-to-json "C:/captures/input.bin" "C:/captures/input.json"
"$PCTL" controller capture-to-json "C:/captures/input.bin" "C:/captures/input.json" /delta
"$PCTL" controller json-to-capture "C:/captures/input.json" "C:/captures/input.bin"
```

---

## K — Network configuration

```bash
# View IP config
"$PCTL" network ip-config
"$PCTL" network ip-config /interface:eth0

# View network status
"$PCTL" network status

# Get DevLAN settings
"$PCTL" network get-devlan-settings

# Set DevLAN settings
"$PCTL" network set-devlan-settings /address:192.168.1.100 /subnetMask:255.255.255.0
"$PCTL" network set-devlan-settings /ipMode:AUTO
"$PCTL" network set-devlan-settings /hostname:mydevkit

# Change the DevKit address/hostname in TM Server
"$PCTL" network set-hostname <hostname>

# NAT traversal info
"$PCTL" network get-nat-traversal-info

# Network emulation (simulate poor network)
"$PCTL" network get-network-emulation-preset 1
"$PCTL" network set-network-emulation 1  # preset 1-3, or 0 to disable

# Per-process network emulation
"$PCTL" network get-process-network-emulation <process> <policy>
"$PCTL" network set-process-network-emulation <process> <policy> <option>

# Packet capture (at network level)
"$PCTL" network set-packet-capture on /type:LAN
"$PCTL" network set-packet-capture off
```

---

## L — User management

```bash
# List users on target
"$PCTL" user list

# Create a new local user
"$PCTL" user create
"$PCTL" user create /user:TestUser

# Login a user
"$PCTL" user login <user>

# Logout a user
"$PCTL" user logout <user>

# Delete a user
"$PCTL" user delete <user>

# PSN operations
"$PCTL" user psn-associate <user> <psnId> <password>
"$PCTL" user psn-signin <user>
"$PCTL" user psn-signout <user>
"$PCTL" user psn-signup <user> <country>
```

---

## M — Workspace management

Standalone workspaces allow deploying game content to the DevKit without creating a full package.

```bash
# Create a workspace
"$PCTL" workspace create <name>
"$PCTL" workspace create <name> /maxSize:2048
"$PCTL" workspace create <name> /storage:M2

# Deploy content to workspace via GP5 file
"$PCTL" workspace deploy <name> "C:/path/to/project.gp5"
"$PCTL" workspace deploy <name> "C:/path/to/project.gp5" /launch:"C:/path/to/elf/"

# Destroy a workspace
"$PCTL" workspace destroy <name>
```

---

## N — PlayGo (streaming install simulation)

PlayGo simulates PlayStation Store streaming install behavior on the DevKit.

```bash
# Get PlayGo status
"$PCTL" playgo get-status
"$PCTL" playgo get-status /titleId:<titleId>

# Set chunk status (simulate install state)
"$PCTL" playgo set-chunk-status <titleId> INITIAL     # only initial payload
"$PCTL" playgo set-chunk-status <titleId> COMPLETED   # all chunks installed

# Start a simulated download transfer
"$PCTL" playgo start-transfer
"$PCTL" playgo start-transfer /mode:LOW
"$PCTL" playgo start-transfer /mode:MANUAL   # install chunk by chunk

# Install next N chunks (when in MANUAL mode)
"$PCTL" playgo next-chunk 5

# Stop transfer
"$PCTL" playgo stop-transfer

# Initiate a PlayGo download
"$PCTL" playgo initiate-download /install:INITIAL
"$PCTL" playgo initiate-download /install:ALL

# Save/load PlayGo snapshots
"$PCTL" playgo save-snapshot "C:/playgo/"
"$PCTL" playgo load-snapshot "C:/playgo/playgo-status.xml" <titleId>
```

---

## O — Settings

```bash
# Export target settings to XML
"$PCTL" settings export "C:/settings/devkit.xml"

# Import settings from XML
"$PCTL" settings import "C:/settings/devkit.xml"
"$PCTL" settings import "C:/settings/devkit.xml" /reboot

# View boot parameters
"$PCTL" settings boot-parameters

# Set release check mode
"$PCTL" settings set-release-check-mode DEVELOPMENT
"$PCTL" settings set-release-check-mode ASSIST
"$PCTL" settings set-release-check-mode RELEASE

# Host exec control (allow target to launch process on host)
"$PCTL" settings get-hostexec
"$PCTL" settings set-hostexec ENABLE

# Mirroring progress notifications
"$PCTL" settings get-mirroring-progress
"$PCTL" settings set-mirroring-progress ENABLE
```

---

## P — PSN management

```bash
# Add/remove friends
"$PCTL" psn add-friend <psnId> <password> <friendPsnId> <friendPassword>
"$PCTL" psn add-friend <psnId> <password> <friendPsnId> <friendPassword> /relationship:CLOSE-FRIEND
"$PCTL" psn delete-friend <psnId> <password> <friendOnlineId>

# Block/unblock users
"$PCTL" psn add-blocked-user <psnId> <password> <userOnlineId>
"$PCTL" psn delete-blocked-user <psnId> <password> <userOnlineId>

# List friends/blocked
"$PCTL" psn list-friends <psnId> <password>
"$PCTL" psn list-blocked-users <psnId> <password>
```

---

## Q — Video watermark

```bash
# Set watermark
"$PCTL" video watermark-set <32-char-passphrase> "C:/path/to/watermark.ps5rvwatermark"

# Remove watermark
"$PCTL" video watermark-unset <32-char-passphrase>
```

---

## Important notes

- The PID changes every time the application restarts. Always re-check with `process list` if unsure.
- `process console` and `target console` block indefinitely streaming TTY output. Always use a timeout or background task pattern.
- The default target is used if `/target:` is not specified. Check `prospero-ctrl target list` to see which device is default.
- Commands via `process console` are UE console commands — anything you'd type in the UE console (`~` key) works.
- Filesystem target paths are unix-style (`/devlog/...`), not Windows paths.
- The DevKit IP (e.g. `192.168.104.17`) may change between kits — always verify dynamically.
- Large files (>10MB) should be sampled rather than read in full — use head/tail/grep.
- The user may refer to the DevKit as "调试机", "测试机", or just "PS5".
- `package install` takes a **host PC path** to a `.pkg` file — the file is transferred automatically.
- `power safe-mode` commands that change target state are **destructive** — confirm with user first.
- `diagnostics system-dump` will **power off** the target.
- `target video` requires Ctrl+C or `/length:` to stop — always use a timeout or background pattern.
- PSN commands require actual PSN credentials — never store or log passwords.

## Follow-up suggestions

After presenting content, offer relevant follow-ups:
- **For logs with errors**: "Want me to search for more context around these errors?"
- **For crash reports**: "Want me to look for this crash pattern in the log files too?"
- **For memreports**: "Want me to run the full memreport-analyze skill for a detailed HTML report?"
- **For performance data**: "Want me to look for correlation with specific game events in the logs?"
- **For package install**: "Want me to start the application after installation?"
- **For diagnostics**: "Want me to collect the full diagnostic logs for SIE support?"
