# MCPEngine Proxy

A proxy for MCPEngine that handles authentication and communication.

## Docker Setup

### Prerequisites

- Docker 20.10.0 or higher
- Docker Compose v2.0.0 or higher

### Building and Running with Docker

1. **Build the Docker image:**

   ```bash
   docker build -t mcpengine:latest .
   ```

2. **Run with Docker:**

   You can run the container using either environment variables or command-line arguments:

   **Using environment variables:**
   ```bash
   docker run -it --rm \
     -p 8181:8181 \
     -e HOST=localhost:8000 \
     -e SSE_PATH=/sse \
     -e DEBUG=false \
     -e CLIENT_ID=your_client_id \
     -e CLIENT_SECRET=your_client_secret \
     mcpengine:latest
   ```

   **Using command-line arguments (recommended):**
   ```bash
   docker run -it --rm -p 8181:8181 mcpengine:latest \
     -host localhost:8000 \
     -sse_path /sse \
     -debug=false \
     -client_id your_client_id \
     -client_secret your_client_secret
   ```

3. **Using Docker Compose:**

   Create a `.env` file with your configuration:

   ```
   HOST=localhost:8000
   SSE_PATH=/sse
   DEBUG=false
   CLIENT_ID=your_client_id
   CLIENT_SECRET=your_client_secret
   ```

   Then run:

   ```bash
   docker-compose up -d
   ```

4. **Using the convenience script:**

   A shell script is provided for easier execution:

   ```bash
   # Make the script executable first
   chmod +x run-docker.sh
   
   # Run with default settings
   ./run-docker.sh
   
   # Run with custom options
   ./run-docker.sh --host api.example.com:8080 --debug --client-id abc123 --client-secret xyz789
   
   # Build the image before running
   ./run-docker.sh --build --host localhost:9000
   ```

## Configuration Options

| Parameter       | Description                                   | Default       |
|-----------------|-----------------------------------------------|---------------|
| HOST            | The hostname for connections                  | localhost:8000|
| SSE_PATH        | Path to append to hostname for SSE connection | /sse          |
| DEBUG           | Enable debug logging                          | false         |
| CLIENT_ID       | OAuth client ID                               | (required for auth) |
| CLIENT_SECRET   | OAuth client secret                           | (required for auth) |

## Security Considerations

- The application runs as a non-root user in the container
- The container is built using a minimal distroless base image
- The Go binary is statically compiled with security flags

## Health Monitoring

The container includes a health check that verifies the application is functioning properly. You can monitor the container health with:

```bash
docker inspect --format='{{.State.Health.Status}}' mcpengine
```

## Logging

Logs can be viewed with:

```bash
docker logs mcpengine
```

Or when using Docker Compose:

```bash
docker-compose logs mcpengine
```
