FROM python:3.10-slim

# Set working directory in the container
WORKDIR /app

# Install uv and tomli for TOML parsing
RUN pip install --no-cache-dir uv tomli==2.0.1

# Copy pyproject.toml
COPY pyproject.toml .

# Install dependencies using uv with --system flag
RUN uv pip install --system --no-cache-dir .

# Copy the application code
COPY . .

# Expose port for the server
EXPOSE 8000

# Environment variables for PostgreSQL connection
ENV DB_HOST=postgres \
    DB_NAME=smack \
    DB_USER=postgres \
    DB_PASSWORD=postgres \
    DB_PORT=5432

# Command to run the web server
CMD ["python", "mcp_smack/server.py"]