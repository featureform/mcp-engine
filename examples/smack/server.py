#!/usr/bin/env python
"""
Smack Messaging Server

A FastMCP-based messaging service that provides message listing and posting capabilities.
"""
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from mcp.server.fastmcp import FastMCP, Context

from postgresDB import MessageDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("smack-server")


@dataclass
class AppContext:
    """Application context containing shared resources."""
    db: MessageDB


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Manage application lifecycle with type-safe context.
    
    Args:
        server: The FastMCP server instance
        
    Yields:
        AppContext: The application context with initialized resources
    """
    logger.info("Initializing application resources")
    db = MessageDB()
    try:
        yield AppContext(db=db)
    except Exception as e:
        logger.error(f"Error during application lifecycle: {e}")
        raise
    finally:
        logger.info("Shutting down application resources")
        try:
            await db.close_connection()
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")


mcp = FastMCP("smack", lifespan=app_lifespan)

@mcp.tool()
async def list_messages(ctx: Context) -> str:
    """
    List all messages from the database.
    
    Args:
        ctx: The request context
        
    Returns:
        str: Formatted list of messages or notification if no messages exist
    """
    logger.info("Handling list_messages request")
    try:
        app_ctx: AppContext = ctx.request_context.lifespan_context
        db: MessageDB = app_ctx.db
        messages = db.get_all_messages()
        
        if not messages:
            logger.info("No messages found in database")
            return "No messages available."
        
        message_list = []
        for i, message in enumerate(messages, 1):
            sender = message[1]
            content = message[2]
            message_list.append(f"{i}. {sender}: {content}")
        
        logger.info(f"Retrieved {len(messages)} messages successfully")
        return "\n".join(message_list)
    except Exception as e:
        logger.error(f"Error listing messages: {e}")
        return f"An error occurred while retrieving messages: {str(e)}"


@mcp.tool()
async def post_message(ctx: Context, sender: str, message: str) -> str:
    """
    Post a new message to the database.
    
    Args:
        ctx: The request context
        sender: The name of the message sender
        message: The content of the message
        
    Returns:
        str: Success or failure message
    """
    logger.info(f"Handling post_message request from {sender}")
    
    # Input validation
    if not sender or not sender.strip():
        logger.warning("Attempted to post message with empty sender")
    
    if not message or not message.strip():
        logger.warning(f"Attempted to post empty message from {sender}")
        return "Message content cannot be empty"

    app_ctx: AppContext = ctx.request_context.lifespan_context
    db: MessageDB = app_ctx.db
    success = db.add_message(sender, message)
    
    if success:
        logger.info(f"Message from {sender} posted successfully")
        return f"Message posted successfully: '{message}'"
    else:
        logger.error(f"Database operation failed when posting message from {sender}")
        return f"Failed to post message to database"


if __name__ == "__main__":
    try:
        logger.info("Starting Smack server")
        mcp.run(transport='sse')
    except KeyboardInterrupt:
        logger.info("Server shutdown requested via KeyboardInterrupt")
    except Exception as e:
        logger.critical(f"Unhandled exception in server: {e}")
        raise
