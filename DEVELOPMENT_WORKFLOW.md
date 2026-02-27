# 개발 및 배포 워크플로우

## 현재 방식 (수동 배포)

```
로컬 PC
  ↓ (소스 수정)
GitHub (소스 코드 저장)
  ↓ (수동)
로컬 PC에서 Docker 빌드
  ↓ (docker push)
Docker Hub (이미지 저장)
  ↓ (수동)
AWS 서버에서 docker pull
  ↓
AWS 서버에서 docker run
```

### 단계별 설명

1. **로컬 개발**
   ```bash
   # 소스 코드 수정
   cd D:\Workspace\kis-api
   # 파일 수정...
   ```

2. **GitHub에 소스 코드 푸시**
   ```bash
   git add .
   git commit -m "기능 추가"
   git push origin main
   ```

3. **Docker 이미지 빌드 및 푸시**
   ```bash
   cd D:\Workspace\kis-api
   docker build -t akito56/quant-trading-dashboard:latest .
   docker push akito56/quant-trading-dashboard:latest
   ```

4. **AWS 서버에서 배포**
   ```bash
   # EC2에 SSH 접속
   ssh ec2-user@your-ec2-ip
   
   # 최신 이미지 pull
   docker pull akito56/quant-trading-dashboard:latest
   
   # 기존 컨테이너 중지 및 제거
   docker stop quant-trading-dashboard
   docker rm quant-trading-dashboard
   
   # 새 컨테이너 실행
   docker run -d \
     --name quant-trading-dashboard \
     -p 8000:8000 \
     --env-file .env \
     --restart unless-stopped \
     akito56/quant-trading-dashboard:latest
   ```

---

## 개선된 방식 (자동화 배포)

### 옵션 1: GitHub Actions를 통한 자동 빌드 및 푸시

GitHub에 코드를 푸시하면 자동으로 Docker Hub에 이미지가 업로드됩니다.

**.github/workflows/docker-build-push.yml:**
```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2
      
      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      
      - name: Build and push
        uses: docker/build-push-action@v4
        with:
          context: ./kis-api
          push: true
          tags: |
            akito56/quant-trading-dashboard:latest
            akito56/quant-trading-dashboard:${{ github.sha }}
          cache-from: type=registry,ref=akito56/quant-trading-dashboard:buildcache
          cache-to: type=registry,ref=akito56/quant-trading-dashboard:buildcache,mode=max
```

**GitHub Secrets 설정:**
- `DOCKERHUB_USERNAME`: `akito56`
- `DOCKERHUB_TOKEN`: Docker Hub Access Token

### 옵션 2: GitHub Actions + AWS 자동 배포

코드 푸시 → Docker Hub 업로드 → AWS 자동 배포

**.github/workflows/deploy.yml:**
```yaml
name: Build, Push and Deploy

on:
  push:
    branches: [ main ]

jobs:
  build-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build and push to Docker Hub
        uses: docker/build-push-action@v4
        with:
          context: ./kis-api
          push: true
          tags: akito56/quant-trading-dashboard:latest
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
  
  deploy-aws:
    needs: build-push
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to AWS EC2
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.AWS_EC2_HOST }}
          username: ec2-user
          key: ${{ secrets.AWS_EC2_SSH_KEY }}
          script: |
            docker pull akito56/quant-trading-dashboard:latest
            docker stop quant-trading-dashboard || true
            docker rm quant-trading-dashboard || true
            docker run -d \
              --name quant-trading-dashboard \
              -p 8000:8000 \
              --env-file .env \
              --restart unless-stopped \
              akito56/quant-trading-dashboard:latest
```

---

## 권장 워크플로우

### 개발 환경별 분리

```
로컬 개발
  ↓
GitHub (develop 브랜치)
  ↓
GitHub Actions → Docker Hub (develop 태그)
  ↓
테스트 서버 배포 (수동 또는 자동)

로컬 개발 완료
  ↓
GitHub (main 브랜치)
  ↓
GitHub Actions → Docker Hub (latest 태그)
  ↓
프로덕션 서버 자동 배포
```

### 브랜치 전략

- **develop**: 개발 중인 기능
- **main**: 프로덕션 배포 준비 완료
- **feature/xxx**: 새로운 기능 개발

### 태그 전략

- `latest`: 최신 프로덕션 버전
- `v1.0.0`: 특정 버전 (시맨틱 버전)
- `develop`: 개발 버전
- `${{ github.sha }}`: 커밋 해시 (고유 버전)

---

## 배포 스크립트 자동화

### AWS 배포 스크립트 (deploy-aws.sh)

```bash
#!/bin/bash
# AWS EC2 자동 배포 스크립트

IMAGE="akito56/quant-trading-dashboard:latest"
EC2_HOST="ec2-user@your-ec2-ip"
SSH_KEY="~/.ssh/your-key.pem"

echo "배포 시작: ${IMAGE}"

ssh -i ${SSH_KEY} ${EC2_HOST} << EOF
  echo "최신 이미지 Pull 중..."
  docker pull ${IMAGE}
  
  echo "기존 컨테이너 중지..."
  docker stop quant-trading-dashboard 2>/dev/null || true
  docker rm quant-trading-dashboard 2>/dev/null || true
  
  echo "새 컨테이너 실행..."
  docker run -d \
    --name quant-trading-dashboard \
    -p 8000:8000 \
    --env-file .env \
    --restart unless-stopped \
    ${IMAGE}
  
  echo "배포 완료!"
  docker ps | grep quant-trading-dashboard
EOF
```

---

## 비교: 수동 vs 자동화

| 항목 | 수동 배포 | 자동화 배포 |
|------|----------|------------|
| **소스 푸시** | GitHub | GitHub |
| **Docker 빌드** | 로컬에서 수동 | GitHub Actions 자동 |
| **Docker Hub 푸시** | 수동 | 자동 |
| **AWS 배포** | SSH 접속 후 수동 | 자동 또는 원클릭 |
| **시간** | 5-10분 | 1-2분 |
| **실수 가능성** | 높음 | 낮음 |
| **롤백** | 수동 | 자동화 가능 |

---

## 권장 사항

### 초기 단계 (현재)
- ✅ 수동 배포로 시작
- ✅ 프로세스 이해
- ✅ 배포 스크립트 작성

### 성장 단계
- ✅ GitHub Actions로 자동 빌드/푸시
- ✅ 수동 배포 (AWS)

### 성숙 단계
- ✅ 완전 자동화 (CI/CD)
- ✅ 테스트 자동화
- ✅ 롤백 자동화

---

## 다음 단계

1. **GitHub Actions 설정** (옵션 1)
2. **배포 스크립트 작성** (deploy-aws.sh)
3. **환경별 분리** (develop/production)
4. **모니터링 설정** (CloudWatch 등)
