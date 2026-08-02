FROM python:3.12-slim

LABEL description="MyHarness sandbox — isolated environment for skill mutation testing"
LABEL phase="phase2-isolation-only"

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /sandbox

# Copy project source
COPY pyproject.toml /sandbox/pyproject.toml
COPY src/ /sandbox/src/
COPY tests/ /sandbox/tests/

# Install in editable mode (no browser extras, no dev tools)
RUN pip install --no-cache-dir -e /sandbox

# Benchmark directory is mounted read-only at runtime
# (see docker-compose.yml volume mount)

# Entry point: run benchmarks only, never the API server
COPY sandbox/run_benchmark.py /sandbox/run_benchmark.py

ENTRYPOINT ["python", "/sandbox/run_benchmark.py"]
