#!/bin/bash
# Docker Hub 배포 스크립트

# 설정
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-your-username}"
IMAGE_NAME="quant-trading-dashboard"
VERSION="${1:-latest}"

echo "=========================================="
echo "Docker Hub 배포 시작"
echo "=========================================="
echo "사용자명: ${DOCKERHUB_USERNAME}"
echo "이미지명: ${IMAGE_NAME}"
echo "버전: ${VERSION}"
echo "=========================================="

# Docker Hub 로그인 확인
if ! docker info | grep -q "Username"; then
    echo "Docker Hub에 로그인하세요:"
    echo "  docker login"
    exit 1
fi

# 이미지 빌드
echo "이미지 빌드 중..."
docker build -t ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION} .

if [ $? -ne 0 ]; then
    echo "빌드 실패!"
    exit 1
fi

# latest 태그도 추가
if [ "${VERSION}" != "latest" ]; then
    docker tag ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION} ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest
fi

# Docker Hub에 푸시
echo "Docker Hub에 푸시 중..."
docker push ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}

if [ "${VERSION}" != "latest" ]; then
    docker push ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest
fi

echo "=========================================="
echo "배포 완료!"
echo "=========================================="
echo "이미지: ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}"
echo ""
echo "AWS에서 실행:"
echo "  docker pull ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}"
echo "  docker run -d -p 8000:8000 --env-file .env ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}"
