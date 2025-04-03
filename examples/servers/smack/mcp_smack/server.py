#!/usr/bin/env python

# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

"""
Smack Messaging Server

A MCPEngine-based messaging service that provides
message listing and posting capabilities.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from db import MessageDB
from mcpengine import Context, MCPEngine

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
async def app_lifespan(server: MCPEngine) -> AsyncIterator[AppContext]:
    """
    Manage application lifecycle with type-safe context.

    Args:
        server: The MCPEngine server instance

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


mcp = MCPEngine(
    "smack",
    lifespan=app_lifespan,
    authentication_enabled=True,
    issuer_url="http://localhost:8080/realms/master",
)


@mcp.authorize(scopes=["messages:list"])
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


@mcp.authorize(scopes=["messages:post"])
@mcp.tool()
async def post_message(ctx: Context, message: str) -> str:
    """
    Post a new message to the database.

    Args:
        ctx: The request context, which includes authenticated user information
        message: The content of the message

    Returns:
        str: Success or failure message
    """
    sender = ctx.user_name
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
        return "Failed to post message to database"


def main():
    try:
        logger.info("Starting Smack server")
        logger.info("Connecting to database...")
        # Test database connection before starting the server
        db = MessageDB()
        try:
            # Test basic connection - will throw exception if connection fails
            db._get_connection()
            logger.info("Database connection established successfully")
        except Exception as e:
            logger.critical(f"Failed to establish database connection: {e}")
            logger.critical(
                "Please ensure the database is running and accessible. "
                "Check your environment variables:"
                "DATABASE_URL or DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD"
            )
            return 1
        finally:
            # Close the test connection
            db.close_connection()

        # Start the server
        mcp.run(transport="sse")
    except KeyboardInterrupt:
        logger.info("Server shutdown requested via KeyboardInterrupt")
    except Exception as e:
        logger.critical(f"Unhandled exception in server: {e}")
        return 1

    return 0
