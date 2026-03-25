# Use the official uv image with Python 3.12
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install ALL system dependencies in one layer (rarely changes)
# We install nmap, sqlmap, and dirsearch as they are commonly used by skills.
# Playwright browser dependencies are included for browser-based agent features.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    nmap \
    sqlmap \
    dirsearch \
    ca-certificates \
    # Playwright browser dependencies
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Enable bytecode compilation to improve startup time
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first (cache layer for dependencies)
COPY pyproject.toml uv.lock ./

# Copy project code (needed for setuptools to find src/ directory)
COPY src/ ./src/
COPY README.md ./

# Install Python dependencies and project (cache layer - only changes when deps change)
RUN uv sync --frozen

# Install Playwright browsers (cache layer - heavy download, only changes when playwright updates)
RUN uv run playwright install chromium

# Copy the rest of the application code (configs, skills, etc. - changes frequently)
COPY . .

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
