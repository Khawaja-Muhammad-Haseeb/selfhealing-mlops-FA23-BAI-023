import os
import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")


def test_health_endpoint():
    resp = requests.get(f"{BASE_URL}/health", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "model_version" in data


def test_predict_returns_label_and_confidence():
    resp = requests.post(
        f"{BASE_URL}/predict",
        json={"text": "I absolutely love this product, it's wonderful!"},
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["label"] in ["POSITIVE", "NEGATIVE"]
    assert 0 <= data["confidence"] <= 1
    assert "model_version" in data


def test_predict_negative_text():
    resp = requests.post(
        f"{BASE_URL}/predict",
        json={"text": "This is the worst, most terrible experience ever."},
        timeout=30,
    )
    assert resp.status_code == 200


def test_health_returns_model_version_unstable():
    resp = requests.get(f"{BASE_URL}/health", timeout=10)
    data = resp.json()
    assert data["model_version"] == "unstable-v1"
