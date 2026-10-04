#!/usr/bin/env python3
"""
Dexorto AI Model Context Protocol (MCP) Server
===============================================
Exposes Dexorto desktop assistant tools (notes, tasks, calculator,
weather, system audit, music control) over standard JSON-RPC 2.0 stdio MCP.
"""

import sys
import os
import json
import traceback

# Ensure parent directory is in Python path for assistant_tools import
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from assistant_tools import ToolExecutor
except ImportError:
    ToolExecutor = None

MCP_TOOLS = [
    {
        "name": "get_daily_tasks",
        "description": "Retrieve daily study routine or weekly task schedule for Dex (Physics, Chemistry, Maths, CS, Rest).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day": {
                    "type": "string",
                    "description": "Day of the week (monday, tuesday, etc.), 'today', 'tomorrow', or 'all'."
                }
            }
        }
    },
    {
        "name": "manage_notes",
        "description": "Manage quick notes, reminders, and todo items (add, list, remove, clear).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove", "clear"],
                    "description": "Action to perform on notes"
                },
                "content": {
                    "type": "string",
                    "description": "Content of the note to add or remove"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "get_weather",
        "description": "Fetch real-time weather and temperature for any city or current location via wttr.in.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name or 'auto' for IP location"
                }
            }
        }
    },
    {
        "name": "calculate",
        "description": "Evaluate mathematical expressions (arithmetic, percentages, powers, square roots).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression string"
                }
            },
            "required": ["expression"]
        }
    },
    {
        "name": "audit_system",
        "description": "Inspect CPU, RAM, and memory hogs, and optionally run optimization/cleanup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cleanup": {
                    "type": "boolean",
                    "description": "Whether to clean memory/cache"
                }
            }
        }
    },
    {
        "name": "copy_to_clipboard",
        "description": "Copy text directly to the Linux desktop X11 clipboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to copy to clipboard"
                }
            },
            "required": ["text"]
        }
    }
]


def send_response(response_dict):
    payload = json.dumps(response_dict)
    sys.stdout.write(f"Content-Length: {len(payload)}\r\n\r\n{payload}")
    sys.stdout.flush()


def handle_request(req):
    msg_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "dexorto-assistant-mcp",
                    "version": "1.0.0"
                }
            }
        }

    elif method == "notifications/initialized":
        return None

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": MCP_TOOLS
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if not ToolExecutor:
            res_text = f"ToolExecutor not available in {SCRIPT_DIR}."
        else:
            try:
                res_text = ToolExecutor.execute_tool(tool_name, tool_args)
            except Exception as e:
                res_text = f"Error executing tool '{tool_name}': {e}\n{traceback.format_exc()}"

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": str(res_text)
                    }
                ]
            }
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Method '{method}' not found."
            }
        }


def main():
    buffer = ""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        buffer += line

        # Handle Content-Length header or raw JSON-RPC newline mode
        if buffer.startswith("Content-Length:"):
            parts = buffer.split("\r\n\r\n", 1)
            if len(parts) == 2:
                header, body = parts
                try:
                    content_len = int(header.split(":")[1].strip())
                    if len(body.encode("utf-8")) >= content_len:
                        req_str = body[:content_len]
                        buffer = body[content_len:]
                        req = json.loads(req_str)
                        resp = handle_request(req)
                        if resp is not None:
                            send_response(resp)
                except Exception:
                    pass
        else:
            # Direct line-delimited JSON
            s_line = line.strip()
            if s_line.startswith("{") and s_line.endswith("}"):
                try:
                    req = json.loads(s_line)
                    resp = handle_request(req)
                    if resp is not None:
                        out = json.dumps(resp)
                        sys.stdout.write(out + "\n")
                        sys.stdout.flush()
                except Exception:
                    pass
                buffer = ""


if __name__ == "__main__":
    main()
