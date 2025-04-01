FROM python:3.10-slim

# Set working directory in the container
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create a volume for persistent database storage
VOLUME /app/data

# Modify db.py to use the volume path
RUN sed -i 's|/Users/riddhibagadiaa/Documents/smack-mcp-server/messages.db|/app/data/messages.db|g' db.py

# Expose port for the server
EXPOSE 8000

# Command to run the web server
CMD ["python", "server.py"]