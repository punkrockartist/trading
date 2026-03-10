# 퀀트 매매 시스템 — 포트폴리오 문서

국내 주식 실시간 틱 기반 자동매매 시스템. KIS(한국투자증권) API·WebSocket 연동, 리스크 관리·종목 선정·승인/자동 체결을 하나의 웹 대시보드에서 운영할 수 있도록 구성했다.

---

## 1. 아키텍처

### 1.1 전체 구성도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         클라이언트 (브라우저)                              │
│  로그인 · 대시보드 UI · 설정 · 승인대기 · 거래내역 · WebSocket 실시간 수신   │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ HTTPS / WSS
┌───────────────────────────────────▼─────────────────────────────────────┐
│                     FastAPI (quant_dashboard)                      │
│  · REST API (quant_dashboard_api)                                 │
│  · JWT 인증 · 설정 CRUD · 종목 선정 · 시스템 시작/중지 · 성과 내보내기      │
│  · WebSocket 브로드캐스트 (상태·포지션·로그)                               │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│                        매매 엔진 (백그라운드 스레드)                        │
│  quant_trading_safe: create_safe_on_result() → WebSocket 틱 수신          │
│  · QuantStrategy: MA 신호 · RiskManager: 한도·손절/익절·포지션            │
│  · safe_execute_order(): 주문 실행 · reconcile: 체결 반영                 │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  KIS REST API │         │ KIS WebSocket   │         │  AWS DynamoDB   │
│  주문·잔고·   │         │ 실시간 호가/체결 │         │  사용자 설정 ·   │
│  체결·지수·   │         │ (domestic_stock_ │         │  성과 저장       │
│  등락률       │         │  functions_ws)   │         │  (선택)         │
└───────────────┘         └─────────────────┘         └─────────────────┘
        │                           │
        └───────────────────────────┴─────────────────────────────────────
                                    │
                          kis_auth (토큰·계정·env_dv)
