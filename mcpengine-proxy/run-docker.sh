#!/bin/bash
set -e

# Default values
HOST=${HOST:-"localhost:8000"}
SSE_PATH=${SSE_PATH:-"/sse"}
DEBUG=${DEBUG:-"false"}
CLIENT_ID=${CLIENT_ID:-""}
CLIENT_SECRET=${CLIENT_SECRET:-""}

# Help function
show_help() {
  echo "Usage: ./run-docker.sh [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --host HOST                    The hostname (default: localhost:8000)"
  echo "  --sse-path PATH                SSE path (default: /sse)"
  echo "  --debug                        Enable debug mode"
  echo "  --client-id ID                 OAuth Client ID"
  echo "  --client-secret SECRET         OAuth Client Secret"
  echo "  --build                        Build the image before running"
  echo "  --help                         Show this help message"
  echo ""
  echo "Example:"
  echo "  ./run-docker.sh --host api.example.com:8080 --debug --client-id abc123"
}

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --sse-path)
      SSE_PATH="$2"
      shift 2
      ;;
    --debug)
      DEBUG="true"
      shift
      ;;
    --client-id)
      CLIENT_ID="$2"
      shift 2
      ;;
    --client-secret)
      CLIENT_SECRET="$2"
      shift 2
      ;;
    --build)
      BUILD=true
      shift
      ;;
    --help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

# Build the image if requested
if [ "$BUILD" = true ]; then
  echo "Building Docker image..."
  docker build -t mcpengine:latest .
fi

# Run the container with parsed arguments
echo "Running MCPEngine with:"
echo "  Host: $HOST"
echo "  SSE Path: $SSE_PATH"
echo "  Debug: $DEBUG"
echo "  Client ID: ${CLIENT_ID:0:3}..." # Show only first 3 chars for security
echo ""

docker run -it --rm \
  -p 8181:8181 \
  mcpengine:latest \
  -host "$HOST" \
  -sse_path "$SSE_PATH" \
  -debug="$DEBUG" \
  -client_id "$CLIENT_ID" \
  -client_secret "$CLIENT_SECRET"
