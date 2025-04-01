#!/usr/bin/env python
from mcp.server.fastmcp import FastMCP, Context
from postgresDB import MessageDB
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
import time


@dataclass
class AppContext:
    db: MessageDB


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""
    # Initialize on startup
    db = MessageDB()
    try:
        yield AppContext(db=db)
    finally:
        # Cleanup on shutdown
        await db.close_connection()


mcp = FastMCP("smack", lifespan=app_lifespan)

@mcp.tool()
async def list_messages(ctx: Context):
    app_ctx: AppContext = ctx.request_context.lifespan_context
    db: MessageDB = app_ctx.db
    messages = db.get_all_messages()
    
    if not messages:
        return "No messages available."
    
    message_list = []
    for i, message in enumerate(messages, 1):
        sender = message[1]
        content = message[2]
        message_list.append(f"{i}. {sender}: {content}")
    
    return "\n".join(message_list)

@mcp.tool()
async def post_message(ctx: Context, sender: str, message: str):
    app_ctx: AppContext = ctx.request_context.lifespan_context
    db: MessageDB = app_ctx.db
    success = db.add_message(sender, message)
    if success:
        return f"Message posted successfully: '{message}'"
    else:
        return f"Failed to post message to database: {success}"

if __name__ == "__main__":
    mcp.run(transport='sse')
