# Self-Healing MLOps Pipeline — Deployment Guide

This guide walks through everything *not* covered by the code files (EC2 setup,
Jenkins config, Minikube, Prometheus/Grafana/Alertmanager, and the final
end-to-end test). Do these in order.

---

## STEP 0 — Find Your 3 Assigned Values

Open the grading CSV, find your row by Roll Number, and note:

| Field | Column | Used in |
|---|---|---|
| Confidence Threshold (e.g. `0.623`) | B | `alert.rules.yml`, Grafana panel |
| Stable Model Code (e.g. `A3F9`) | C | `stable-fallback/app.py` (x2) |
| Webhook Token (e.g. `ROLLBACK_4D2E1A_TOKEN`) | E | `alertmanager.yml`, Jenkins rollback trigger |

### Find & Replace checklist across this repo

| Placeholder | Replace with | Files |
|---|---|---|
| `YOUR_THRESHOLD` | your confidence threshold | `alert.rules.yml` |
| `stable-v0-XXXX` | `stable-v0-<your code>` | `stable-fallback/app.py` (2 places) |
| `YOUR_WEBHOOK_TOKEN` | your webhook token | `alertmanager.yml`, Jenkins rollback job |
| `<dockerhub-user>` | your DockerHub username | `Jenkinsfile`, `k8s/blue-deployment.yaml`, `k8s/green-deployment.yaml` |
| `<EC2-IP>` | your EC2 public IP | `alertmanager.yml` |
| `YOUR_JENKINS_USERNAME` / `YOUR_JENKINS_API_TOKEN` | your Jenkins creds | `alertmanager.yml` |
| `<your-roll-number>` | your roll number | GitHub repo name |

---

## PHASE 1 — Infrastructure & Version Control

### 1.1 Launch EC2

- AWS Console → EC2 → Launch Instance
- AMI: **Ubuntu Server 22.04 LTS**
- Instance type: **t2.large** (8 GB RAM minimum — DistilBERT needs it)
- Storage: bump to at least **30 GB** (Docker images + models add up fast)
- Security Group — open inbound TCP for:

| Port | Purpose |
|---|---|
| 22 | SSH |
| 8080 | Jenkins |
| 9090 | Prometheus |
| 9093 | Alertmanager |
| 3000 | Grafana |
| 8000 | Custom exporter |
| 32500 | App (Minikube NodePort) |

SSH in:
```bash
ssh -i your-key.pem ubuntu@<EC2-IP>
```

### 1.2 Create the GitHub Repo

```bash
# On GitHub: create a PUBLIC repo named selfhealing-mlops-<your-roll-number>

git init
git remote add origin https://github.com/<your-username>/selfhealing-mlops-<roll>.git

# main branch: everything except stable-fallback/ contents
git checkout -b main
git add app.py requirements.txt templates/ Dockerfile Dockerfile.test \
        Jenkinsfile Jenkinsfile.rollback exporter.py prometheus.yml \
        alert.rules.yml alertmanager.yml k8s/ tests/
git commit -m "Initial main branch: unstable app, pipeline, k8s, monitoring"
git push -u origin main

# stable-fallback branch: only stable app.py, requirements.txt, Dockerfile
git checkout --orphan stable-fallback
git rm -rf .
cp stable-fallback/app.py app.py
cp stable-fallback/requirements.txt requirements.txt
cp stable-fallback/Dockerfile Dockerfile
git add app.py requirements.txt Dockerfile
git commit -m "Stable fallback: rule-based sentiment API"
git push -u origin stable-fallback

git checkout main
```

> ⚠️ Make sure you edited `stable-fallback/app.py` (replacing `XXXX` with your
> code) **before** committing it to the `stable-fallback` branch.

### 1.3 Install Tools on EC2

