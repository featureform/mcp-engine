# SMACK - Message Storage Service

SMACK is a simple messaging service with a persistent message store using PostgreSQL. It's designed to work with the Model Context Protocol (MCP) Inspector for easy testing and interaction.

## Overview

SMACK is built on the MCP Engine, a secure implementation of the Model Context Protocol (MCP) with authentication support. While MCP standardizes interactions between AI models and external systems, early implementations lacked key features for security, scalability, and reliability. MCP Engine addresses these by integrating OAuth 2.1, ensuring secure and seamless communication.

SMACK serves as a practical demonstration of the MCP Engine's capabilities by providing a basic yet functional messaging service. It highlights the importance of authentication and provides a hands-on experience with secure AI interactions.

For a visual representation of the architecture and how SMACK integrates with the MCP Engine, please refer to the diagram below:


This diagram illustrates the flow of data and the role of authentication in ensuring secure interactions within the SMACK service.

We encourage you to explore SMACK to understand the critical role of authentication and scalability in MCP-based interactions and to experience firsthand the enhancements brought by the MCP Engine.

## Features

- Persistent message storage using PostgreSQL
- Docker containerization for easy deployment

## Prerequisites

- Docker and Docker Compose
- MCP Inspector (for testing and interaction)
- npx (optional)

## Quick Start

### 1. Clone the repository and navigate to the examples/smack directory

### 2. Start the service using Docker Compose:
   ```bash
   docker-compose up --build
   ```
   This will:
   - Build and start the SMACK server on port 8000
   - Start a PostgreSQL instance on port 5432
   - Create necessary volumes for data persistence

### 3. Connect to the service
    You can use our proxy server to connect SMACK to your client.
    Navigate to the proxy directory and build the main file:

    ```bash
    cd src/mcp/proxy
    go build main.go
    ```

   There are multiple ways to interact with SMACK:
   
   #### a. Using the MCP Inspector
   In a separate terminal run

   ```bash
   npx @modelcontextprotocol/inspector ./main <server-url> [log-file]
   ```
   In this case the server url is http://localhost:8000/sse and the log file can be a file of your choice, to which the logs will be written.

   This will open the MCP inspector in your browser where you can list the tools and interact with the server.
   
   #### b. Using Claude Desktop
   Create the config file if it doesn't exist:

   ```bash
   touch ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```
   Add the following to the file:
   ```json
    {
        "mcpServers": {
        "smack_mcp_server": {
        "command": "path/to/repo/mcp_engine/src/mcp/proxy/main",
        "args": [
            "http://localhost:8000/sse", <log-file>
        ]
    }
        }
    }
   ```

   Save the file and restart Claude Desktop. You should now see the SMACK server in the list of available servers. 
   You can now use Claude to send messages and list messages on SMACK.

   #### c. Writing your own MCP client

## Available Tools

### `list_messages()`
Retrieves all posted messages from the database.

**Response Format:**
```
1. sender: message content
2. sender: message content
...
```

### `post_message(message: str)`
Posts a new message to the database.

**Parameters:**
- `message`: The text content you want to post

**Response:**
- Success: "Message posted successfully: '{message}'"
- Failure: Error message if the post failed
