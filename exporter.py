"""
Custom Prometheus exporter for the Sentiment API.

Runs as a plain Python process on the EC2 host (NOT inside Minikube).
Polls the app's /api/latest-confidence endpoint every 5 seconds and
exposes the value as the Prometheus gauge `prediction_confidence_score`
on port 8000.

If the endpoint is unreachable, defaults to 1.0 (healthy / no drift).
"""

import os
import time
import requests
from prometheus_client import start_http_server, Gauge

# The app is reachable on the Minikube NodePort (32500) from the EC2 host.
# Override with the APP_URL env var if needed.
APP_URL = os.environ.get(
    "APP_URL", "http://localhost:32500/api/latest-confidence"
)
POLL_INTERVAL_SECONDS = 5
EXPORTER_PORT = 8000

prediction_confidence_score = Gauge(
    "prediction_confidence_score",
    "Latest prediction confidence score reported by the Sentiment API",
)


def poll_forever():
    while True:
        try:
            resp = requests.get(APP_URL, timeout=3)
            resp.raise_for_status()
            data = resp.json()
            confidence = float(data.get("confidence", 1.0))
        except Exception:
            confidence = 1.0

        prediction_confidence_score.set(confidence)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    start_http_server(EXPORTER_PORT)
    print(f"Exporter running on :{EXPORTER_PORT}, polling {APP_URL} every {POLL_INTERVAL_SECONDS}s")
    poll_forever()
