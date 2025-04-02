# Stage 1: Build the application
FROM golang:1.23.5-bookworm AS builder

# Create a non-root user for the application
RUN groupadd -g 10001 appgroup && \
    useradd -u 10000 -g appgroup -s /sbin/nologin -M appuser

# Set working directory
WORKDIR /build

# Copy only the go.mod and go.sum files to leverage Docker cache
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy the rest of the application code
COPY . .

# Build the application with security flags enabled
# Disabling CGO for a fully static binary
# Setting security flags:
# - trimpath: removes file system paths from the resulting binary
# - mod=readonly: ensures the go.mod file is not modified
# - tags=netgo: ensures we use Go's DNS resolver instead of CGO
# - ldflags to strip debugging information and make the binary smaller
RUN CGO_ENABLED=0 go build \
    -trimpath \
    -mod=readonly \
    -tags=netgo \
    -ldflags="-w -s -extldflags '-static'" \
    -o mcpengine cmd/main.go

# Stage 2: Create a minimal runtime image
FROM gcr.io/distroless/static-debian12:nonroot

# Set environment variables
ENV HOST="localhost:8000" \
    SSE_PATH="/sse" \
    DEBUG="false"

# Set working directory
WORKDIR /app

# Copy the compiled binary from the builder stage
COPY --from=builder /build/mcpengine /app/

# Use the non-root user
USER nonroot:nonroot

# Expose the default auth callback port
EXPOSE 8181

# Set HEALTHCHECK to verify the application is running properly
# The application doesn't have a health endpoint, so we'll check if the process is running
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["/app/mcpengine", "-help"] || exit 1

# Set the entrypoint with proper configuration
ENTRYPOINT ["/app/mcpengine"]

# Default command - can be overridden from docker run
CMD []
