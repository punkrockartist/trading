"""
KIS API 설정 파일 생성 스크립트
YAML 설정 파일을 생성하여 app key와 secret을 저장합니다.
"""

import os
import yaml
from pathlib import Path

# 설정 파일 경로: 이 프로젝트 루트의 config 폴더
_project_root = os.path.dirname(os.path.abspath(__file__))
config_root = os.path.join(_project_root, "config")
config_file = os.path.join(config_root, "kis_devlp.yaml")

def create_config():
    """설정 파일 생성"""
    # 디렉토리 생성
    Path(config_root).mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("KIS API 설정 파일 생성")
    print("=" * 80)
    print(f"\n설정 파일 경로: {config_file}")
    print("\n아래 정보를 입력해주세요:")
    print("(입력하지 않으면 빈 값으로 설정됩니다)\n")
    
    # 사용자 입력 받기
    my_app = input("실전투자용 App Key: ").strip()
    my_sec = input("실전투자용 App Secret: ").strip()
    
    paper_app = input("모의투자용 App Key (선택사항): ").strip()
    paper_sec = input("모의투자용 App Secret (선택사항): ").strip()
    
    my_acct_stock = input("주식 계좌번호 (8자리, 선택사항): ").strip()
    my_acct_future = input("선물옵션 계좌번호 (8자리, 선택사항): ").strip()
    my_prod = input("계좌상품코드 (2자리, 기본값: 01): ").strip() or "01"
    my_htsid = input("HTS ID (선택사항): ").strip()
    
    # 기본값 설정
    config = {
        "my_app": my_app,
        "my_sec": my_sec,
        "paper_app": paper_app if paper_app else my_app,  # 모의투자용이 없으면 실전용 사용
        "paper_sec": paper_sec if paper_sec else my_sec,
        "my_acct_stock": my_acct_stock,
        "my_acct_future": my_acct_future,
        "my_prod": my_prod,
        "my_htsid": my_htsid,
        "my_token": "",  # 토큰은 자동으로 발급됨
        "prod": "https://openapi.koreainvestment.com:9443",  # 실전 서버 URL (필수)
        "vps": "https://openapivts.koreainvestment.com:29443",  # 모의 서버 URL (필수)
        "ops": "https://openapi.koreainvestment.com:9443",  # 실전 WebSocket 서버 URL (필수)
        "vops": "https://openapivts.koreainvestment.com:29443",  # 모의 WebSocket 서버 URL (필수)
        "my_url": "https://openapi.koreainvestment.com:9443",  # 실전 도메인
        "my_url_ws": "https://openapivts.koreainvestment.com:29443",  # 모의 도메인
        "my_agent": "Mozilla/5.0"  # User-Agent
    }
    
    # YAML 파일 저장
    with open(config_file, "w", encoding="UTF-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    print("\n" + "=" * 80)
    print("✅ 설정 파일이 생성되었습니다!")
    print("=" * 80)
    print(f"\n파일 위치: {config_file}")
    print("\n생성된 설정 내용:")
    print("-" * 80)
    for key, value in config.items():
        if key in ["my_sec", "paper_sec"]:
            # 보안을 위해 secret은 일부만 표시
            display_value = value[:10] + "..." if value else "(비어있음)"
        else:
            display_value = value if value else "(비어있음)"
        print(f"  {key}: {display_value}")
    print("-" * 80)
    print("\n⚠️  보안 주의: 이 파일에는 민감한 정보가 포함되어 있습니다.")
    print("   다른 사람과 공유하지 마세요!")

if __name__ == "__main__":
    try:
        create_config()
    except KeyboardInterrupt:
        print("\n\n취소되었습니다.")
    except Exception as e:
        print(f"\n오류 발생: {e}")
