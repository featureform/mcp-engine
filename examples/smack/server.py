#!/usr/bin/env python
from mcp.server.fastmcp import FastMCP
from postgresDB import MessagePostgresDB
import time

mcp = FastMCP("smack")

# Global database instance
db_instance = None

def get_db():
    """Get the database instance, creating it if needed."""
    global db_instance
    if db_instance is None:
        db_instance = MessagePostgresDB()
    return db_instance

@mcp.tool()
async def list_messages():
    db = MessagePostgresDB()
    # db = get_db()
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
async def post_message(message: str):
    SENDER_NAME = "user"
    db = MessagePostgresDB()
    # db = get_db()
    success = db.add_message(SENDER_NAME, message)
    if success:
        return f"Message posted successfully: '{message}'"
    else:
        return f"Failed to post message to database: {success}"

def wait_for_postgres():
    """Wait for PostgreSQL to be ready before starting the server."""
    max_retries = 30
    retry_interval = 2
    
    print("Checking PostgreSQL connection...")
    for i in range(max_retries):
        try:
            # Try to create the database instance and test a simple query
            db = MessagePostgresDB()
            db.get_all_messages()  # Test query
            print("PostgreSQL connection successful!")
            return True
        except Exception as e:
            print(f"Waiting for PostgreSQL... Attempt {i+1}/{max_retries} ({str(e)})")
            time.sleep(retry_interval)
    
    print("Failed to connect to PostgreSQL after multiple attempts")
    return False

if __name__ == "__main__":

    # try:
    #     # Initialize the database connection
    #     if wait_for_postgres():
    #         # This will happen only once due to the singleton pattern
    #         db_instance = MessagePostgresDB()
    #         print("Database initialized successfully")
    #     else:
    #         print("Warning: Could not initialize database")
    # except Exception as e:
    #     print(f"Error during database initialization: {e}")

    mcp.run(transport='sse')