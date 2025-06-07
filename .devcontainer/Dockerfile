# Use the official Python image as a base
FROM mcr.microsoft.com/devcontainers/python:3.12

# Install fish shell and uv
RUN apt update && pip install uv && apt clean && rm -rf /var/lib/apt/lists/*

# Set up workspace directory
WORKDIR /workspaces/dirdigest

# We'll run setup as a post-create command instead of during build
