# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.

FROM public.ecr.aws/lambda/python:3.12

# Set working directory in the container
WORKDIR /var/task

# Install uv
RUN pip install --no-cache-dir uv

# Copy application code
COPY . .

# Install dependencies using uv with --system flag
RUN uv pip install --system --no-cache-dir .

# Expose port for the server
EXPOSE 8000

# Command to run the web server
CMD ["weather.server.handler"]