```

### 1.2 레이어 요약

| 레이어 | 역할 |
|--------|------|
| **UI** | `dashboard_html.py` — 로그인, 설정 탭, 승인대기, 거래내역, 도움말, WebSocket 수신 |
| **API** | `quant_dashboard_api.py` — 인증·설정·종목선정·시스템 제어·성과 export |
| **엔진** | `quant_trading_safe.py` — 틱 수신 → 신호 생성 → 리스크 검사 → 주문 실행 → 체결 반영 |
| **전략** | `QuantStrategy` — MA 골든/데드 크로스, 필터(모멘텀·스프레드·레인지 등) |
| **리스크** | `RiskManager` — 일일 한도·손절/익절·ATR·포지션 수·pending·reconcile |
| **종목선정** | `stock_selector.py` — 등락률 API + 가격/거래량/거래대금 필터·정렬 |
| **인프라** | `kis_auth`, `domestic_stock_functions`, `domestic_stock_functions_ws` — KIS 연동 |

---

## 2. 디렉터리·파일 구조

```
kis-api/
├── kis_auth.py                    # KIS 인증·토큰·계정·env_dv (실전/모의)
├── config/
│   └── kis_devlp.yaml             # KIS 앱키·시크릿·계좌 (gitignore)
├── domestic_stock/
│   ├── quant_dashboard.py  # FastAPI 앱·상태·로그인·WebSocket
│   ├── quant_dashboard_api.py  # REST 엔드포인트 (설정·종목·시스템·성과)
│   ├── dashboard_html.py   # HTML/JS/CSS 대시보드 (f-string 렌더)
│   ├── quant_trading_safe.py      # RiskManager, QuantStrategy, safe_execute_order
│   ├── stock_selector.py          # StockSelector (등락률 기반 종목 선정)
│   ├── stock_selection_presets.py # 종목선정 프리셋
│   ├── domestic_stock_functions.py    # KIS REST (주문·잔고·체결·지수·등락률)
│   ├── domestic_stock_functions_ws.py # KIS WebSocket (호가·체결)
│   ├── domestic_stock_ws.py       # WebSocket 연결·구독
│   ├── user_settings_store.py     # DynamoDB 사용자 설정 저장소
│   ├── user_result_store.py       # DynamoDB 일별 성과 저장 (선택)
│   ├── audit_log.py               # 설정/수동주문/승인 감사 로그
│   ├── notifier.py                # 알림 (log_only | telegram)
│   ├── auth_manager.py            # 로그인·JWT·비밀번호 검증
│   └── dynamodb_config.py         # DynamoDB 테이블/리전 설정
├── deploy/
│   └── docker-compose.yml         # 서버 배포용 (Hub 이미지 + env_file)
├── docker-compose.yml             # 로컬/빌드용
├── Dockerfile
└── requirements.txt
```

---

## 3. 파일별 설명

### 3.1 핵심 실행·API

| 파일 | 설명 |
|------|------|
| **quant_dashboard.py** | FastAPI 앱 진입점. `TradingState` 전역 상태, 로그인/회원가입, JWT, WebSocket 브로드캐스트, HTML 라우트. `create_safe_on_result`로 엔진 콜백 등록. |
| **quant_dashboard_api.py** | 모든 REST API: 설정 로드/저장, 종목 선정, 시스템 시작/중지, 모의/실전 전환, 수동 주문, 승인/거절, 성과 조회/내보내기. 지수 MA·서킷·VI 캐시, 스킵 사유 로깅. |
| **dashboard_html.py** | 단일 HTML 내장 CSS/JS. 리스크·전략·종목선정·운영 설정 폼, 추천 프리셋, 도움말, 승인대기, 거래내역, 로그. `id="settings-section-help"` 등으로 섹션 구분. |

### 3.2 매매 엔진·전략·리스크

| 파일 | 설명 |
|------|------|
| **quant_trading_safe.py** | **RiskManager**: 한도·손절/익절·ATR·변동성 사이징·pending·reconcile·Lock. **QuantStrategy**: 틱 가격 히스토리, MA, `get_signal`. **safe_execute_order**: 주문 실행·재시도·폴백. **create_safe_on_result**: WebSocket 틱 콜백에서 신호→실행 루프. |

### 3.3 종목 선정·설정 저장

| 파일 | 설명 |
|------|------|
| **stock_selector.py** | **StockSelector**: 등락률 API 호출, 가격/거래량/거래대금 필터, 정렬(sort_by), 워밍업·장초 강화·고점 대비 하락 제외. `select_stocks_by_fluctuation()` 진입점. |
| **stock_selection_presets.py** | 종목선정 프리셋 정의 및 `get_preset`, `list_presets`. |
| **user_settings_store.py** | **DynamoDBUserSettingsStore**: 사용자별 리스크·전략·종목선정·운영 설정 저장/로드. |
| **user_result_store.py** | 일별 성과(수익률·거래 수·승/패) DynamoDB 저장·조회·기간 내보내기(백테스트 파라미터 옵션). |

### 3.4 인증·알림·감사

| 파일 | 설명 |
|------|------|
| **kis_auth.py** | KIS 토큰 발급/저장, `config_root`/`token_root`, 실전/모의(env_dv) 분기, TR_ID·URL 설정. |
| **auth_manager.py** | 로그인·회원가입·JWT 발급/검증, 비밀번호 해시. |
| **notifier.py** | **send_alert(level, message, title)**: log_only 또는 Telegram 발송. |
| **audit_log.py** | **audit_log(username, action, details)**: config_save, manual_order, signal_approve/reject 기록. |

### 3.5 KIS 연동

| 파일 | 설명 |
|------|------|
| **domestic_stock_functions.py** | REST: 주문(order_cash), 잔고·체결 조회, 지수·등락률(fluctuation)·거래량 순위 등. |
| **domestic_stock_functions_ws.py** | WebSocket: 호가(asking_price_krx), 체결(ccnl_krx) 구독·파싱. |
| **domestic_stock_ws.py** | WebSocket 연결·재연결·메시지 라우팅. |

---

## 4. 기능별·주요 함수

### 4.1 리스크 관리 (RiskManager)

| 함수/역할 | 설명 |
|-----------|------|
| **can_trade(stock_code, price, quantity)** | 일일 한도·거래 횟수·동시 보유 종목 수·재진입 쿨다운·매수 시간대·pending 중복 방지 등 검사 후 (bool, reason) 반환. |
| **check_exit_signal(stock_code, current_price)** | 손절/익절(고정 비율 또는 ATR 배수), 트레일링 스탑, 부분 익절 판단 후 "sell" 또는 None. |
| **calculate_quantity(price)** | max_single_trade_amount·min_order_quantity 기준 매수 수량. |
| **calculate_quantity_with_volatility(stock_code, price, fallback_quantity)** | 변동성 사이징·max_loss_per_stock_krw 적용 시 수량 계산. |
| **update_position(stock_code, price, quantity, action)** | positions 갱신 (buy/sell/partial). Lock 사용. |
| **has_pending_order / set_pending_order / clear_pending_order** | 주문 접수 후 체결 대기 중인 건 관리, 중복 주문 방지. |
| **get_unrealized_pnl / get_total_pnl** | 미실현·실현 포함 손익. 일일 한도 판단에 사용. |

### 4.2 전략·신호 (QuantStrategy)

| 함수/역할 | 설명 |
|-----------|------|
| **update_price(stock_code, price)** | 틱 가격을 price_history에 누적, RiskManager.last_prices 반영. |
| **calculate_ma(stock_code, period)** | 최근 period틱 종가 평균. |
| **get_signal(stock_code, current_price)** | 단기/장기 MA 골든크로스 → "buy", 데드크로스 → "sell". (필터·레짐은 API/엔진 쪽에서 추가 적용) |

### 4.3 주문 실행 (quant_trading_safe)

| 함수/역할 | 설명 |
|-----------|------|
| **safe_execute_order(signal, stock_code, price, strategy, trenv, is_paper_trading, manual_approval)** | can_trade 검사, 수량 계산, 수동 승인 시 대기, order_cash 호출, 접수/체결 분리. 재시도·지정가→시장가 폴백. |
| **_extract_order_response(df)** | order_cash 응답에서 ODNO·RT_CD 등 추출, 접수 성공 여부 판단. |
| **_check_unfilled_order_acceptance / _check_filled_order** | 미체결 조회로 접수 여부 확인, 체결 조회로 체결량·체결가 반영. |
| **create_safe_on_result(strategy, trenv, is_paper_trading, manual_approval)** | WebSocket 틱 콜백 등록: 틱 수신 → 선정 종목 필터 → get_signal → check_exit_signal → safe_execute_order. reconcile 루프로 pending 체결 반영. |

### 4.4 종목 선정 (StockSelector)

| 함수/역할 | 설명 |
|-----------|------|
| **select_stocks_by_fluctuation()** | 등락률 API 호출 후 가격/거래량/거래대금 필터, 위험 종목 제외, 정렬(sort_by), 워밍업·장초 강화·고점 대비 하락 제외 적용. 선정 종목코드 리스트 반환. |

### 4.5 API·설정 (quant_dashboard_api)

| 역할 | 설명 |
|------|------|
| 설정 로드/저장 | 사용자별 RiskConfig·StrategyConfig·StockSelectionConfig·OperationalConfig DynamoDB 읽기/쓰기. |
| 종목 선정 | StockSelector 인스턴스 생성 후 select_stocks_by_fluctuation 호출, 결과 저장·감사 로그. |
| 시스템 시작/중지 | WebSocket 연결·엔진 스레드 기동, create_safe_on_result 콜백 등록 / 중지·선택적 청산. |
| 승인/거절 | pending_signals에서 신호 조회, safe_execute_order 호출 또는 거절 로그. |
| 성과 내보내기 | user_result_store 기간 조회, 슬리피지·수수료·체결가정 옵션과 함께 CSV/JSON 반환. |

### 4.6 인증·알림·감사

| 모듈 | 함수/역할 |
|------|-----------|
| **auth_manager** | 로그인·회원가입·JWT 발급·검증, get_current_user 의존성. |
| **notifier** | send_alert(level, message, title) — 한도 도달·VI/서킷 스킵 등 알림. |
| **audit_log** | audit_log(username, action, details) — 설정 저장·수동 주문·신호 승인/거절 기록. |

---

## 5. 기술 스택

| 구분 | 기술 |
|------|------|
| 백엔드 | Python 3.12, FastAPI, Uvicorn |
| 인증 | JWT, PyJWT, pycryptodome |
| 저장소 | AWS DynamoDB (설정·성과), 선택적 인메모리 |
| 실시간 | WebSocket (FastAPI), KIS WebSocket (호가·체결) |
| 연동 | KIS Open API (REST·WebSocket), YAML·env 설정 |
| 프론트 | 단일 HTML 내장 CSS/JS (모바일 반응형) |
| 배포 | Docker, Docker Compose, GitHub Actions → Docker Hub |

---

## 6. 배포·운영

- **로컬**: `config/kis_devlp.yaml`, `.env` 준비 후 `uvicorn domestic_stock.quant_dashboard:app --reload`
- **Docker**: `docker-compose up -d` 또는 Hub 이미지 `akito56/quant-trading-dashboard:latest` + `deploy/docker-compose.yml`
- **환경 변수**: KIS 설정, DynamoDB 테이블/리전, 알림(Telegram 등), `KIS_TOKEN_ROOT`(쓰기 경로)

---

*이 문서는 코드 구조와 주요 함수 위주로 정리한 포트폴리오용 요약입니다. 상세 평가는 `docs/SYSTEM_EVALUATION_SUMMARY.md`, `domestic_stock/docs/TRADING_SYSTEM_EVALUATION.md`를 참고하면 됩니다.*