```bash
sudo apt update && sudo apt upgrade -y

# --- Docker ---
sudo apt install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker   # or log out/in

# --- Java (required by Jenkins) ---
sudo apt install -y fontconfig openjdk-17-jre

# --- Jenkins ---
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key | sudo tee \
  /usr/share/keyrings/jenkins-keyring.asc > /dev/null
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc]" \
  "https://pkg.jenkins.io/debian-stable binary/" | sudo tee \
  /etc/apt/sources.list.d/jenkins.list > /dev/null
sudo apt update
sudo apt install -y jenkins
sudo usermod -aG docker jenkins
sudo systemctl enable --now jenkins
# Unlock: cat /var/lib/jenkins/secrets/initialAdminPassword

# --- Minikube + kubectl ---
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl

minikube start --driver=docker --memory=4096 --cpus=2

# Allow jenkins user to run kubectl/minikube (copy kubeconfig)
sudo mkdir -p /var/lib/jenkins/.kube /var/lib/jenkins/.minikube
sudo cp -r ~/.kube/* /var/lib/jenkins/.kube/
sudo cp -r ~/.minikube/* /var/lib/jenkins/.minikube/
sudo chown -R jenkins:jenkins /var/lib/jenkins/.kube /var/lib/jenkins/.minikube
# Edit /var/lib/jenkins/.kube/config so paths point to /var/lib/jenkins/.minikube/...
sudo sed -i "s|$HOME|/var/lib/jenkins|g" /var/lib/jenkins/.kube/config

# --- Grafana (apt) ---
sudo apt install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt update && sudo apt install -y grafana
sudo systemctl enable --now grafana-server
```

> 💡 To make `sentiment-api-service` on NodePort 32500 reachable from
> outside EC2, run `minikube tunnel` in a background `tmux`/`screen` session,
> OR simpler: use `socat` to forward the EC2 host port to the Minikube node:
> ```bash
> MINIKUBE_IP=$(minikube ip)
> tmux new -s nodeport -d "socat TCP-LISTEN:32500,fork,reuseaddr TCP:${MINIKUBE_IP}:32500"
> ```

---

## PHASE 2 — CI Pipeline (Jenkins, Docker, Selenium)

### 2.1 GitHub Webhook

GitHub repo → Settings → Webhooks → Add webhook
- Payload URL: `http://<EC2-IP>:8080/github-webhook/`
- Content type: `application/json`
- Events: just the **push** event

### 2.2 Jenkins Plugins & Credentials

Jenkins → Manage Jenkins → Plugins → install:
- **Docker Pipeline**
- **Generic Webhook Trigger**
- **Git**

Jenkins → Manage Jenkins → Credentials → Add:
- Kind: **Username with password**
- ID: `dockerhub-creds`
- Username/Password: your DockerHub login

### 2.3 Create `sentiment-ci-pipeline` job

- New Item → Pipeline → name **exactly** `sentiment-ci-pipeline`
- Build Triggers → check **GitHub hook trigger for GITScm polling**
- Pipeline → Definition: **Pipeline script from SCM**
  - SCM: Git, your repo URL, branch `*/main`
  - Script Path: `Jenkinsfile`

### 2.4 Create `rollback-to-stable` job

- New Item → Pipeline → name **exactly** `rollback-to-stable`
- Build Triggers → check **Generic Webhook Trigger**
  - Token: `YOUR_WEBHOOK_TOKEN`
- Pipeline → Definition: **Pipeline script from SCM**
  - Script Path: `Jenkinsfile.rollback`

Generate a Jenkins API token: Jenkins → your user → Configure → API Token →
Add new Token (save this for the submission form + `alertmanager.yml`
basic-auth).

---

## PHASE 3 — Blue-Green on Minikube

`k8s/blue-deployment.yaml`, `k8s/green-deployment.yaml`, `k8s/service.yaml`,
and `k8s/pvc.yaml` are already written for you (see repo). They get applied
automatically by the **Deploy to Minikube** Jenkins stage. Just make sure:

- You replaced `<dockerhub-user>` in both deployment YAMLs
- `service.yaml` selector starts as `slot: blue`

Manual sanity check after first pipeline run:
```bash
kubectl get pods
kubectl get deployments
kubectl get svc sentiment-api-service
```

---

## PHASE 4 — Monitoring on EC2 (Prometheus, Alertmanager, Grafana)

All of these run **on the EC2 host** (Prometheus/Alertmanager as Docker
containers with `--network host`, Grafana via apt, exporter as a plain
Python process) — **not inside Minikube**.

### 4.1 Run the exporter

