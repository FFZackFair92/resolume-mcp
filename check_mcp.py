# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2", "httpx>=0.27"]
# ///
"""Carica il server MCP senza avviarlo e stampa i tool registrati."""
import asyncio

import resolume_mcp

tools = asyncio.run(resolume_mcp.mcp.list_tools())
names = sorted(t.name for t in tools)
print(len(names), "tool")
for n in names:
    print(" -", n)
