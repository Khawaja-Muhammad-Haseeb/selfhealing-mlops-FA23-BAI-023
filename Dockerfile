# Dockerfile - containerizes the Flask sentiment API
# Used for BOTH the main (unstable) branch and the stable-fallback branch.
# Each branch has its own requirements.txt / app.py, so this same Dockerfile
# works for both images (unstable image is heavier because of torch/transformers).

FROM python:3.10-slim

WORKDIR /app

# Install OS deps needed by torch/transformers (only relevant on main branch,
# harmless on stable-fallback which has a tiny requirements.txt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Log directory used by app.py for persistence (mounted via PVC in k8s)
RUN mkdir -p /app/logs

EXPOSE 5000

CMD ["python", "app.py"]