```bash
cd ~/selfhealing-mlops
python3 -m venv venv && source venv/bin/activate
pip install prometheus-client requests

# APP_URL defaults to http://localhost:32500/api/latest-confidence
tmux new -s exporter -d "source venv/bin/activate && python3 exporter.py"

curl http://localhost:8000/metrics | grep prediction_confidence_score
```

### 4.2 Run Prometheus

```bash
mkdir -p ~/monitoring && cd ~/monitoring
cp ~/selfhealing-mlops/prometheus.yml .
cp ~/selfhealing-mlops/alert.rules.yml .   # with YOUR_THRESHOLD substituted

docker run -d --name prometheus --network host \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  -v $(pwd)/alert.rules.yml:/etc/prometheus/alert.rules.yml \
  prom/prometheus
```

Check: `http://<EC2-IP>:9090/targets` → `sentiment-ml-exporter` should be **UP**.

### 4.3 Run Alertmanager

```bash
cp ~/selfhealing-mlops/alertmanager.yml .   # with your IP/token/creds substituted

docker run -d --name alertmanager --network host \
  -v $(pwd)/alertmanager.yml:/etc/alertmanager/alertmanager.yml \
  prom/alertmanager --config.file=/etc/alertmanager/alertmanager.yml
```

Check: `http://<EC2-IP>:9093`

### 4.4 Configure Grafana

`http://<EC2-IP>:3000` (default login `admin`/`admin`)

1. Connections → Data sources → Add → **Prometheus** → URL `http://localhost:9090` → Save & Test
2. Dashboards → New Dashboard → name it exactly **`MLOps - Sentiment API Health`**
3. Add panel:
   - Query: `prediction_confidence_score`
   - Visualization: **Time series**
   - Add a threshold line (red) at **YOUR_THRESHOLD** (Panel → Field → Thresholds)

---

## PHASE 5 — End-to-End Self-Healing Test

Run these from your local machine or EC2, before submitting:

```bash
# 1. Confirm blue slot active
curl http://<EC2-IP>:32500/health
# Expected: "model_version": "unstable-v1"

# 2. Inject drift
curl -X POST http://<EC2-IP>:32500/inject-drift
# Expected: {"status": "drift_injected"}

# 3. Generate traffic so confidence drops below your threshold
for i in $(seq 1 10); do
  curl -s -X POST http://<EC2-IP>:32500/predict \
    -H 'Content-Type: application/json' -d '{"text":"Great product"}'
  sleep 2
done

# 4. Wait ~90s, then check Prometheus alerts
#    http://<EC2-IP>:9090/alerts -> ModelConfidenceDrift should be FIRING

# 5. Check Alertmanager received it
#    http://<EC2-IP>:9093

# 6. Check Jenkins rollback-to-stable job triggered
#    http://<EC2-IP>:8080/job/rollback-to-stable/

# 7. Confirm self-healing complete
curl http://<EC2-IP>:32500/health
# Expected: "model_version": "stable-v0-<your code>"
```

If step 7 doesn't show the stable version:
- Check `kubectl get svc sentiment-api-service -o yaml` — selector should now be `slot: green`
- Check Jenkins console output for `rollback-to-stable` for `kubectl patch` errors
- Confirm the rollback job's Generic Webhook Trigger token matches `alertmanager.yml` exactly

### To reset and re-test:
```bash
curl -X POST http://<EC2-IP>:32500/reset
kubectl patch service sentiment-api-service \
  -p '{"spec":{"selector":{"app":"sentiment-api","slot":"blue"}}}'
```

---

## Final Submission Checklist

- [ ] All 3 customization values match your CSV row exactly
- [ ] `selfhealing-mlops-<roll>` repo is public, both branches pushed
- [ ] Pipeline `sentiment-ci-pipeline` triggers on push and passes all 6 stages
- [ ] `rollback-to-stable` job exists with correct webhook token
- [ ] `http://<EC2-IP>:32500/health` reachable externally
- [ ] Prometheus target UP, Grafana dashboard named exactly `MLOps - Sentiment API Health`
- [ ] Full drift → alert → rollback loop completes in < 3 minutes
- [ ] Report (with screenshots + all scripts) ready for Dropbox submission
- [ ] Google Form submitted with EC2 IP, DockerHub username, Jenkins username/API token
- [ ] **Do not stop the EC2 instance before grading**
