# Youmoji

TouchDesigner project. Main file: `DuoMoji.toe`.

## Setup

### 1. Large assets (not in git)

`yolo_1_0.tox` (~1.2 GB) is gitignored because of its size. Place it at the repo
root so `/project1/yolo` can load it via the relative path `yolo_1_0.tox`.

### 2. MCP server (optional, for Claude Code feature work)

The `touchdesigner-mcp-td/` folder is vendored from
[touchdesigner-mcp v1.4.7](https://github.com/8beeeaaat/touchdesigner-mcp).
It exposes TouchDesigner to Claude Code via the `touchdesigner` MCP server.

To enable:

1. Register the MCP server with Claude Code:
   ```
   claude mcp add -s user touchdesigner -- npx -y touchdesigner-mcp-server@latest --stdio
   ```
2. Restart Claude Code.
3. Open `DuoMoji.toe` in TouchDesigner — `/project1/mcp_webserver_base` loads
   `touchdesigner-mcp-td/mcp_webserver_base.tox` via the project-relative path.
