FROM python:3.11-slim

WORKDIR /workspace

# Install system audio, build, and networking dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies for agent worker and shared backend services
COPY agent/requirements.txt ./agent_reqs.txt
COPY backend/requirements.txt ./backend_reqs.txt
RUN pip install --no-cache-dir -r agent_reqs.txt -r backend_reqs.txt

# Copy backend and agent application code
COPY backend/ /workspace/backend/
COPY agent/ /workspace/agent/

ENV PYTHONPATH=/workspace

CMD ["python", "-m", "agent.src.worker", "start"]
