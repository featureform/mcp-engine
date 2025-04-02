from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpengine import Context, MCPEngine


class Database:  # Replace with your actual DB type
    @classmethod
    async def connect(cls):
        return cls()

    async def disconnect(self):
        pass

    def query(self):
        return "Hello, World!"


# Create a named server
mcp = MCPEngine("My App")


@dataclass
class AppContext:
    db: Database


@asynccontextmanager
async def app_lifespan(server: MCPEngine) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""
    # Initialize on startup
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        # Cleanup on shutdown
        await db.disconnect()


# Pass lifespan to server
mcp = MCPEngine("My App", lifespan=app_lifespan)


# Access type-safe lifespan context in tools
@mcp.tool()
def query_db(ctx: Context) -> str:
    """Tool that uses initialized resources"""
    db = ctx.request_context.lifespan_context.db
    return db.query()
