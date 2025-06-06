# Use the official Python image as a base
FROM mcr.microsoft.com/devcontainers/python:3.11

# Install fish shell and uv
RUN apt-get update \
    && apt-get install -y fish \
    && pip install uv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace directory
WORKDIR /workspaces/dirdigest

# We'll run setup as a post-create command instead of during build
