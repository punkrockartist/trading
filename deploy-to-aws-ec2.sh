#!/bin/bash
# AWS EC2 배포 스크립트

# 설정
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-your-username}"
IMAGE_NAME="quant-trading-dashboard"
VERSION="${1:-latest}"
EC2_HOST="${EC2_HOST:-ec2-user@your-ec2-ip}"
SSH_KEY="${SSH_KEY:-~/.ssh/your-key.pem}"

echo "=========================================="
echo "AWS EC2 배포 시작"
echo "=========================================="
echo "EC2 호스트: ${EC2_HOST}"
echo "이미지: ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}"
echo "=========================================="

# EC2에 SSH 접속하여 배포
ssh -i ${SSH_KEY} ${EC2_HOST} << EOF
  echo "Docker Hub에서 이미지 Pull 중..."
  docker pull ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}
  
  echo "기존 컨테이너 중지 및 제거..."
  docker stop quant-trading-dashboard 2>/dev/null || true
  docker rm quant-trading-dashboard 2>/dev/null || true
  
  echo "새 컨테이너 실행..."
  docker run -d \
    --name quant-trading-dashboard \
    -p 8000:8000 \
    --env-file .env \
    --restart unless-stopped \
    ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}
  
  echo "컨테이너 상태 확인..."
  docker ps | grep quant-trading-dashboard
  
  echo "로그 확인 (최근 20줄)..."
  docker logs --tail 20 quant-trading-dashboard
EOF

echo "=========================================="
echo "배포 완료!"
echo "=========================================="
echo "접속: http://${EC2_HOST#*@}:8000"
