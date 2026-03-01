# Python 3.12 기반 이미지
FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필수 패키지 설치
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 파일 복사
COPY requirements.txt .

# Python 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# config 디렉토리 (kis_auth는 프로젝트 루트/config 사용)
RUN mkdir -p /app/config
COPY config/ /app/config/

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/domestic_stock

# 포트 노출
EXPOSE 8000

# 헬스체크 (선택)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/system/status', timeout=5)" || exit 1

# 애플리케이션 실행
# 방법 1: uvicorn 모듈로 실행
CMD ["python", "-m", "uvicorn", "domestic_stock.quant_dashboard_mobile:app", "--host", "0.0.0.0", "--port", "8000"]

# 방법 2: 직접 실행 (대안)
# WORKDIR /app/domestic_stock
# CMD ["python", "quant_dashboard_mobile.py"]
