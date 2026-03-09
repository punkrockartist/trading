# 서버에서 docker-compose 실행

서버에 `kis-api` 폴더만 있고 `docker-compose.yml`이 없을 때 사용.

## 서버 디렉터리 구조 (목표)

```
~/kis-api/
├── docker-compose.yml   ← 여기 있어야 함
└── config/
    ├── .env
    └── kis_devlp.yaml
```

## 1) docker-compose.yml 넣기

**방법 A – 로컬에서 서버로 복사**

```bash
scp deploy/docker-compose.yml ubuntu@서버IP:~/kis-api/
```

**방법 B – 서버에서 직접 만들기**

```bash
cd ~/kis-api
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  quant-trading:
    image: akito56/quant-trading-dashboard:latest
    container_name: quant-trading-dashboard
    env_file: config/.env
    ports:
      - "8000:8000"
    environment:
      - PYTHONUNBUFFERED=1
      - PYTHONPATH=/app:/app/domestic_stock
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    restart: unless-stopped
    networks:
      - quant-trading-network

networks:
  quant-trading-network:
    driver: bridge
EOF
```

## 2) 실행

```bash
cd ~/kis-api
docker-compose up -d
```

## 3) 확인

```bash
docker-compose ps
# 브라우저: http://서버IP:8000
```

`.env`는 `config/.env` 그대로 두면 됩니다 (compose에서 `env_file: config/.env`로 읽음).
