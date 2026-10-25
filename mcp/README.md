# Mednafen MCP debugger

Local MCP server and opt-in WonderSwan debugger bridge. The Python server uses
stdio JSON-RPC; it exchanges commands with Mednafen through a private directory.
It requires Python 3.8+ and a POSIX host. No Python packages or network port are
needed. Other emulator cores are unchanged.

## Build

On Debian/Ubuntu:

```sh
sudo apt install build-essential libsdl2-dev libflac-dev autoconf automake gettext pkg-config
python3 mcp/build.py
```

This creates `build-wswan/src/mednafen` with only the WonderSwan core and debugger.
It does not install or replace the system emulator. `autoreconf` regenerates
tracked Autotools output with your installed tool versions.

## Launch

Use the same absolute `MEDNAFEN_MCP_DIR` for the emulator and client/server.
If the directory already exists, it must be owned by you and have mode 0700.
Use a separate `MEDNAFEN_HOME` to isolate game saves and settings.

```sh
mkdir -p "$PWD/mcp/local/home"
MEDNAFEN_HOME="$PWD/mcp/local/home" \
MEDNAFEN_MCP_DIR="/tmp/mednafen-mcp-$(id -u)" \
  ./build-wswan/src/mednafen /absolute/path/game.wsc
```

The emulator starts **paused** when the bridge is enabled. Any request refreshes
the pause lease. After 30 seconds without a request, a paused emulator resumes
automatically. A running emulator is also bounded by the requested instruction
budget. The bridge is disabled unless `MEDNAFEN_MCP_DIR` is set.

Inspect using the command-line client (wire integers are decimal):

```sh
python3 mcp/client.py status
python3 mcp/client.py registers
python3 mcp/client.py read_memory 34336 32
python3 mcp/client.py breakpoint write 34336 34783
python3 mcp/client.py resume 10000000
python3 mcp/client.py status
```

The default client directory is `/tmp/mednafen-mcp-<uid>`.
Do not use the on-screen CPU debugger while controlling the MCP debugger: its
independent pause loop can prevent remote requests from being serviced.

## Connect an MCP client

Launch the server with `python3 /absolute/path/to/mcp/server.py`. It publishes:

- `debug_status`, `debug_pause`, `debug_continue`, `debug_step`
- `debug_registers`, `debug_read_memory`, `debug_disassemble`
- `debug_add_breakpoint`, `debug_clear_breakpoints`

For Codex CLI, for example:

```sh
codex mcp add mednafen -- python3 /absolute/path/to/mcp/server.py
```

For a nondefault bridge directory, provide `MEDNAFEN_MCP_DIR` to both processes.
Registering a server does not guarantee that an already running client session
will discover it; reconnect or start a new session as required by that client.

Inspection tools require a paused emulator. Resume and step return immediately;
poll `debug_status` to observe the eventual stop. CPU PC breakpoints and memory
addresses use 20-bit physical addresses. Disassembly takes a 16-bit IP and uses
the current CS segment. Registers include ROM bank selectors so mapped addresses
can be related to ROM offsets.

Memory breakpoints use Mednafen's speculative debug execution pass, so the
reported instruction has **not yet committed** the access. Read breakpoints
include instruction fetches. The first matching access is reported. Stepping
counts CPU callbacks; HLT callbacks can occur without retiring an instruction.
There are no remote memory-write, arbitrary file-load or code-execution tools.
The MCP tool set does not yet expose controller input, screenshots or state loading. The file client additionally supports `input <mask> <frames>` (up to 600 frames) and `capture`. Capture queues a PPM screenshot at the next rendered frame in `<bridge>/snapshot.ppm`; resume the emulator to complete it. Standard controller bits are X up/right/down/left at bits 0/1/2/3, Y at bits 4–7, Start at bit 8, A at bit 9 and B at bit 10. Input temporarily overrides controller state and then releases automatically.

The file client also has experimental `auto_capture 1`, `auto_capture 0`, and
`save_state` commands. Automatic capture uses a white-pixel screen hash to
detect a stable frame and writes numbered PPM images with matching `.mcs`
states. It is a visual heuristic, not a text recognizer: cursors or other white
graphics can trigger captures, and text in other colors can be missed. The
sequence counter resets each time the emulator starts. `save_state` writes
`checkpoint.mcs` at the next completed frame. These additions compile, but
have not yet had complete runtime validation.

## Validation

```sh
python3 -m unittest discover -s mcp/tests -v
python3 mcp/smoke_rom.py --rom /absolute/path/game.wsc
# Optionally start from a user-supplied Mednafen state:
python3 mcp/smoke_rom.py --rom /absolute/path/game.wsc --state /absolute/path/game.mc3
```

Tests compile a fake C++ backend and exercise file IPC and MCP stdio end to end.
The ROM smoke test starts the **real compiled emulator** with SDL's dummy video
driver and an isolated temporary home, checks registers/disassembly/memory,
steps three CPU callbacks, and catches a real RAM-write breakpoint. It never
modifies the provided ROM or state file. ROMs and save states are not included.

When a command times out, its outcome may be unknown: inspect status before
retrying a mutation. One emulator may own a bridge directory at a time; the
OS releases its lock on exit. Concurrent controllers are not coordinated.

License: GPL-2.0-or-later for the added bridge and Python code; see the upstream
source headers and root `COPYING` for the existing emulator's terms.

Protocol references:

- https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- https://mednafen.github.io/documentation/debugger.html
