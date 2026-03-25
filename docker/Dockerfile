# Use the official uv image with Python 3.12
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install system dependencies and security tools
# We install nmap, sqlmap, and dirsearch as they are commonly used by skills.
# ca-certificates is needed for HTTPS requests.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    nmap \
    sqlmap \
    dirsearch \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Enable bytecode compilation to improve startup time
ENV UV_COMPILE_BYTECODE=1

# Copy only the dependency files first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install project dependencies using uv
# --frozen ensures we use the exact versions from uv.lock
# --no-install-project skips installing the current project as a package for now
RUN uv sync --frozen --no-install-project

# Install Playwright browsers and their system dependencies
# This is required for the browser-based agent features.
# We only install chromium to keep the image size reasonable.
RUN uv run playwright install --with-deps chromium

# Copy the rest of the application code
COPY . .

# Install the project itself
RUN uv sync --frozen

# Create directories for persistent data and artifacts
RUN mkdir -p /app/data /app/artifacts /app/configs

# Expose the web UI port (default 8000)
EXPOSE 8000

# Set default environment variables
# These can be overridden in docker-compose.yml or at runtime
ENV AUTOSONGSHU_DATABASE_URL=sqlite:////app/data/autosongshu.db
ENV AUTOSONGSHU_ARTIFACT_DIR=/app/artifacts
ENV AUTOSONGSHU_SKILLS_DIRECTORIES=/app/skills
ENV AUTOSONGSHU_DEFAULT_CONFIG_PATH=/app/configs/pentest.example.yaml
ENV HOST=0.0.0.0
ENV PORT=8000
ENV AUTOSONGSHU_BROWSER_HEADLESS=true

# Default command to run the web application
CMD ["uv", "run", "autosongshu-web", "--host", "0.0.0.0", "--port", "8000"]
