# GitHub Actions 실패 시 점검 사항

Actions가 전부 실패할 때 흔한 원인 두 가지입니다.

---

## 1. Docker Hub 로그인 실패 (가장 흔함)

워크플로에서 **Login to Docker Hub** 단계가 실패하면 이후 빌드/푸시가 모두 실패합니다.

**원인**: 저장소에 Docker Hub 비밀값이 없거나 잘못됨.

**조치**:
1. GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions**
2. 다음 시크릿이 있는지 확인:
   - `DOCKERHUB_USERNAME`: Docker Hub 로그인 아이디
   - `DOCKERHUB_TOKEN`: Docker Hub **Access Token** (비밀번호가 아님)
3. 토큰 생성: [Docker Hub → Account Settings → Security → New Access Token](https://hub.docker.com/settings/security)
4. 값이 없으면 두 시크릿 모두 추가한 뒤 워크플로 다시 실행

**그래도 "Username and password required"가 나올 때:**

- **포크에서 실행 중인지 확인**  
  포크(fork)한 저장소에서 Actions를 돌리면, **원본 저장소의 시크릿은 전달되지 않습니다.**  
  포크가 아니라 **본인 계정의 원본 저장소**에서 실행하거나, 포크라면 그 포크 저장소 Settings에서 시크릿을 따로 등록해야 합니다.

- **토큰 복사 시 공백/줄바꿈**  
  토큰을 붙여넣을 때 **앞뒤 공백**이나 **중간 줄바꿈**이 들어가면 로그인이 실패합니다.  
  메모장에 붙여넣고 공백·줄바꿈을 모두 지운 뒤, 한 줄만 복사해서 시크릿에 넣어보세요.

- **토큰 재발급**  
  위를 해도 안 되면 Docker Hub에서 **새 Access Token**을 만들고, 그 값으로 `DOCKERHUB_TOKEN`을 **삭제 후 다시 생성**해서 넣은 뒤 Re-run 해보세요.

- **시크릿 이름 철자**  
  `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (전부 대문자, HUB는 한 단어).  
  `DOCKER_HUB_*` 처럼 언더스코어가 들어가면 안 됩니다.

---

## 2. Docker 빌드 실패 (COPY config/ 실패)

**원인**: `config/` 디렉터리가 리포지터리에 없음.  
`config/kis_devlp.yaml`은 `.gitignore`로 제외되어 있어, 다른 파일이 없으면 `config/` 자체가 Git에 안 올라가고,  
Dockerfile의 `COPY config/ /app/config/` 단계에서 **file not found** 로 빌드가 실패합니다.

**조치**:  
`config/.gitkeep` 파일을 추가해 두었습니다. 이 파일을 커밋·푸시하면 `config/` 디렉터리가 빌드 컨텍스트에 포함되어 위 COPY 단계가 성공합니다.

```bash
git add config/.gitkeep
git commit -m "ci: add config/.gitkeep for Docker build context"
git push
```

---

## 3. 실제 실패 단계 확인 방법

GitHub 저장소 **Actions** 탭에서 실패한 런을 열고:

- **Set up Docker Buildx** 다음에 실패 → 보통 **Login to Docker Hub** 단계 (시크릿 점검)
- **Build and push** 단계에서 실패 → 로그에 `COPY failed` 등이 있으면 **config/** 또는 경로 이슈, 그 외는 `requirements.txt` / 네트워크 등

로그의 **에러 메시지**를 한 줄만 복사해 두면 원인 파악이 빠릅니다.
