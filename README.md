# MCPEngine

**Production-Grade Implementation of the Model Context Protocol (MCP)**

<img src="assets/logo.png" alt="MCPEngine Logo" width="400">

## Overview

**MCPEngine** is a production-grade, HTTP-first implementation of the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). It provides a secure, scalable, and modern framework for exposing data, tools, and prompts to Large Language Models (LLMs) via MCP.

We believe MCP can be the "**REST for LLMs**," enabling any application (Slack, Gmail, GitHub, etc.) to expose a standardized endpoint that LLMs can access without custom-coded integrations. **MCPEngine** is our contribution to making MCP robust enough for modern, cloud-native use cases.

## Key Features

- **Built-in OAuth** with Okta, Keycloak, Google SSO, etc.  
- **HTTP-first** design (SSE instead of just stdio)  
- **Scope-based Authorization** for tools, resources, and prompts  
- **Seamless bridging** for LLM hosts (like Claude Desktop) via a local proxy  
- **Full backwards-compatibility** with FastMCP and the official MCP SDK

## Architecture

MCPEngine uses a proxy-based architecture to integrate with LLM hosts like Claude Desktop:

```
┌───────────────┐     stdio     ┌─────────────────┐     HTTP/SSE     ┌───────────────┐
│  Claude Host  ├───────────────►  MCPProxy Local ├──────────────────► MCPEngine     │
│               │               │                 │                   │ Server        │
│               ◄───────────────┤ (runs locally) ◄──────────────────┬┤ (remote)      │
└───────────────┘               └─────────────────┘      OAuth 2.1   │└───────────────┘
                                                                     │
                                                        ┌────────────┴───────────┐
                                                        │ Identity Provider      │
                                                        │ (Okta, Keycloak, etc.) │
                                                        └────────────────────────┘
```

This architecture provides several advantages:
1. **Seamless integration** - Claude sees a local stdio-based process
2. **Security** - The proxy handles OAuth authentication flows
3. **Scalability** - The MCPEngine server can run anywhere (cloud, on-prem)
4. **Separation of concerns** - Authentication is handled independently from your business logic

## Installation

```bash
uv add "mcpengine[cli]"
# or
pip install "mcpengine[cli]"
```

Once installed, you can run the CLI tools:

```bash
mcpengine --help
```

## Quickstart

### Create a Server

```python
# server.py
from mcpengine import MCPEngine

mcp = MCPEngine("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    return f"Hello, {name}!"
```

### Claude Desktop Integration

If your server is at http://localhost:8000, you can start the proxy locally:

```bash
mcpengine proxy http://localhost:8000/sse
```

Claude Desktop sees a local stdio server, while the proxy handles any necessary OAuth or SSE traffic automatically.

## Core Concepts

### Authentication & Authorization

Enable OAuth and scopes:

```python
from mcpengine import MCPEngine, Context

mcp = MCPEngine(
    "SecureDemo",
    authentication_enabled=True,
    issuer_url="https://your-idp.example.com/realms/some-realm",
)

@mcp.auth(scopes=["calc:read"])
@mcp.tool()
def add(a: int, b: int, ctx: Context) -> int:
    ctx.info(f"User {ctx.user_id} with roles {ctx.roles} called add.")
    return a + b
```

Any attempt to call `add` requires the user to have `calc:read` scope. Without it, the server returns 401 Unauthorized, prompting a login flow if used via the proxy.

### Resources

`@mcp.resource("uri")`: Provide read-only context for LLMs, like a GET endpoint.

```python
@mcp.resource("config://app")
def get_config():
    return "Configuration Data"
```

### Tools

`@mcp.tool()`: LLM-invokable functions. They can have side effects or perform computations.

```python
@mcp.tool()
def send_email(to: str, body: str):
    return "Email Sent!"
```

### Prompts

`@mcp.prompt()`: Reusable conversation templates.

```python
@mcp.prompt()
def debug_prompt(error_msg: str):
    return f"Debug: {error_msg}"
```

### Images

Return images as first-class data:

```python
from mcpengine import Image
@mcp.tool()
def thumbnail(path: str) -> Image:
    ...
```

### Context

Each request has a Context:

- `ctx.user_id`: Authenticated user id
- `ctx.user_name`: Authenticated user name
- `ctx.roles`: User scopes/roles
- `ctx.info(...)`: Logging
- `ctx.read_resource(...)`: Access other resources

## Example Implementations

### SQLite Explorer

```python
import sqlite3
from mcpengine import MCPEngine, Context

mcp = MCPEngine(
    "SQLiteExplorer",
    authentication_enabled=True,
    issuer_url="https://your-idp.example.com/realms/some-realm",
)

@mcp.auth(scopes=["database:read"])
@mcp.tool()
def query_db(sql: str, ctx: Context) -> str:
    conn = sqlite3.connect("data.db")
    try:
        rows = conn.execute(sql).fetchall()
        ctx.info(f"User {ctx.user.id} executed query: {sql}")
        return str(rows)
    except Exception as e:
        return f"Error: {str(e)}"
```

### Echo Server

```python
@mcp.resource("echo://{msg}")
def echo_resource(msg: str):
    return f"Resource echo: {msg}"

@mcp.tool()
def echo_tool(msg: str):
    return f"Tool echo: {msg}"
```

## Smack - Message Storage Example

Smack is a simple messaging service example with PostgreSQL storage that demonstrates MCPEngine's capabilities with OAuth 2.1 authentication.

### Quick Start

1. Start the service using Docker Compose:

```bash
git clone https://github.com/featureform/mcp-engine.git
cd mcp-engine/examples/servers/smack
docker-compose up --build
```

2. Using Claude Desktop

Configure Claude Desktop to use Smack:

Manually:
```bash
touch ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Add to the file:

```json
{
    "mcpServers": {
        "smack_mcp_server": {
            "command": "docker",
            "args": [
                "run",
                "-p",
                "8181:8181",
                "-i",
                "--rm",
                "featureformcom/mcpengine-proxy",
                "http://localhost:8000/sse",
                "-client_id=client_id_optional",
                "-client_secret=client_secret_optional",
            ]
        }
    }
}
```

Via CLI:
```bash
mcpengine proxy http://localhost:8000
```

Smack provides two main tools:
- `list_messages()`: Retrieves all messages
- `post_message(message: str)`: Posts a new message

For more details, see the [Smack example code](https://github.com/featureform/mcp-engine/tree/main/examples/servers/smack).

## Roadmap

- Advanced Auth Flows
- Service Discovery
- Fine-Grained Authorization
- Observability & Telemetry
- Ongoing FastMCP Compatibility

## Contributing

We welcome feedback, issues, and pull requests. If you'd like to shape MCP's future, open an issue or propose changes on [GitHub](https://github.com/featureform/mcp-engine). We actively maintain MCPEngine to align with real-world enterprise needs.

## Community

Join our discussion on [Slack](https://join.slack.com/t/featureform-community/shared_invite/zt-xhqp2m4i-JOCaN1vRN2NDXSVif10aQg?mc_cid=80bdc03b3b&mc_eid=UNIQID) to share feedback, propose features, or collaborate.

## License

Licensed under the MIT License. See LICENSE for details.
