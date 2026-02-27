# Docker Hub 로그인 문제 해결

## 문제
Docker Desktop credential helper 오류:
```
user akito56 is not authorized to access punkrockartist84@gmail.com
```

## 해결 방법

### 방법 1: Docker Desktop에서 직접 로그인 (권장)

1. **Docker Desktop 열기**
2. **Settings (설정)** 클릭
3. **Resources > WSL Integration** 또는 **General** 탭으로 이동
4. **Sign in** 버튼 클릭
5. Docker Hub 계정으로 로그인

### 방법 2: PowerShell에서 수동 로그인

```powershell
# 1. config.json 파일 수정 (credential helper 비활성화)
$configPath = "$env:USERPROFILE\.docker\config.json"
$content = '{"credsStore":""}'
[System.IO.File]::WriteAllText($configPath, $content, [System.Text.UTF8Encoding]::new($false))

# 2. 새로운 PowerShell 창에서 직접 로그인
docker login -u punkrockartist84@gmail.com
# 비밀번호 입력

# 3. 로그인 확인
docker info | Select-String "Username"
```

### 방법 3: Access Token 사용 (더 안전)

1. **Docker Hub 웹사이트 접속**: https://hub.docker.com/
2. **Account Settings > Security > New Access Token** 클릭
3. Token 생성 (읽기/쓰기 권한)
4. PowerShell에서:
```powershell
echo "YOUR_ACCESS_TOKEN" | docker login -u punkrockartist84@gmail.com --password-stdin
```

### 방법 4: Docker Desktop 재시작

1. Docker Desktop 완전 종료
2. Docker Desktop 재시작
3. 다시 로그인 시도

## 로그인 확인

```powershell
docker info | Select-String "Username"
```

또는

```powershell
docker pull hello-world
```

## 로그인 후 이미지 푸시

```powershell
cd D:\Workspace\kis-api

# 이미지 빌드
docker build -t punkrockartist84/quant-trading-dashboard:latest .

# 이미지 푸시
docker push punkrockartist84/quant-trading-dashboard:latest
```

## 추가 문제 해결

### credential helper 완전 제거
```powershell
# config.json에서 credsStore 제거
$configPath = "$env:USERPROFILE\.docker\config.json"
$config = Get-Content $configPath | ConvertFrom-Json
$config.PSObject.Properties.Remove('credsStore')
$config | ConvertTo-Json | Set-Content $configPath
```

### Docker Desktop credential helper 재설정
1. Docker Desktop > Settings > General
2. "Use the WSL 2 based engine" 체크 해제 후 재시작
3. 다시 체크 후 재시작
