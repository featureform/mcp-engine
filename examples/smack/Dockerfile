FROM python:3.10-slim

# Set working directory in the container
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

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
CMD ["python", "server.py"]