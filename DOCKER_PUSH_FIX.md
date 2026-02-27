# Docker Hub Push 오류 해결

## 오류 메시지
```
denied: requested access to the resource is denied
```

## 원인
1. Docker Hub에 로그인하지 않음
2. 로그인한 사용자명과 이미지 태그의 사용자명이 일치하지 않음
3. 리포지토리 권한 문제

## 해결 방법

### 방법 1: Docker Hub에 로그인 확인 및 재로그인

```powershell
# 현재 로그인 상태 확인
docker info | Select-String "Username"

# 로그아웃
docker logout

# 다시 로그인 (새 PowerShell 창에서)
docker login -u punkrockartist84@gmail.com
# 또는 Docker Hub 사용자명으로
docker login -u punkrockartist84
```

### 방법 2: 이미지 태그 확인

이미지 태그의 사용자명이 Docker Hub 로그인 사용자명과 일치해야 합니다:

```powershell
# 현재 이미지 확인
docker images | Select-String "quant-trading"

# 만약 사용자명이 다르다면 다시 태깅
docker tag kis-api_quant-trading:latest punkrockartist84/quant-trading-dashboard:latest
```

### 방법 3: Docker Hub에서 리포지토리 생성

1. https://hub.docker.com/ 접속
2. **Repositories** > **Create Repository** 클릭
3. Repository 이름: `quant-trading-dashboard`
4. Visibility: **Public** (무료) 또는 **Private** (무료 플랜 1개)
5. **Create** 클릭

### 방법 4: 전체 프로세스 재실행

```powershell
cd D:\Workspace\kis-api

# 1. 로그인 확인
docker login -u punkrockartist84

# 2. 이미지 빌드
docker build -t punkrockartist84/quant-trading-dashboard:latest .

# 3. 이미지 푸시
docker push punkrockartist84/quant-trading-dashboard:latest
```

## 확인 사항 체크리스트

- [ ] Docker Hub에 로그인했는가?
- [ ] 로그인한 사용자명이 `punkrockartist84`인가?
- [ ] 이미지 태그가 `punkrockartist84/quant-trading-dashboard:latest`인가?
- [ ] Docker Hub에 `quant-trading-dashboard` 리포지토리가 생성되어 있는가?
