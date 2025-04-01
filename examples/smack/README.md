# Smack - Message Storage Service

Smack is a simple messaging service with a persistent message store using PostgreSQL. It's designed to work with the Model Context Protocol (MCP) Inspector for easy testing and interaction.

## Features

- Persistent message storage using PostgreSQL
- Docker containerization for easy deployment

## Prerequisites

- Docker and Docker Compose
- MCP Inspector (for testing and interaction)

## Quick Start

1. Clone the repository and navigate to the examples/smack directory

2. Start the service using Docker Compose:
   ```bash
   docker compose up
   ```
   This will:
   - Build and start the Smack server on port 8000
   - Start a PostgreSQL instance on port 5432
   - Create necessary volumes for data persistence

There are multiple ways to test the server:
- Using the MCP Inspector (recommended for beginners)
- Using Claude Desktop
- Writing your own MCP client

3. Connect to the service using the MCP Inspector at `localhost:8000`

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
