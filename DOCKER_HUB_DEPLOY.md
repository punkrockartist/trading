# Docker Hub 배포 및 AWS 실행 가이드

## 1. Docker Hub에 이미지 업로드

### 1.1 Docker Hub 계정 준비
1. [Docker Hub](https://hub.docker.com/)에 계정 생성
2. 로컬에서 Docker Hub 로그인:
```bash
docker login
```

### 1.2 이미지 빌드 및 태깅
```bash
cd D:\Workspace\kis-api

# 이미지 빌드 (Docker Hub 사용자명으로 태깅)
docker build -t YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest .

# 예시:
# docker build -t myusername/quant-trading-dashboard:latest .
```

### 1.3 Docker Hub에 푸시
```bash
# 이미지 푸시
docker push YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest

# 예시:
# docker push myusername/quant-trading-dashboard:latest
```

### 1.4 버전 태깅 (선택사항)
```bash
# 특정 버전으로 태깅
docker tag YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:v1.0.0
docker push YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:v1.0.0
```

---

## 2. AWS에서 이미지 실행

### 2.1 AWS EC2에서 실행

#### 2.1.1 EC2 인스턴스 준비
```bash
# EC2 인스턴스에 SSH 접속
ssh -i your-key.pem ec2-user@your-ec2-ip

# Docker 설치 (Amazon Linux 2)
sudo yum update -y
sudo yum install docker -y
sudo service docker start
sudo usermod -a -G docker ec2-user
# 로그아웃 후 다시 로그인 필요
```

#### 2.1.2 Docker Hub에서 이미지 Pull 및 실행
```bash
# Docker Hub에서 이미지 pull
docker pull YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest

# 환경 변수 파일 생성 (.env)
cat > .env << EOF
USE_DYNAMODB=true
DYNAMODB_TABLE_NAME=quant_trading_users
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_SESSION_TOKEN=
PYTHONUNBUFFERED=1
EOF

# Docker 컨테이너 실행
docker run -d \
  --name quant-trading-dashboard \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest
```

#### 2.1.3 보안 그룹 설정
- EC2 보안 그룹에서 포트 8000 인바운드 규칙 추가
- 소스: `0.0.0.0/0` (또는 특정 IP만 허용)

---

### 2.2 AWS ECS (Elastic Container Service)에서 실행

#### 2.2.1 ECS 작업 정의 (Task Definition) 생성

**task-definition.json:**
```json
{
  "family": "quant-trading-dashboard",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "quant-trading-dashboard",
      "image": "YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "USE_DYNAMODB",
          "value": "true"
        },
        {
          "name": "DYNAMODB_TABLE_NAME",
          "value": "quant_trading_users"
        },
        {
          "name": "AWS_DEFAULT_REGION",
          "value": "us-east-1"
        }
      ],
      "secrets": [
        {
          "name": "AWS_ACCESS_KEY_ID",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:quant-trading/aws-credentials"
        },
        {
          "name": "AWS_SECRET_ACCESS_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:quant-trading/aws-credentials"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/quant-trading-dashboard",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

#### 2.2.2 ECS 클러스터 및 서비스 생성
```bash
# AWS CLI로 작업 정의 등록
aws ecs register-task-definition --cli-input-json file://task-definition.json

# ECS 서비스 생성
aws ecs create-service \
  --cluster your-cluster-name \
  --service-name quant-trading-dashboard \
  --task-definition quant-trading-dashboard \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

---

### 2.3 AWS EKS (Elastic Kubernetes Service)에서 실행

#### 2.3.1 Kubernetes Deployment 생성

**deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: quant-trading-dashboard
spec:
  replicas: 1
  selector:
    matchLabels:
      app: quant-trading-dashboard
  template:
    metadata:
      labels:
        app: quant-trading-dashboard
    spec:
      containers:
      - name: quant-trading-dashboard
        image: YOUR_DOCKERHUB_USERNAME/quant-trading-dashboard:latest
        ports:
        - containerPort: 8000
        env:
        - name: USE_DYNAMODB
          value: "true"
        - name: DYNAMODB_TABLE_NAME
          value: "quant_trading_users"
        - name: AWS_DEFAULT_REGION
          value: "us-east-1"
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: aws-credentials
              key: access-key-id
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: aws-credentials
              key: secret-access-key
---
apiVersion: v1
kind: Service
metadata:
  name: quant-trading-dashboard-service
spec:
  selector:
    app: quant-trading-dashboard
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

#### 2.3.2 배포
```bash
# Kubernetes Secret 생성
kubectl create secret generic aws-credentials \
  --from-literal=access-key-id=YOUR_ACCESS_KEY \
  --from-literal=secret-access-key=YOUR_SECRET_KEY

# Deployment 적용
kubectl apply -f deployment.yaml

# 서비스 상태 확인
kubectl get services
```

---

## 3. AWS 자격 증명 관리 (보안)

### 3.1 IAM Role 사용 (권장)
- EC2: IAM Role을 EC2 인스턴스에 연결
- ECS: Task Role 사용
- EKS: Service Account와 IAM Role 연결

### 3.2 AWS Secrets Manager 사용
```bash
# Secret 생성
aws secretsmanager create-secret \
  --name quant-trading/aws-credentials \
  --secret-string '{"access-key-id":"YOUR_KEY","secret-access-key":"YOUR_SECRET"}'
```

---

## 4. 자동화 스크립트

### 4.1 배포 스크립트 (deploy.sh)
```bash
#!/bin/bash

DOCKERHUB_USERNAME="your-username"
IMAGE_NAME="quant-trading-dashboard"
VERSION="latest"

# 이미지 빌드
docker build -t ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION} .

# Docker Hub에 푸시
docker push ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}

echo "배포 완료: ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}"
```

### 4.2 AWS 배포 스크립트 (deploy-aws.sh)
```bash
#!/bin/bash

DOCKERHUB_USERNAME="your-username"
IMAGE_NAME="quant-trading-dashboard"
VERSION="latest"

# EC2에서 실행
ssh ec2-user@your-ec2-ip << EOF
  docker pull ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}
  docker stop quant-trading-dashboard || true
  docker rm quant-trading-dashboard || true
  docker run -d \
    --name quant-trading-dashboard \
    -p 8000:8000 \
    --env-file .env \
    --restart unless-stopped \
    ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}
EOF

echo "AWS 배포 완료"
```

---

## 5. CI/CD 파이프라인 (GitHub Actions 예시)

**.github/workflows/deploy.yml:**
```yaml
name: Build and Deploy

on:
  push:
    branches: [ main ]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Login to Docker Hub
        uses: docker/login-action@v1
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_PASSWORD }}
      
      - name: Build and push
        uses: docker/build-push-action@v2
        with:
          context: ./kis-api
          push: true
          tags: ${{ secrets.DOCKERHUB_USERNAME }}/quant-trading-dashboard:latest
      
      - name: Deploy to AWS EC2
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.AWS_EC2_HOST }}
          username: ec2-user
          key: ${{ secrets.AWS_EC2_SSH_KEY }}
          script: |
            docker pull ${{ secrets.DOCKERHUB_USERNAME }}/quant-trading-dashboard:latest
            docker stop quant-trading-dashboard || true
            docker rm quant-trading-dashboard || true
            docker run -d --name quant-trading-dashboard -p 8000:8000 --env-file .env --restart unless-stopped ${{ secrets.DOCKERHUB_USERNAME }}/quant-trading-dashboard:latest
```

---

## 6. 모니터링 및 로그

### 6.1 CloudWatch Logs (ECS/EKS)
- ECS: 로그 드라이버 설정으로 자동 전송
- EKS: Fluentd 또는 CloudWatch Logs Agent 사용

### 6.2 Health Check
```bash
# 헬스체크 확인
curl http://your-aws-ip:8000/api/system/status
```

---

## 7. 비용 최적화

### 7.1 EC2
- t3.micro 또는 t3.small 사용 (프리티어 가능)
- 스팟 인스턴스 고려

### 7.2 ECS Fargate
- 필요한 만큼만 리소스 할당
- Auto Scaling 설정

### 7.3 EKS
- Managed Node Groups 사용
- Cluster Autoscaler 설정

---

## 8. 보안 체크리스트

- [ ] Docker Hub 이미지 Private 설정 (선택)
- [ ] AWS 자격 증명을 환경 변수 대신 IAM Role 사용
- [ ] 보안 그룹에서 필요한 IP만 허용
- [ ] HTTPS 사용 (ALB/NLB + ACM)
- [ ] 정기적인 이미지 업데이트 및 보안 스캔
