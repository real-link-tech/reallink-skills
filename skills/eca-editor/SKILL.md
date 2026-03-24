---
name: eca-editor
description: Control Unreal Editor via ECA commands through CmdLink named pipe
user_invocable: true
---

# ECA Editor — Unreal Editor Control via CmdLink

Execute ECA commands against a running Unreal Editor through the CmdLink named pipe.

## Prerequisites

- Unreal Editor running with `-cmdlink` flag
- CmdLink.exe built from your engine (located at `Engine/Binaries/Win64/CmdLink.exe`)

## Decision Flow — What to Use

```
Task requires controlling UE Editor
  |
  +-- Do you know which predefined command to use?
  |     +-- Yes --> ECA.Exec <command> '<json>'          <-- vast majority of cases
  |     +-- Not sure --> ECA.List [Category] to look up, then Exec
  |
  +-- No predefined command covers this operation?
  |     +-- describe_object to explore the target class
  |     +-- describe_function to confirm the signature
  |     +-- call_function to invoke it                   <-- escape hatch, not the normal path
  |
  +-- Need to run multiple commands in sequence?
        +-- ECA.Batch to send them all at once           <-- latency optimization, optional
```

**Core principle**: Predefined commands first. Reflection only when predefined commands don't cover the use case.

## Calling Convention

```bash
# Set this to your engine's CmdLink.exe path
CMDLINK="<engine_root>/Engine/Binaries/Win64/CmdLink.exe"

# 1. Execute a command (most common)
$CMDLINK ECA.Exec <command_name> '<json_params>'

# 2. Discover commands (when unsure which to use)
$CMDLINK ECA.List              # List all categories
$CMDLINK ECA.List Actor        # List all commands + params in the Actor category

# 3. Batch (optional optimization for multiple sequential commands)
$CMDLINK ECA.Batch '[{"command":"cmd1","params":{...}},{"command":"cmd2","params":{...}}]'
```

## Response Format

```json
{"success":true,"result":{...}}
```

On error, the response includes the command's full parameter signature for self-correction:
```json
{"success":false,"error":"...","expected":{"name":"create_actor","params":[{"name":"actor_type","type":"string","required":true}]}}
```

Batch response:
```json
{"success":true,"count":2,"results":[{"command":"cmd1","success":true,"result":{...}},{"command":"cmd2","success":true,"result":{...}}]}
```

## Common Examples

```bash
$CMDLINK ECA.Exec get_level_info '{}'
$CMDLINK ECA.Exec create_actor '{"actor_type":"PointLight","location":{"x":0,"y":0,"z":200}}'
$CMDLINK ECA.Exec take_gameplay_screenshot '{}'
$CMDLINK ECA.Exec find_actors '{"class_name":"StaticMeshActor"}'
$CMDLINK ECA.Exec lisp_to_blueprint '{"blueprint_path":"/Game/BP/BP_Test","code":"(event BeginPlay (call PrintString \"Hello\"))","clear_existing":true}'
$CMDLINK ECA.Exec save_all_dirty '{}'
```

## Reflection Commands (only when predefined commands are insufficient)

```bash
# Explore: what functions and properties does this class have?
$CMDLINK ECA.Exec describe_object '{"object_path":"/Script/Engine.Actor","function_filter":"Location"}'

# Confirm signature: how do I call this function?
$CMDLINK ECA.Exec describe_function '{"object_path":"/Script/Engine.Actor","function_name":"GetActorLocation"}'

# Read property value (supports bVisible/Visible flexible lookup)
$CMDLINK ECA.Exec describe_property '{"object_path":"/Game/Maps/L.L:PersistentLevel.MyActor","property_name":"Visible"}'

# Find live instances
$CMDLINK ECA.Exec find_instances '{"class_name":"PointLight","limit":5}'

# Call any UFunction via reflection
$CMDLINK ECA.Exec call_function '{"object_path":"/Script/Engine.Default__KismetSystemLibrary","function_name":"PrintString","args":{"InString":"Hello"}}'
```

## Notes

- Asset paths use UE content format: `/Game/Folder/Asset`
- File system paths use forward slashes: `D:/Projects/file.png`
- JSON params default to `{}` if omitted
- Commands run on the game thread — editor must not be in a modal dialog
- Use `save_asset` or `save_all_dirty` to persist changes
- `call_function` does not support latent functions (those with async/delay)
