# Docker Hub 배포 및 AWS 실행 가이드

## 빠른 시작

### 1. Docker Hub에 이미지 업로드

```bash
# Docker Hub 로그인
docker login

# 환경 변수 설정 (선택)
export DOCKERHUB_USERNAME=your-username

# 배포 스크립트 실행
cd D:\Workspace\kis-api
bash deploy-to-dockerhub.sh

# 또는 수동으로
docker build -t your-username/quant-trading-dashboard:latest .
docker push your-username/quant-trading-dashboard:latest
```

### 2. AWS EC2에서 실행

```bash
# EC2 인스턴스에 SSH 접속
ssh -i your-key.pem ec2-user@your-ec2-ip

# Docker 설치 (Amazon Linux 2)
sudo yum update -y
sudo yum install docker -y
sudo service docker start
sudo usermod -a -G docker ec2-user

# 환경 변수 파일 생성
cat > .env << EOF
USE_DYNAMODB=true
DYNAMODB_TABLE_NAME=quant_trading_users
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
PYTHONUNBUFFERED=1
EOF

# Docker Hub에서 이미지 pull 및 실행
docker pull your-username/quant-trading-dashboard:latest
docker run -d \
  --name quant-trading-dashboard \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  your-username/quant-trading-dashboard:latest
```

### 3. 보안 그룹 설정

EC2 보안 그룹에서 포트 8000 인바운드 규칙 추가:
- Type: Custom TCP
- Port: 8000
- Source: 0.0.0.0/0 (또는 특정 IP)

### 4. 접속 확인

```
http://your-ec2-public-ip:8000
```

기본 계정: `admin` / `admin123`

---

## 상세 가이드

자세한 내용은 `DOCKER_HUB_DEPLOY.md` 파일을 참조하세요.
