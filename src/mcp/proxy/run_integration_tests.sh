#!/bin/bash

# This script runs the integration tests against a running MCP server
# The server should be running on http://localhost:8000/sse

# Build the proxy binary if it doesn't exist
if [ ! -f ./stdiosseproxy ]; then
    echo "Building stdiosseproxy binary..."
    go build -o stdiosseproxy .
fi

# Set the environment variable to enable integration tests
export RUN_INTEGRATION_TESTS=1

# Run the integration tests with verbose output
echo "Running integration tests..."
go test -v ./integration

# Reset the environment variable
unset RUN_INTEGRATION_TESTS

echo "Integration tests completed."
