# Smack - Message Storage Service

<img src="../../../assets/mcpengine-smack-demo.png" alt="MCPEngine Smack Demo" width="400">

Smack is a simple messaging service built on MCPEngine, demonstrating how to securely store and retrieve messages using PostgreSQL in a production-grade MCP environment.

## Overview

Smack shows how MCPEngine integrates OAuth 2.1 authentication and persistent storage to create a secure, scalable, and reliable messaging service. It highlights the importance of robust authentication in LLM workflows and how MCP can be extended beyond local toy demos.

> **Note:** For an overview of MCPEngine's architecture and why it matters, see the [MCPEngine repository](https://github.com/featureform/mcp-engine).

## Features

* **OAuth 2.1 Authentication**: Securely authenticate users before they can list or post messages
* **Persistent PostgreSQL Storage**: Messages are stored in a real database for reliability
* **Docker Containerization**: Easily spin up Smack and its dependencies with Docker Compose
* **Compatible with MCP Inspector & Claude Desktop**: Test locally or in production-like setups

## Prerequisites

* Docker and Docker Compose
* MCP Inspector (optional, for testing and interaction)
* npx (optional, for running the MCP Inspector via npx)

## Quick Start

Clone this repository and navigate to examples/smack:

```bash
git clone https://github.com/featureform/mcp-engine.git
cd mcp-engine/examples/smack
```

Start the service using Docker Compose:

```bash
docker-compose up --build
```

This will:
* Build and start the Smack server on http://localhost:8000
* Launch a PostgreSQL instance on port 5432
* Create necessary volumes for data persistence

Connect to the service in one of two ways:

### a) MCPEngine Proxy (Local Approach)

If you already have Claude Desktop or another stdio-based LLM client, you can locally run:

```bash
mcpengine proxy http://localhost:8000/sse
```

The command spawns a local process that listens for stdio MCP requests and forwards them to http://localhost:8000/sse. The proxy also handles OAuth interactions if your Smack server is configured for authentication.

### b) Using Docker Run in Claude Desktop

Alternatively, you can run the MCPEngine-Proxy container in Docker and configure Claude Desktop to point to it. Create or edit your config file at:

```bash
~/Library/Application Support/Claude/claude_desktop_config.json
```

Add the following:

```json
{
  "mcpServers": {
    "smack_mcp_server": {
      "command": "docker",
      "args": [
        "run",
        "-it",
        "--rm",
        "-p",
        "8181:8181",
        "featureformcom/mcpengine:latest",
        "-host",
        "localhost:8000",
        "-sse_path",
        "/sse",
        "-debug=false",
        "-client_id",
        "your_client_id",
        "-client_secret",
        "your_client_secret"
      ]
    }
  }
}
```

Claude Desktop sees a local stdio server, while Docker runs the MCPEngine-Proxy container. The proxy container listens on port 8181, connects to your Smack server at localhost:8000, and passes along OAuth credentials if required.

Restart Claude Desktop, and you should see "smack_mcp_server" in the list of available servers.

## Available Tools

### list_messages()

Retrieves all posted messages from the database.

Response Example:
```
1. Hello, world!
2. Another message
...
```

### post_message(message: str)

Posts a new message to the database.

Parameters:
* `message`: The textual content to post

Response:
* Success: "Message posted successfully: '...'"
* Failure: Returns an error message describing the issue



## Why Smack?

* **Security**: Demonstrates how OAuth 2.1 flows protect messaging endpoints
* **Scalability**: Runs on Docker with PostgreSQL for data persistence
* **Practical Example**: Illustrates how real-world services can adopt MCP (and MCPEngine) for secure AI-driven workflows

## Further Reading

* [MCPEngine Repository](https://github.com/featureform/mcp-engine)
* [Official MCP Specification](https://modelcontextprotocol.io)

## Questions or Feedback?

Join our [Slack community](https://join.slack.com/t/featureform-community/shared_invite/zt-xhqp2m4i-JOCaN1vRN2NDXSVif10aQg?mc_cid=80bdc03b3b&mc_eid=UNIQID) or open an issue! We're excited to see what you build with Smack and MCPEngine.
