pipeline {
    agent any

    environment {
        DOCKERHUB_CREDENTIALS = credentials('dockerhub-creds')
        IMAGE_NAME = "haseeb67786/sentiment-api"
        TEST_CONTAINER = "sentiment-api-test"
    }

    stages {

        stage('Fetch') {
            steps {
                checkout scm
            }
        }

        stage('Build and Run') {
            steps {
                sh '''
                    docker build -t sentiment-api:unstable .

                    docker rm -f ${TEST_CONTAINER} || true
                    docker run -d --name ${TEST_CONTAINER} --network host sentiment-api:unstable

                    echo "Waiting for the Flask app + DistilBERT model to come up..."
                    for i in $(seq 1 30); do
                        if curl -sf http://localhost:5000/health > /dev/null; then
                            echo "App is up!"
                            break
                        fi
                        sleep 5
                    done
                '''
            }
        }

        stage('Unit Test') {
            steps {
                sh '''
                    docker build -t sentiment-api-tests -f Dockerfile.test .
                    docker run --rm --network host \
                        -e BASE_URL=http://localhost:5000 \
                        sentiment-api-tests pytest tests/test_api.py -v
                '''
            }
        }

        stage('UI Test') {
            steps {
                sh '''
                    docker run --rm --network host \
                        -e BASE_URL=http://localhost:5000 \
                        sentiment-api-tests pytest tests/test_ui.py -v
                '''
            }
        }

        stage('Build and Push') {
            steps {
                sh '''
                    echo "$DOCKERHUB_CREDENTIALS_PSW" | docker login -u "$DOCKERHUB_CREDENTIALS_USR" --password-stdin

                    # --- Unstable (main branch / blue slot) ---
                    docker build -t ${IMAGE_NAME}:unstable .
                    docker push ${IMAGE_NAME}:unstable

                    # --- Stable (stable-fallback branch / green slot) ---
                    rm -rf stable-build
                    git clone -b stable-fallback "$(git config --get remote.origin.url)" stable-build
                    docker build -t ${IMAGE_NAME}:stable ./stable-build
                    docker push ${IMAGE_NAME}:stable
                '''
            }
        }

        stage('Deploy to Minikube') {
            steps {
                sh '''
                    kubectl apply -f k8s/pvc.yaml
                    kubectl apply -f k8s/blue-deployment.yaml
                    kubectl apply -f k8s/green-deployment.yaml
                    kubectl apply -f k8s/service.yaml

                    kubectl rollout status deployment/sentiment-blue-deployment --timeout=180s
                    kubectl rollout status deployment/sentiment-green-deployment --timeout=180s
                '''
            }
        }
    }

    post {
        always {
            sh 'docker rm -f ${TEST_CONTAINER} || true'
        }
    }
}
