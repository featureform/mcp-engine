#!/usr/bin/env python
from mcp.server.fastmcp import FastMCP
import sys
from db import MessageDB

# Create FastMCP instance for HTTP mode
mcp = FastMCP("smack")

@mcp.tool()
def list_messages():
    db = MessageDB()
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
def post_message(message: str):
    SENDER_NAME = "user"
    db = MessageDB()
    success = db.add_message(SENDER_NAME, message)
    if success:
        return f"Message posted successfully: '{message}'"
    else:
        return "Failed to post message to database"

if __name__ == "__main__":
    print("Starting web server on port 8000...", file=sys.stderr)
    # Run as HTTP server instead of stdio
    mcp.run(transport='sse')