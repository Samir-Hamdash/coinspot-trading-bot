"""
claude_brain.py — replaced by mcp_server.py

The AI decision engine now runs inside Claude desktop via MCP.
bot.py calls mcp_server.request_mcp_analysis() instead of this module.

This stub is kept so that any external tooling that imports this module
does not crash with an ImportError.
"""
from mcp_server import request_mcp_analysis

async def analyse_market(market_data, portfolio, memory_summary):
    """Shim — delegates to MCP server."""
    return await request_mcp_analysis(market_data, portfolio, memory_summary)
