# 퀀트 매매 시스템 (Quant Trading System)

KIS API를 활용한 자동화된 퀀트 매매 시스템입니다.

## 주요 기능

- 실시간 주식 시세 모니터링
- 자동화된 매매 전략 실행
- 리스크 관리 (손절/익절, 일일 손실 한도)
- 웹 대시보드 (모바일 최적화)
- 사용자 인증 (DynamoDB 지원)

## 기술 스택

- **Backend**: Python 3.12, FastAPI, Uvicorn
- **Database**: DynamoDB (사용자 관리)
- **API**: KIS API (한국투자증권)
- **Container**: Docker
- **Deployment**: Docker Hub, AWS EC2/ECS/EKS

## 빠른 시작

### 로컬 실행

```bash
cd domestic_stock
py -3.12 quant_dashboard_mobile.py
```

### Docker 실행

```bash
docker-compose up -d
```

### 접속

- URL: http://localhost:8000
- 기본 계정: `admin` / `admin123`

## 배포

### Docker Hub에 이미지 업로드

```bash
docker build -t akito56/quant-trading-dashboard:latest .
docker push akito56/quant-trading-dashboard:latest
```

### AWS에서 실행

```bash
docker pull akito56/quant-trading-dashboard:latest
docker run -d -p 8000:8000 --env-file .env akito56/quant-trading-dashboard:latest
```

## 문서

- [개발 워크플로우](DEVELOPMENT_WORKFLOW.md)
- [Docker Hub 배포 가이드](DOCKER_HUB_DEPLOY.md)
- [Docker 로그인 문제 해결](DOCKER_LOGIN_FIX.md)

## 라이선스

Private
