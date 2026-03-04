"""
대시보드 HTML 생성 모듈 (모바일 최적화)
"""

def get_dashboard_html_mobile(username: str) -> str:
    """모바일 최적화 대시보드 HTML"""
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>퀀트 매매 시스템</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{
            /* Light (AWS 콘솔 느낌) */
            --bg: #f2f3f3;
            --surface: #ffffff;
            --surface-2: #f8f9fa;
            --text: #0f1b2d;
            --muted: #5f6b7a;
            --border: #d5dbdb;
            --shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
            --container-pad: 15px;
            /* Navigation row backgrounds (행 전체 배경) */
            --nav-row-bg: #d9dee5;
            --subnav-row-bg: #f3f5f7;
            --radius: 4px;     /* 전체 UI 모서리: 거의 직각 */

            --primary: #0972d3;         /* AWS 콘솔 블루 계열 */
            --primary-active: #075aa6;
            --danger: #d13212;
            --danger-active: #b1270f;

            --ok: #1d8102;
            --warn: #b35c00;
            --err: #d13212;

            /* System log (dark) */
            --log-bg: #0b1220;
            --log-border: #1f2937;
            --log-text: #e5e7eb;
            --log-muted: #9ca3af;
            --log-info: #7ee787;
            --log-warn: #fbbf24;
            --log-error: #fb7185;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 0;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}
        .header {{
            background: var(--surface);
            color: var(--text);
            padding: 15px 20px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: var(--shadow);
            border-bottom: 1px solid var(--border);
        }}
        .header-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .header h1 {{
            font-size: 20px;
            font-weight: 600;
        }}
        .header-user {{
            font-size: 12px;
            color: var(--muted);
        }}
        .status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: var(--radius);
            font-size: 12px;
            font-weight: 600;
            margin-left: 8px;
        }}
        .status.running {{ background: rgba(29, 129, 2, 0.12); border: 1px solid rgba(29, 129, 2, 0.35); color: var(--ok); }}
        .status.stopped {{ background: rgba(209, 50, 18, 0.10); border: 1px solid rgba(209, 50, 18, 0.35); color: var(--err); }}
        .container {{
            padding: var(--container-pad);
            max-width: 100%;
        }}
        .card {{
            background: var(--surface);
            border-radius: var(--radius);
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: var(--shadow);
            border: 1px solid var(--border);
        }}
        .card h2 {{
            color: var(--text);
            font-size: 16px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
        }}
        .metric:last-child {{ border-bottom: none; }}
        .metric-label {{
            color: var(--muted);
            font-size: 14px;
        }}
        .metric-value {{
            font-weight: 600;
            font-size: 14px;
            color: var(--text);
        }}
        .metric-value.positive {{ color: var(--ok); }}
        .metric-value.negative {{ color: var(--err); }}
        .btn {{
            background: var(--primary);
            color: #fff;
            border: none;
            padding: 12px 20px;
            border-radius: var(--radius);
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            margin: 5px 0;
            transition: all 0.2s;
            -webkit-tap-highlight-color: transparent;
        }}
        .btn:active {{
            transform: scale(0.98);
            background: var(--primary-active);
        }}
        .btn-danger {{
            background: var(--danger);
        }}
        .btn-danger:active {{
            background: var(--danger-active);
        }}
        .env-selector {{
            display: flex;
            gap: 8px;
            align-items: center;
            flex-wrap: wrap;
        }}
        .env-selector .metric-label {{
            flex: 0 0 auto;
            margin-right: 4px;
        }}
        .env-btn {{
            flex: 1;
            min-width: 90px;
            padding: 8px 14px;
            border-radius: var(--radius);
            border: 1px solid var(--border);
            background: var(--surface);
            color: var(--muted);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .env-btn.active {{
            background: var(--primary);
            border-color: var(--primary);
            color: #fff;
        }}
        .env-btn:not(.active):hover {{
            background: var(--surface-2);
            border-color: #aab7b8;
            color: var(--text);
        }}
        .env-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 23, 42, 0.55);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 999;
            padding: 20px;
        }}
        .modal {{
            background: var(--surface);
            border-radius: var(--radius);
            width: 100%;
            max-width: 420px;
            box-shadow: 0 18px 55px rgba(0,0,0,0.25);
            overflow: hidden;
            border: 1px solid var(--border);
        }}
        .modal-header {{
            padding: 14px 16px;
            border-bottom: 1px solid var(--border);
            font-weight: 700;
            color: var(--text);
        }}
        .modal-body {{
            padding: 16px;
            color: var(--text);
            font-size: 14px;
            line-height: 1.5;
        }}
        .modal-footer {{
            padding: 12px 16px;
            border-top: 1px solid var(--border);
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }}
        .checkbox-row {{
            display: flex;
            gap: 10px;
            align-items: center;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            background: var(--surface-2);
            margin-top: 12px;
        }}
        .checkbox-row input {{
            width: auto;
            margin: 0;
        }}
        .checkbox-row label {{
            color: var(--text);
        }}
        .btn-group {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 10px;
        }}
        input, select {{
            width: 100%;
            padding: 12px;
            margin: 8px 0;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            font-size: 14px;
            background: var(--surface);
            color: var(--text);
            -webkit-appearance: none;
            appearance: none;
        }}
        /* 체크박스는 기본 UI를 살리고 테마만 적용 */
        input[type="checkbox"] {{
            width: auto;
            padding: 0;
            margin: 0;
            border: none;
            border-radius: 4px;
            background: transparent;
            -webkit-appearance: auto;
            appearance: auto;
            accent-color: var(--primary);
            cursor: pointer;
            transform: scale(1.15);
        }}
        input:focus, select:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(9, 114, 211, 0.15);
        }}
        .form-group {{
            margin: 12px 0;
        }}
        .form-group label {{
            display: block;
            margin-bottom: 6px;
            color: var(--muted);
            font-weight: 600;
            font-size: 13px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        th, td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            color: var(--text);
        }}
        th {{
            background: var(--surface-2);
            color: var(--muted);
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
        }}
        .log {{
            background: var(--log-bg);
            color: var(--log-text);
            padding: 12px;
            border-radius: var(--radius);
            max-height: 200px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            -webkit-overflow-scrolling: touch;
            border: 1px solid var(--log-border);
        }}
        .log-entry {{
            margin: 4px 0;
            padding: 4px;
            word-break: break-word;
        }}
        .log-entry.info {{ color: var(--log-info); }}
        .log-entry.warning {{ color: var(--log-warn); }}
        .log-entry.error {{ color: var(--log-error); }}
        .logout-btn {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 6px 12px;
            border-radius: var(--radius);
            font-size: 12px;
            cursor: pointer;
        }}
        .logout-btn:hover {{
            background: rgba(9, 114, 211, 0.08);
        }}
        /* 최상단 메뉴바: 탭(좌) + 상태/사용자/로그아웃(우) */
        .topbar {{
            position: sticky;
            top: 0;
            z-index: 200;
            background: var(--nav-row-bg);
            border: none;
            box-shadow: 0 6px 18px rgba(0,0,0,0.06);
        }}
        .topbar-inner {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 10px var(--container-pad);
            max-width: 1200px;
            margin: 0 auto;
        }}
        .tablist {{
            display: flex;
            align-items: center;
            gap: 2px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            flex: 1 1 auto;
            min-width: 0;
        }}
        .nav-right {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 0 0 auto;
            white-space: nowrap;
        }}
        .user-menu {{
            position: relative;
            display: inline-flex;
            align-items: center;
        }}
        .user-avatar {{
            width: 32px;
            height: 32px;
            border-radius: 999px; /* avatar는 원형 유지 */
            background: #ffffff;
            border: 1px solid rgba(15, 27, 45, 0.18);
            color: #0f1b2d;
            font-weight: 800;
            font-size: 13px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            user-select: none;
            line-height: 1;
        }}
        .user-avatar:hover {{
            border-color: rgba(9, 114, 211, 0.45);
        }}
        .user-dropdown {{
            position: absolute;
            top: calc(100% + 10px);
            right: 0;
            min-width: 200px;
            background: var(--surface);
            border: 1px solid var(--border);
            box-shadow: 0 18px 55px rgba(0,0,0,0.12);
            border-radius: var(--radius);
            padding: 8px;
            display: none;
            z-index: 500;
        }}
        .user-dropdown.open {{
            display: block;
        }}
        .user-dropdown .menu-header {{
            padding: 8px 10px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 6px;
            font-size: 12px;
            color: var(--muted);
        }}
        .menu-item {{
            width: 100%;
            text-align: left;
            background: transparent;
            border: none;
            padding: 10px 10px;
            border-radius: var(--radius);
            cursor: pointer;
            font-size: 13px;
            font-weight: 700;
            color: var(--text);
        }}
        .menu-item:hover {{
            background: rgba(15, 27, 45, 0.05);
        }}
        .menu-item.danger {{
            color: var(--danger);
        }}
        .menu-item.danger:hover {{
            background: rgba(209, 50, 18, 0.08);
        }}
        .tab {{
            padding: 10px 14px;
            background: transparent;
            border: none;
            border-radius: var(--radius);
            font-size: 13px;
            font-weight: 700;
            color: #334155; /* light 배경 대비 강화 */
            cursor: pointer;
            white-space: nowrap;
            position: relative;
            transition: background-color 0.12s ease;
        }}
        .tab:hover {{
            color: inherit;
            /* hover 효과: 배경색만 살짝 변경 */
            background: rgba(15, 27, 45, 0.06);
        }}
        .tab:not(.active):hover::after {{
            content: none; /* hover 언더라인 제거 */
        }}
        .tab.active {{
            color: var(--primary);
            background: transparent; /* 메뉴 '배경'은 최소화: 언더라인+텍스트로만 강조 */
        }}
        .tab.active::after {{
            content: '';
            position: absolute;
            left: 10px;
            right: 10px;
            bottom: 4px;
            height: 2px;
            background: var(--primary);
            border-radius: var(--radius);
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        /* 설정 서브메뉴: 메인 메뉴바 바로 아래 바 형태 */
        .topbar-sub {{
            display: none;
            background: var(--subnav-row-bg);
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .topbar-sub-inner {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 8px var(--container-pad);
        }}
        .subtabs {{
            display: flex;
            align-items: center;
            gap: 2px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}
        .subtab {{
            padding: 8px 10px;
            background: transparent;
            border: none;
            border-radius: var(--radius);
            font-size: 12px;
            font-weight: 800;
            color: #475569;
            cursor: pointer;
            white-space: nowrap;
            position: relative;
        }}
        .subtab:hover {{
            background: rgba(15, 27, 45, 0.06);
        }}
        .subtab.active {{
            color: var(--primary);
            background: transparent;
        }}
        .subtab.active::after {{
            content: '';
            position: absolute;
            left: 10px;
            right: 10px;
            bottom: 3px;
            height: 2px;
            background: var(--primary);
            border-radius: var(--radius);
        }}
        .settings-section {{
            display: none;
        }}
        .settings-section.active {{
            display: block;
        }}
        details {{
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 10px 12px;
            background: var(--surface-2);
            margin: 10px 0;
        }}
        summary {{
            cursor: pointer;
            color: var(--text);
            font-weight: 700;
            font-size: 13px;
        }}
        .hint {{
            color: var(--muted);
            font-size: 12px;
            line-height: 1.5;
            margin-top: 6px;
        }}
        @media (min-width: 768px) {{
            :root {{
                --container-pad: 20px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: var(--container-pad);
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 20px;
            }}
        }}
        @media (min-width: 1024px) {{
            .grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="topbar">
        <div class="topbar-inner">
            <div class="tablist">
                <button class="tab active" onclick="showTab('status')">상태</button>
                <button class="tab" onclick="showTab('positions')">포지션</button>
                <button class="tab" onclick="showTab('settings')">설정</button>
                <button class="tab" onclick="showTab('signals')">승인대기</button>
                <button class="tab" onclick="showTab('trades')">거래내역</button>
            </div>
            <div class="nav-right">
                <span id="status" class="status stopped">중지됨</span>
                <div class="user-menu" id="userMenu">
                    <div class="user-avatar" id="userAvatar" role="button" tabindex="0" aria-haspopup="true" aria-expanded="false" onclick="toggleUserMenu()">{username[:1].upper()}</div>
                    <div class="user-dropdown" id="userDropdown" role="menu" aria-label="사용자 메뉴">
                        <div class="menu-header">Signed in as <strong>{username}</strong></div>
                        <button type="button" class="menu-item danger" onclick="logout()">Sign out</button>
                    </div>
                </div>
            </div>
        </div>
        <div class="topbar-sub" id="settingsSubbar">
            <div class="topbar-sub-inner">
                <div class="subtabs">
                    <button type="button" class="subtab active" id="subtab-preset" onclick="showSettingsSection('preset')">프리셋</button>
                    <button type="button" class="subtab" id="subtab-risk" onclick="showSettingsSection('risk')">리스크</button>
                    <button type="button" class="subtab" id="subtab-strategy" onclick="showSettingsSection('strategy')">전략</button>
                    <button type="button" class="subtab" id="subtab-stocks" onclick="showSettingsSection('stocks')">종목선정</button>
                </div>
            </div>
        </div>
    </div>

    <div class="container">

        <!-- 상태 탭 -->
        <div id="tab-status" class="tab-content active">
            <div class="card">
                <h2>시스템 상태</h2>
                <div class="metric">
                    <div class="env-selector">
                        <span class="metric-label">투자 환경:</span>
                        <button type="button" id="env-btn-paper" class="env-btn active" onclick="setTradingEnv(true)" title="시스템 중지 시에만 변경 가능">모의 투자</button>
                        <button type="button" id="env-btn-real" class="env-btn" onclick="setTradingEnv(false)" title="시스템 중지 시에만 변경 가능">실전 투자</button>
                    </div>
                    <span class="metric-value" id="env" style="display:block; margin-top:6px; font-size:12px; color:var(--muted);">-</span>
                </div>
                <div class="metric">
                    <div class="env-selector">
                        <span class="metric-label">매매 방식:</span>
                        <button type="button" id="trade-mode-manual" class="env-btn active" onclick="setTradeMode(true)" title="신호 발생 시 승인대기 후 수동 승인">수동</button>
                        <button type="button" id="trade-mode-auto" class="env-btn" onclick="setTradeMode(false)" title="신호 발생 시 즉시 자동 매수/매도">자동</button>
                    </div>
                    <span class="metric-value" id="trade_mode_label" style="display:block; margin-top:6px; font-size:12px; color:var(--muted);">승인대기 후 수동</span>
                </div>
                <div class="metric">
                    <span class="metric-label">계좌 잔고:</span>
                    <span class="metric-value" id="balance">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">일일 손익:</span>
                    <span class="metric-value" id="daily_pnl">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">일일 거래 횟수:</span>
                    <span class="metric-value" id="daily_trades">-</span>
                </div>
                <div class="btn-group">
                    <button class="btn" onclick="startSystem()">시작</button>
                    <button class="btn btn-danger" onclick="openStopModal()">중지</button>
                </div>
                <button class="btn" onclick="refreshData()" style="margin-top: 10px;">새로고침</button>
            </div>
            <div class="card">
                <h2>선정 종목 리스트</h2>
                <div id="selected_stocks">
                    <p style="color: var(--muted); text-align: center; padding: 20px;">선정된 종목이 없습니다.</p>
                </div>
            </div>
            <div class="card">
                <h2>매수 스킵 통계</h2>
                <div id="skip_stats" style="color:var(--text); font-size:13px; line-height:1.55;">
                    <p style="color: var(--muted); text-align: center; padding: 20px;">집계 중...</p>
                </div>
            </div>
        </div>

        <!-- 포지션 탭 -->
        <div id="tab-positions" class="tab-content">
            <div class="card">
                <h2>현재 포지션</h2>
                <div id="positions">
                    <p style="color: var(--muted); text-align: center; padding: 20px;">보유 종목이 없습니다.</p>
                </div>
            </div>
        </div>

        <!-- 설정 탭 -->
        <div id="tab-settings" class="tab-content">
            

            <div id="settings-section-preset" class="settings-section active">
                <div class="card">
                    <h2>추천 프리셋</h2>
                    <div class="hint">
                        오전 단타(9~12) 운영을 가정한 기본값을 한 번에 적용합니다. (리스크/전략/종목선정 기준)
                    </div>
                    <button type="button" class="btn" onclick="applyScalpMorningPreset()">오전 단타(9~12) 프리셋 적용</button>
                </div>
            </div>

            <div id="settings-section-risk" class="settings-section">
                <div class="card">
                    <h2>리스크 관리</h2>
                    <div class="hint" id="risk_summary"></div>
                    <div class="form-group">
                        <label>최대 거래 금액 (원):</label>
                        <input type="number" id="max_trade_amount" value="1000000">
                    </div>
                    <div class="form-group">
                        <label>최소 매수 수량(주):</label>
                        <input type="number" id="min_order_quantity" value="1" min="1" max="1000">
                    </div>
                    <div class="form-group">
                        <label>손절매 비율 (%):</label>
                        <input type="number" id="stop_loss" value="2" step="0.1">
                    </div>
                    <div class="form-group">
                        <label>익절매 비율 (%):</label>
                        <input type="number" id="take_profit" value="5" step="0.1">
                    </div>
                    <div class="form-group">
                        <label>일일 손실 한도 (원):</label>
                        <input type="number" id="daily_loss_limit" value="500000">
                    </div>
                    <div class="form-group">
                        <label>일일 이익 한도(원) (전량매도 트리거):</label>
                        <input type="number" id="daily_profit_limit" value="0" min="0" step="10000">
                    </div>

                    <details>
                        <summary>고급(트레일링/부분익절)</summary>
                        <div class="form-group">
                            <label>부분 익절 트리거(%):</label>
                            <input type="number" id="partial_tp_pct" value="0" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label>부분 익절 비율(%):</label>
                            <input type="number" id="partial_tp_fraction_pct" value="50" step="5" min="0" max="100">
                        </div>
                        <div class="form-group">
                            <label>트레일링 스탑 (%):</label>
                            <input type="number" id="trailing_stop_pct" value="0" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label>트레일링 활성화 최소 수익(%):</label>
                            <input type="number" id="trailing_activation_pct" value="0" step="0.1" min="0" max="50">
                        </div>
                    </details>

                    <button class="btn" onclick="updateRiskConfig()">저장</button>
                </div>
            </div>

            <div id="settings-section-strategy" class="settings-section">
                <div class="card">
                    <h2>전략 설정 (이동평균)</h2>
                    <div class="hint" id="strategy_summary"></div>
                    <div class="form-group">
                        <label>MA 프리셋:</label>
                        <div class="btn-group">
                            <button type="button" class="btn" onclick="applyMaPreset(3, 10)">빠름 3/10</button>
                            <button type="button" class="btn" onclick="applyMaPreset(5, 20)">보수 5/20</button>
                        </div>
                        <button type="button" class="btn" onclick="applyMaPreset(8, 21)" style="margin-top: 8px;">중기 8/21</button>
                    </div>
                    <div class="form-group">
                        <label>단기 이동평균 (틱):</label>
                        <input type="number" id="short_ma_period" value="3" min="2" max="60">
                    </div>
                    <div class="form-group">
                        <label>장기 이동평균 (틱):</label>
                        <input type="number" id="long_ma_period" value="10" min="3" max="200">
                    </div>
                    <div class="form-group">
                        <label>신규 매수 허용 시작 (HH:MM, KST):</label>
                        <input type="text" id="buy_window_start_hhmm" value="09:05" placeholder="09:05">
                    </div>
                    <div class="form-group">
                        <label>신규 매수 허용 종료 (HH:MM, KST):</label>
                        <input type="text" id="buy_window_end_hhmm" value="11:30" placeholder="11:30">
                    </div>

                    <details>
                        <summary>고급(필터/쿨다운/청산)</summary>
                        <div class="form-group">
                            <label>단기MA 기울기 최소(%/틱):</label>
                            <input type="number" id="min_short_ma_slope_pct" value="0" step="0.001" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>재진입 쿨다운(초):</label>
                            <input type="number" id="reentry_cooldown_seconds" value="0" min="0" max="3600">
                        </div>
                        <div class="form-group">
                            <label>진입 확인(연속 틱 수):</label>
                            <input type="number" id="buy_confirm_ticks" value="1" min="1" max="10">
                        </div>
                        <div class="form-group">
                            <label>최대 스프레드(%):</label>
                            <input type="number" id="max_spread_pct" value="0" step="0.01" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>횡보장 제외: 최근 N틱</label>
                            <input type="number" id="range_lookback_ticks" value="0" min="0" max="300">
                        </div>
                        <div class="form-group">
                            <label>횡보장 제외: 최소 레인지(%)</label>
                            <input type="number" id="min_range_pct" value="0" step="0.01" min="0" max="20">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="enable_time_liquidation">
                                시간기반 청산 사용
                            </label>
                        </div>
                        <div class="form-group">
                            <label>청산 시작 시각(HH:MM, KST):</label>
                            <input type="text" id="liquidate_after_hhmm" value="11:55" placeholder="11:55">
                        </div>
                    </details>

                    <button class="btn" onclick="updateStrategyConfig()">저장</button>
                </div>
            </div>

            <div id="settings-section-stocks" class="settings-section">
                <div class="card">
                    <h2>종목 선정 기준</h2>
                    <div class="hint" id="stocks_summary"></div>
                    <div class="form-group">
                        <label>프리셋:</label>
                        <select id="preset_select" onchange="loadPreset()">
                            <option value="">직접 설정</option>
                            <option value="scalp_morning">오전 단타(9~12)</option>
                            <option value="common">보편적</option>
                            <option value="conservative">보수적</option>
                            <option value="aggressive">공격적</option>
                            <option value="beginner">초보자용</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>최소 상승률 (%):</label>
                        <input type="number" id="min_change" value="1" step="0.1">
                    </div>
                    <div class="form-group">
                        <label>최대 상승률 (%):</label>
                        <input type="number" id="max_change" value="15" step="0.1">
                    </div>
                    <div class="form-group">
                        <label>최대 선정 종목 수:</label>
                        <input type="number" id="max_stocks" value="5">
                    </div>
                    <div class="form-group">
                        <label>최소 가격 (원):</label>
                        <input type="number" id="min_price" value="1000">
                    </div>
                    <div class="form-group">
                        <label>최대 가격 (원):</label>
                        <input type="number" id="max_price" value="2000000">
                    </div>
                    <div class="form-group">
                        <label>최소 거래량 (주):</label>
                        <input type="number" id="min_volume" value="50000">
                    </div>
                    <div class="form-group">
                        <label>최소 거래대금 (원):</label>
                        <input type="number" id="min_trade_amount" value="0">
                    </div>

                    <details>
                        <summary>고급(장초/드로우다운)</summary>
                        <div class="form-group">
                            <label>장 시작 시각 (HH:MM):</label>
                            <input type="text" id="market_open_hhmm" value="09:00" placeholder="09:00">
                        </div>
                        <div class="form-group">
                            <label>장초 워밍업(분):</label>
                            <input type="number" id="warmup_minutes" value="5" min="0" max="60">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="early_strict">
                                장초 강화 필터 사용(초기 변동 노이즈 완화)
                            </label>
                        </div>
                        <div class="form-group">
                            <label>장초 강화 적용 시간(분):</label>
                            <input type="number" id="early_strict_minutes" value="30" min="1" max="180">
                        </div>
                        <div class="form-group">
                            <label>장초 강화 최소 거래량(주):</label>
                            <input type="number" id="early_min_volume" value="200000" min="0">
                        </div>
                        <div class="form-group">
                            <label>장초 강화 최소 거래대금(원):</label>
                            <input type="number" id="early_min_trade_amount" value="0" min="0">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="exclude_drawdown">
                                고점 대비 하락추세 종목 제외(장중 후행 진입 방지)
                            </label>
                        </div>
                        <div class="form-group">
                            <label>고점 대비 최대 허용 하락폭(%):</label>
                            <input type="number" id="max_drawdown_pct" value="2.0" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label>하락추세 제외 적용 시작 시각(HH:MM):</label>
                            <input type="text" id="drawdown_filter_after_hhmm" value="12:00" placeholder="12:00">
                        </div>
                    </details>

                    <div class="btn-group" style="grid-template-columns: 1fr 1fr;">
                        <button class="btn" onclick="updateStockSelection()">저장</button>
                        <button class="btn" onclick="selectStocks()">종목 재선정</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- 승인대기 탭 -->
        <div id="tab-signals" class="tab-content">
            <div class="card">
                <h2>승인 대기 신호</h2>
                <div id="pending_signals">
                    <p style="color: var(--muted); text-align: center; padding: 20px;">대기 중인 신호가 없습니다.</p>
                </div>
            </div>
        </div>

        <!-- 거래내역 탭 -->
        <div id="tab-trades" class="tab-content">
            <div class="card">
                <h2>거래 내역</h2>
                <div id="trade_history" style="max-height: 400px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>시간</th>
                                <th>종목</th>
                                <th>유형</th>
                                <th>수량</th>
                                <th>가격</th>
                            </tr>
                        </thead>
                        <tbody id="trade_history_body">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 시스템 로그 -->
        <div class="card">
            <h2>시스템 로그</h2>
            <div class="log" id="log">
                <div class="log-entry info">대시보드 연결 중...</div>
            </div>
        </div>
    </div>

    <!-- 중지 확인 모달 -->
    <div id="stopModalOverlay" class="modal-overlay" onclick="closeStopModal(event)">
        <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-header">시스템 중지</div>
            <div class="modal-body">
                시스템을 중지하시겠습니까?
                <div class="checkbox-row">
                    <input type="checkbox" id="liquidate_on_stop">
                    <label for="liquidate_on_stop" style="cursor:pointer;">
                        보유 포지션 전량 시장가 청산 후 중지
                    </label>
                </div>
                <div style="margin-top:10px; font-size:12px; color:var(--muted);">
                    청산을 선택하면 보유 종목을 시장가로 매도 주문합니다.
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn" onclick="closeStopModal()">취소</button>
                <button type="button" class="btn btn-danger" onclick="confirmStop()">중지</button>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let reconnectInterval = null;
        let pendingSignals = {{}};

        function showTab(tabName) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById(`tab-${{tabName}}`).classList.add('active');
            const sub = document.getElementById('settingsSubbar');
            if (sub) sub.style.display = (tabName === 'settings') ? 'block' : 'none';
        }}

        function toggleUserMenu() {{
            const dd = document.getElementById('userDropdown');
            const av = document.getElementById('userAvatar');
            if (!dd || !av) return;
            const open = dd.classList.toggle('open');
            av.setAttribute('aria-expanded', open ? 'true' : 'false');
        }}

        function closeUserMenu() {{
            const dd = document.getElementById('userDropdown');
            const av = document.getElementById('userAvatar');
            if (!dd || !av) return;
            dd.classList.remove('open');
            av.setAttribute('aria-expanded', 'false');
        }}

        document.addEventListener('click', (e) => {{
            const menu = document.getElementById('userMenu');
            const dd = document.getElementById('userDropdown');
            if (!menu || !dd) return;
            if (!dd.classList.contains('open')) return;
            if (menu.contains(e.target)) return;
            closeUserMenu();
        }});

        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeUserMenu();
            }}
            if (e.key === 'Enter' || e.key === ' ') {{
                const av = document.getElementById('userAvatar');
                if (av && document.activeElement === av) {{
                    e.preventDefault();
                    toggleUserMenu();
                }}
            }}
        }});

        function showSettingsSection(name) {{
            const sections = ['preset', 'risk', 'strategy', 'stocks'];
            sections.forEach(s => {{
                const sec = document.getElementById(`settings-section-${{s}}`);
                const btn = document.getElementById(`subtab-${{s}}`);
                if (sec) sec.classList.toggle('active', s === name);
                if (btn) btn.classList.toggle('active', s === name);
            }});
            updateSettingsSummaries();
        }}

        function connectWebSocket() {{
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${{protocol}}//${{window.location.host}}/ws`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {{
                addLog('WebSocket 연결됨', 'info');
                if (reconnectInterval) {{
                    clearInterval(reconnectInterval);
                    reconnectInterval = null;
                }}
            }};
            
            ws.onmessage = (event) => {{
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            }};
            
            ws.onclose = () => {{
                addLog('WebSocket 연결 끊김', 'warning');
                if (!reconnectInterval) {{
                    reconnectInterval = setInterval(connectWebSocket, 3000);
                }}
            }};
            
            ws.onerror = (error) => {{
                addLog('WebSocket 오류', 'error');
            }};
        }}

        function handleWebSocketMessage(data) {{
            if (data.type === 'status') {{
                updateStatus(data.data);
            }} else if (data.type === 'position') {{
                updatePositions(data.data);
            }} else if (data.type === 'trade') {{
                addTradeToHistory(data.data);
            }} else if (data.type === 'signal_pending') {{
                upsertPendingSignal(data.data);
            }} else if (data.type === 'signal_resolved') {{
                removePendingSignal(data.data.signal_id, data.data.status);
            }} else if (data.type === 'signal_snapshot') {{
                pendingSignals = {{}};
                (data.data || []).forEach(s => {{
                    pendingSignals[s.signal_id] = s;
                }});
                renderPendingSignals();
            }} else if (data.type === 'log') {{
                addLog(data.message, data.level || 'info');
            }}
        }}

        function upsertPendingSignal(signal) {{
            pendingSignals[signal.signal_id] = signal;
            renderPendingSignals();
            addLog(`신호 감지: ${{signal.stock_code}} ${{signal.signal.toUpperCase()}}`, 'warning');
        }}

        function removePendingSignal(signalId, status) {{
            if (pendingSignals[signalId]) {{
                const removed = pendingSignals[signalId];
                delete pendingSignals[signalId];
                renderPendingSignals();
                addLog(`신호 처리: ${{removed.stock_code}} (${{status}})`, status === 'approved' ? 'info' : 'warning');
            }}
        }}

        function renderPendingSignals() {{
            const container = document.getElementById('pending_signals');
            const list = Object.values(pendingSignals);
            if (!list.length) {{
                container.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 20px;">대기 중인 신호가 없습니다.</p>';
                return;
            }}

            list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            let html = '';
            list.forEach(signal => {{
                const name = (signal.stock_name || '').trim();
                const title = name ? `${{signal.stock_code}} · ${{name}}` : `${{signal.stock_code}}`;
                html += `
                    <div style="border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; margin-bottom: 10px; background: var(--surface-2);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <strong>${{title}}</strong>
                            <span style="font-size:12px; padding:4px 8px; border-radius: var(--radius); background:${{signal.signal === 'buy' ? '#e8f5e9' : '#ffebee'}}; color:${{signal.signal === 'buy' ? '#2e7d32' : '#c62828'}};">
                                ${{signal.signal === 'buy' ? '매수' : '매도'}}
                            </span>
                        </div>
                        <div style="font-size:13px; color:var(--muted); margin-bottom:4px;">가격: ${{formatNumber(signal.price)}}원</div>
                        <div style="font-size:13px; color:var(--muted); margin-bottom:4px;">수량(제안): ${{signal.suggested_qty}}주</div>
                        <div style="font-size:12px; color:var(--muted); margin-bottom:10px;">사유: ${{signal.reason}}</div>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                            <button class="btn" onclick="approveSignal('${{signal.signal_id}}')" style="margin:0;">승인</button>
                            <button class="btn btn-danger" onclick="rejectSignal('${{signal.signal_id}}')" style="margin:0;">거절</button>
                        </div>
                    </div>
                `;
            }});
            container.innerHTML = html;
        }}

        async function loadPendingSignals() {{
            try {{
                const response = await fetch('/api/signals/pending');
                const data = await response.json();
                if (data.success) {{
                    pendingSignals = {{}};
                    (data.signals || []).forEach(s => {{
                        pendingSignals[s.signal_id] = s;
                    }});
                    renderPendingSignals();
                }}
            }} catch (error) {{
                addLog('신호 목록 조회 실패: ' + error, 'error');
            }}
        }}

        async function approveSignal(signalId) {{
            try {{
                const response = await fetch(`/api/signals/${{signalId}}/approve`, {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    addLog('신호 승인 완료', 'info');
                    delete pendingSignals[signalId];
                    renderPendingSignals();
                }} else {{
                    addLog('신호 승인 실패: ' + data.message, 'error');
                }}
            }} catch (error) {{
                addLog('신호 승인 오류: ' + error, 'error');
            }}
        }}

        async function rejectSignal(signalId) {{
            try {{
                const response = await fetch(`/api/signals/${{signalId}}/reject`, {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    addLog('신호 거절 완료', 'warning');
                    delete pendingSignals[signalId];
                    renderPendingSignals();
                }} else {{
                    addLog('신호 거절 실패: ' + data.message, 'error');
                }}
            }} catch (error) {{
                addLog('신호 거절 오류: ' + error, 'error');
            }}
        }}

        function updateStatus(data) {{
            document.getElementById('status').textContent = data.is_running ? '실행 중' : '중지됨';
            document.getElementById('status').className = 'status ' + (data.is_running ? 'running' : 'stopped');
            document.getElementById('env').textContent = data.env_name || '-';
            const isPaper = data.is_paper_trading !== false;
            const paperBtn = document.getElementById('env-btn-paper');
            const realBtn = document.getElementById('env-btn-real');
            if (paperBtn) {{
                paperBtn.classList.toggle('active', isPaper);
                paperBtn.disabled = !!data.is_running;
            }}
            if (realBtn) {{
                realBtn.classList.toggle('active', !isPaper);
                realBtn.disabled = !!data.is_running;
            }}
            const manualApproval = data.manual_approval !== false;
            const manualBtn = document.getElementById('trade-mode-manual');
            const autoBtn = document.getElementById('trade-mode-auto');
            const tradeModeLabel = document.getElementById('trade_mode_label');
            if (manualBtn) {{
                manualBtn.classList.toggle('active', manualApproval);
            }}
            if (autoBtn) {{
                autoBtn.classList.toggle('active', !manualApproval);
            }}
            if (tradeModeLabel) {{
                tradeModeLabel.textContent = manualApproval ? '승인대기 후 수동' : '즉시 자동 체결';
            }}
            document.getElementById('balance').textContent = formatNumber(data.account_balance) + '원';
            document.getElementById('daily_pnl').textContent = formatNumber(data.daily_pnl) + '원';
            document.getElementById('daily_pnl').className = 'metric-value ' + (data.daily_pnl >= 0 ? 'positive' : 'negative');
            document.getElementById('daily_trades').textContent = data.daily_trades + '회';
            if (data.short_ma_period) {{
                document.getElementById('short_ma_period').value = data.short_ma_period;
            }}
            if (data.long_ma_period) {{
                document.getElementById('long_ma_period').value = data.long_ma_period;
            }}
            if (data.buy_window_start_hhmm) {{
                const el = document.getElementById('buy_window_start_hhmm');
                if (el) el.value = data.buy_window_start_hhmm;
            }}
            if (data.buy_window_end_hhmm) {{
                const el = document.getElementById('buy_window_end_hhmm');
                if (el) el.value = data.buy_window_end_hhmm;
            }}
            renderSelectedStocks(data.selected_stock_info || data.selected_stocks || []);
            renderBuySkipStats(data.buy_skip_stats || null);
            updateSettingsSummaries();
        }}

        function _labelSkipKey(key) {{
            const k = (key || '').toString();
            const map = {{
                spread: '스프레드 과대',
                range: '횡보장 제외',
                slope: '단기MA 기울기 부족',
                cooldown: '재진입 쿨다운',
                confirm: '진입 확인 대기',
                time_window: '신규매수 시간외',
                unknown: '기타',
            }};
            return map[k] || k;
        }}

        function renderBuySkipStats(stats) {{
            const el = document.getElementById('skip_stats');
            if (!el) return;
            if (!stats) {{
                el.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 20px;">집계 데이터가 없습니다.</p>';
                return;
            }}
            const total = stats.total || 0;
            const byReason = stats.by_reason || [];
            const topStocks = stats.top_stocks || [];

            const reasonsHtml = byReason.length
                ? byReason.map(r => `<div style="display:flex; justify-content:space-between; gap:12px;"><span>${{_labelSkipKey(r.key)}}</span><strong>${{r.count}}</strong></div>`).join('')
                : '<div style="color:var(--muted);">아직 스킵이 없습니다.</div>';

            const stocksHtml = topStocks.length
                ? topStocks.map(s => `<div style="display:flex; justify-content:space-between; gap:12px;"><span>${{s.code}}</span><strong>${{s.count}}</strong></div>`).join('')
                : '<div style="color:var(--muted);">-</div>';

            el.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <span style="color:var(--muted);">누적 스킵</span>
                    <strong style="font-size:14px;">${{total}}</strong>
                </div>
                <div style="display:grid; grid-template-columns:1fr; gap:12px;">
                    <div style="padding:10px; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface-2);">
                        <div style="color:var(--muted); font-size:12px; margin-bottom:8px;">사유 TOP</div>
                        ${{reasonsHtml}}
                    </div>
                    <div style="padding:10px; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface-2);">
                        <div style="color:var(--muted); font-size:12px; margin-bottom:8px;">종목 TOP</div>
                        ${{stocksHtml}}
                    </div>
                </div>
            `;
        }}

        function updateSettingsSummaries() {{
            try {{
                const risk = document.getElementById('risk_summary');
                if (risk) {{
                    const maxAmt = document.getElementById('max_trade_amount')?.value || '-';
                    const minQty = document.getElementById('min_order_quantity')?.value || '-';
                    const sl = document.getElementById('stop_loss')?.value || '-';
                    const tp = document.getElementById('take_profit')?.value || '-';
                    const dly = document.getElementById('daily_loss_limit')?.value || '-';
                    const dpr = document.getElementById('daily_profit_limit')?.value || '0';
                    const pt = document.getElementById('partial_tp_pct')?.value || '0';
                    const tr = document.getElementById('trailing_stop_pct')?.value || '0';
                    risk.textContent =
                        'max=' + maxAmt + '원 · ' +
                        'minQty=' + minQty + '주 · ' +
                        'SL=' + sl + '%/TP=' + tp + '% · ' +
                        'dailyLoss=' + dly + '원 · ' +
                        'dailyProfit=' + dpr + '원 · ' +
                        '부분익절=' + pt + '% · ' +
                        'trailing=' + tr + '%';
                }}

                const strat = document.getElementById('strategy_summary');
                if (strat) {{
                    const sma = document.getElementById('short_ma_period')?.value || '-';
                    const lma = document.getElementById('long_ma_period')?.value || '-';
                    const bwS = document.getElementById('buy_window_start_hhmm')?.value || '-';
                    const bwE = document.getElementById('buy_window_end_hhmm')?.value || '-';
                    const slope = document.getElementById('min_short_ma_slope_pct')?.value || '0';
                    const cd = document.getElementById('reentry_cooldown_seconds')?.value || '0';
                    const conf = document.getElementById('buy_confirm_ticks')?.value || '1';
                    const spr = document.getElementById('max_spread_pct')?.value || '0';
                    const n = document.getElementById('range_lookback_ticks')?.value || '0';
                    const rr = document.getElementById('min_range_pct')?.value || '0';
                    const liqOn = !!document.getElementById('enable_time_liquidation')?.checked;
                    const liqAt = document.getElementById('liquidate_after_hhmm')?.value || '-';
                    strat.textContent =
                        'MA=' + sma + '/' + lma + ' · ' +
                        'buy=' + bwS + '-' + bwE + ' · ' +
                        'slope≥' + slope + '%/t · ' +
                        'cd=' + cd + 's · ' +
                        'confirm=' + conf + ' · ' +
                        'spr≤' + spr + '% · ' +
                        'range≥' + rr + '%/N' + n + ' · ' +
                        'timeLiq=' + (liqOn ? 'on' : 'off') + '@' + liqAt;
                }}

                const stocks = document.getElementById('stocks_summary');
                if (stocks) {{
                    const mc = document.getElementById('min_change')?.value || '-';
                    const xc = document.getElementById('max_change')?.value || '-';
                    const mp = document.getElementById('min_price')?.value || '-';
                    const xp = document.getElementById('max_price')?.value || '-';
                    const mv = document.getElementById('min_volume')?.value || '-';
                    const ta = document.getElementById('min_trade_amount')?.value || '-';
                    const mx = document.getElementById('max_stocks')?.value || '-';
                    const warm = document.getElementById('warmup_minutes')?.value || '0';
                    const es = !!document.getElementById('early_strict')?.checked;
                    const dd = !!document.getElementById('exclude_drawdown')?.checked;
                    const ddPct = document.getElementById('max_drawdown_pct')?.value || '0';
                    stocks.textContent =
                        'chg=' + mc + '-' + xc + '% · ' +
                        'px=' + mp + '-' + xp + ' · ' +
                        'vol≥' + mv + ' · ' +
                        'amt≥' + ta + ' · ' +
                        'max=' + mx + ' · ' +
                        'warmup=' + warm + 'm · ' +
                        'earlyStrict=' + (es ? 'on' : 'off') + ' · ' +
                        'drawdown=' + (dd ? 'on' : 'off') + '(' + ddPct + '%)';
                }}
            }} catch (e) {{
                // ignore
            }}
        }}

        function renderSelectedStocks(stocks) {{
            const container = document.getElementById('selected_stocks');
            if (!stocks || stocks.length === 0) {{
                container.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 20px;">선정된 종목이 없습니다.</p>';
                return;
            }}

            const chips = stocks.map(item => {{
                const code = (typeof item === 'string') ? item : (item.code || '-');
                const name = (typeof item === 'string') ? '' : (item.name || '');
                const label = name ? `${{code}} · ${{name}}` : code;
                return `<span style="display:inline-block; padding:6px 10px; margin:4px; border-radius:var(--radius); background:var(--surface-2); color:var(--text); font-weight:700; font-size:13px; border:1px solid var(--border);">${{label}}</span>`;
            }}).join('');
            container.innerHTML = `<div>${{chips}}</div>`;
        }}

        function updatePositions(positions) {{
            const container = document.getElementById('positions');
            if (!positions || Object.keys(positions).length === 0) {{
                container.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 20px;">보유 종목이 없습니다.</p>';
                return;
            }}
            
            let html = '<table><thead><tr><th>종목</th><th>수량</th><th>매수가</th><th>현재가</th><th>손익</th></tr></thead><tbody>';
            for (const [code, pos] of Object.entries(positions)) {{
                const pnl = (pos.current_price - pos.buy_price) * pos.quantity;
                html += `<tr>
                    <td>${{code}}</td>
                    <td>${{pos.quantity}}주</td>
                    <td>${{formatNumber(pos.buy_price)}}원</td>
                    <td>${{formatNumber(pos.current_price)}}원</td>
                    <td class="${{pnl >= 0 ? 'positive' : 'negative'}}">${{formatNumber(pnl)}}원</td>
                </tr>`;
            }}
            html += '</tbody></table>';
            container.innerHTML = html;
        }}

        function addTradeToHistory(trade) {{
            const tbody = document.getElementById('trade_history_body');
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${{new Date(trade.timestamp).toLocaleTimeString()}}</td>
                <td>${{trade.stock_code}}</td>
                <td>${{trade.order_type === 'buy' ? '매수' : '매도'}}</td>
                <td>${{trade.quantity}}주</td>
                <td>${{formatNumber(trade.price)}}원</td>
            `;
            tbody.insertBefore(row, tbody.firstChild);
        }}

        function addLog(message, level = 'info') {{
            const log = document.getElementById('log');
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + level;
            entry.textContent = `[${{new Date().toLocaleTimeString()}}] ${{message}}`;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }}

        function formatNumber(num) {{
            return new Intl.NumberFormat('ko-KR').format(num);
        }}

        async function setTradingEnv(isPaper) {{
            try {{
                const response = await fetch('/api/system/set-env', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ is_paper_trading: isPaper }})
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog(data.message || (isPaper ? '모의 투자로 변경됨' : '실전 투자로 변경됨'), 'info');
                    refreshData();
                }} else {{
                    addLog('환경 변경 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        async function setTradeMode(manualApproval) {{
            try {{
                const response = await fetch('/api/system/set-trade-mode', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ manual_approval: manualApproval }})
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog(data.message || (manualApproval ? '수동(승인대기) 모드' : '자동 체결 모드'), 'info');
                    refreshData();
                }} else {{
                    addLog('매매 모드 변경 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        async function startSystem() {{
            try {{
                const response = await fetch('/api/system/start', {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    addLog('시스템 시작됨', 'info');
                }} else {{
                    addLog('시스템 시작 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        function openStopModal() {{
            document.getElementById('liquidate_on_stop').checked = false;
            document.getElementById('stopModalOverlay').style.display = 'flex';
        }}

        function closeStopModal(evt) {{
            if (evt && evt.target && evt.target.id !== 'stopModalOverlay') {{
                // clicked inside modal
                return;
            }}
            document.getElementById('stopModalOverlay').style.display = 'none';
        }}

        async function confirmStop() {{
            const liquidate = document.getElementById('liquidate_on_stop').checked;
            closeStopModal();
            await stopSystem(liquidate);
        }}

        async function stopSystem(liquidate = false) {{
            try {{
                const response = await fetch(`/api/system/stop?liquidate=${{liquidate ? 'true' : 'false'}}`, {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    addLog('시스템 중지됨', 'info');
                }} else {{
                    addLog('시스템 중지 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        async function refreshData() {{
            try {{
                const response = await fetch('/api/system/status');
                const data = await response.json();
                updateStatus(data);
            }} catch (error) {{
                addLog('새로고침 오류: ' + error, 'error');
            }}
        }}

        async function loadUserSettings() {{
            try {{
                const response = await fetch('/api/config/user-settings');
                const data = await response.json();
                if (!data.success) {{
                    return;
                }}
                const s = data.settings || {{}};
                const risk = s.risk_config || null;
                const strat = s.strategy_config || null;
                const stocksel = s.stock_selection_config || null;

                if (risk) {{
                    if (risk.max_single_trade_amount != null) document.getElementById('max_trade_amount').value = risk.max_single_trade_amount;
                    if (risk.min_order_quantity != null) document.getElementById('min_order_quantity').value = risk.min_order_quantity;
                    if (risk.stop_loss_ratio != null) document.getElementById('stop_loss').value = (risk.stop_loss_ratio * 100).toFixed(1);
                    if (risk.take_profit_ratio != null) document.getElementById('take_profit').value = (risk.take_profit_ratio * 100).toFixed(1);
                    if (risk.daily_loss_limit != null) document.getElementById('daily_loss_limit').value = risk.daily_loss_limit;
                    if (risk.daily_profit_limit != null) document.getElementById('daily_profit_limit').value = risk.daily_profit_limit;
                    if (risk.trailing_stop_ratio != null) document.getElementById('trailing_stop_pct').value = (risk.trailing_stop_ratio * 100).toFixed(1);
                    if (risk.trailing_activation_ratio != null) document.getElementById('trailing_activation_pct').value = (risk.trailing_activation_ratio * 100).toFixed(1);
                    if (risk.partial_take_profit_ratio != null) document.getElementById('partial_tp_pct').value = (risk.partial_take_profit_ratio * 100).toFixed(1);
                    if (risk.partial_take_profit_fraction != null) document.getElementById('partial_tp_fraction_pct').value = (risk.partial_take_profit_fraction * 100).toFixed(0);
                }}
                if (strat) {{
                    if (strat.short_ma_period != null) document.getElementById('short_ma_period').value = strat.short_ma_period;
                    if (strat.long_ma_period != null) document.getElementById('long_ma_period').value = strat.long_ma_period;
                    if (strat.buy_window_start_hhmm != null) document.getElementById('buy_window_start_hhmm').value = strat.buy_window_start_hhmm;
                    if (strat.buy_window_end_hhmm != null) document.getElementById('buy_window_end_hhmm').value = strat.buy_window_end_hhmm;
                    if (strat.min_short_ma_slope_ratio != null) document.getElementById('min_short_ma_slope_pct').value = (strat.min_short_ma_slope_ratio * 100).toFixed(3);
                    if (strat.reentry_cooldown_seconds != null) document.getElementById('reentry_cooldown_seconds').value = strat.reentry_cooldown_seconds;
                    if (strat.buy_confirm_ticks != null) document.getElementById('buy_confirm_ticks').value = strat.buy_confirm_ticks;
                    if (strat.enable_time_liquidation != null) document.getElementById('enable_time_liquidation').checked = !!strat.enable_time_liquidation;
                    if (strat.liquidate_after_hhmm != null) document.getElementById('liquidate_after_hhmm').value = strat.liquidate_after_hhmm;
                    if (strat.max_spread_ratio != null) document.getElementById('max_spread_pct').value = (strat.max_spread_ratio * 100).toFixed(2);
                    if (strat.range_lookback_ticks != null) document.getElementById('range_lookback_ticks').value = strat.range_lookback_ticks;
                    if (strat.min_range_ratio != null) document.getElementById('min_range_pct').value = (strat.min_range_ratio * 100).toFixed(2);
                }}
                if (stocksel) {{
                    const preset = document.getElementById('preset_select');
                    if (preset) preset.value = '';
                    if (stocksel.min_price_change_ratio != null) document.getElementById('min_change').value = (stocksel.min_price_change_ratio * 100).toFixed(1);
                    if (stocksel.max_price_change_ratio != null) document.getElementById('max_change').value = (stocksel.max_price_change_ratio * 100).toFixed(1);
                    if (stocksel.max_stocks != null) document.getElementById('max_stocks').value = stocksel.max_stocks;
                    if (stocksel.min_price != null) document.getElementById('min_price').value = stocksel.min_price;
                    if (stocksel.max_price != null) document.getElementById('max_price').value = stocksel.max_price;
                    if (stocksel.min_volume != null) document.getElementById('min_volume').value = stocksel.min_volume;
                    if (stocksel.min_trade_amount != null) document.getElementById('min_trade_amount').value = stocksel.min_trade_amount;

                    if (stocksel.market_open_hhmm != null) document.getElementById('market_open_hhmm').value = stocksel.market_open_hhmm;
                    if (stocksel.warmup_minutes != null) document.getElementById('warmup_minutes').value = stocksel.warmup_minutes;
                    if (stocksel.early_strict != null) document.getElementById('early_strict').checked = !!stocksel.early_strict;
                    if (stocksel.early_strict_minutes != null) document.getElementById('early_strict_minutes').value = stocksel.early_strict_minutes;
                    if (stocksel.early_min_volume != null) document.getElementById('early_min_volume').value = stocksel.early_min_volume;
                    if (stocksel.early_min_trade_amount != null) document.getElementById('early_min_trade_amount').value = stocksel.early_min_trade_amount;
                    if (stocksel.exclude_drawdown != null) document.getElementById('exclude_drawdown').checked = !!stocksel.exclude_drawdown;
                    if (stocksel.max_drawdown_from_high_ratio != null) document.getElementById('max_drawdown_pct').value = (stocksel.max_drawdown_from_high_ratio * 100).toFixed(1);
                    if (stocksel.drawdown_filter_after_hhmm != null) document.getElementById('drawdown_filter_after_hhmm').value = stocksel.drawdown_filter_after_hhmm;
                }}
                updateSettingsSummaries();
            }} catch (e) {{
                // ignore
            }}
        }}

        async function updateRiskConfig() {{
            try {{
                const config = {{
                    max_single_trade_amount: parseInt(document.getElementById('max_trade_amount').value),
                    min_order_quantity: parseInt(document.getElementById('min_order_quantity').value) || 1,
                    stop_loss_ratio: parseFloat(document.getElementById('stop_loss').value) / 100,
                    take_profit_ratio: parseFloat(document.getElementById('take_profit').value) / 100,
                    daily_loss_limit: parseInt(document.getElementById('daily_loss_limit').value),
                    daily_profit_limit: parseInt(document.getElementById('daily_profit_limit').value) || 0,
                    max_trades_per_day: 5,
                    max_position_size_ratio: 0.1,
                    trailing_stop_ratio: (parseFloat(document.getElementById('trailing_stop_pct').value) || 0) / 100,
                    trailing_activation_ratio: (parseFloat(document.getElementById('trailing_activation_pct').value) || 0) / 100,
                    partial_take_profit_ratio: (parseFloat(document.getElementById('partial_tp_pct').value) || 0) / 100,
                    partial_take_profit_fraction: (parseFloat(document.getElementById('partial_tp_fraction_pct').value) || 0) / 100,
                }};
                const response = await fetch('/api/config/risk', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog('리스크 설정 저장됨', 'info');
                    updateSettingsSummaries();
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        async function updateStrategyConfig() {{
            try {{
                const config = {{
                    short_ma_period: parseInt(document.getElementById('short_ma_period').value),
                    long_ma_period: parseInt(document.getElementById('long_ma_period').value),
                    buy_window_start_hhmm: (document.getElementById('buy_window_start_hhmm').value || '09:05').trim(),
                    buy_window_end_hhmm: (document.getElementById('buy_window_end_hhmm').value || '11:30').trim(),
                    min_short_ma_slope_ratio: (parseFloat(document.getElementById('min_short_ma_slope_pct').value) || 0) / 100,
                    reentry_cooldown_seconds: parseInt(document.getElementById('reentry_cooldown_seconds').value) || 0,
                    buy_confirm_ticks: parseInt(document.getElementById('buy_confirm_ticks').value) || 1,
                    enable_time_liquidation: !!document.getElementById('enable_time_liquidation').checked,
                    liquidate_after_hhmm: (document.getElementById('liquidate_after_hhmm').value || '11:55').trim(),
                    max_spread_ratio: (parseFloat(document.getElementById('max_spread_pct').value) || 0) / 100,
                    range_lookback_ticks: parseInt(document.getElementById('range_lookback_ticks').value) || 0,
                    min_range_ratio: (parseFloat(document.getElementById('min_range_pct').value) || 0) / 100,
                }};
                const response = await fetch('/api/config/strategy', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog(`전략 설정 저장됨 (short=${{config.short_ma_period}}, long=${{config.long_ma_period}}, buy_window=${{config.buy_window_start_hhmm}}-${{config.buy_window_end_hhmm}})`, 'info');
                    updateSettingsSummaries();
                }} else {{
                    addLog('전략 설정 저장 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        async function applyMaPreset(shortPeriod, longPeriod) {{
            document.getElementById('short_ma_period').value = shortPeriod;
            document.getElementById('long_ma_period').value = longPeriod;
            addLog(`MA 프리셋 적용: short=${{shortPeriod}}, long=${{longPeriod}}`, 'info');
            await updateStrategyConfig();
        }}

        async function applyScalpMorningPreset() {{
            try {{
                addLog('오전 단타(9~12) 프리셋 적용 중...', 'info');

                // 리스크(보수적 기본값)
                document.getElementById('max_trade_amount').value = 1000000;
                document.getElementById('min_order_quantity').value = 2;
                document.getElementById('stop_loss').value = 1.0;
                document.getElementById('take_profit').value = 2.0;
                document.getElementById('daily_loss_limit').value = 300000;
                document.getElementById('partial_tp_pct').value = 1.0;
                document.getElementById('partial_tp_fraction_pct').value = 50;
                document.getElementById('trailing_stop_pct').value = 0.8;
                document.getElementById('trailing_activation_pct').value = 1.0;
                await updateRiskConfig();

                // 전략(빠른 MA + 신규 매수 시간 제한)
                document.getElementById('short_ma_period').value = 3;
                document.getElementById('long_ma_period').value = 10;
                document.getElementById('buy_window_start_hhmm').value = '09:05';
                document.getElementById('buy_window_end_hhmm').value = '11:30';
                document.getElementById('min_short_ma_slope_pct').value = 0.010;
                document.getElementById('reentry_cooldown_seconds').value = 180;
                document.getElementById('buy_confirm_ticks').value = 2;
                // 스프레드/횡보장 필터 기본값 튜닝(너무 타이트하면 매수 자체가 안 걸릴 수 있음)
                document.getElementById('max_spread_pct').value = 0.20;
                document.getElementById('range_lookback_ticks').value = 60;
                document.getElementById('min_range_pct').value = 0.25;
                document.getElementById('enable_time_liquidation').checked = true;
                document.getElementById('liquidate_after_hhmm').value = '11:55';
                await updateStrategyConfig();

                // 종목 선정 프리셋
                const sel = document.getElementById('preset_select');
                if (sel) sel.value = 'scalp_morning';
                await loadPreset();
                const ok = await updateStockSelection(true);
                if (!ok) {{
                    addLog('프리셋 적용 실패: 종목 선정 기준 저장 실패', 'warning');
                    return;
                }}

                // 1회 자동 재선정 (바로 표시)
                const res = await selectStocks(true);
                if (res && res.success) {{
                    addLog('오전 단타 프리셋 적용 완료', 'info');
                }} else {{
                    addLog('오전 단타 프리셋 적용 완료(재선정 실패): ' + ((res && res.message) ? res.message : '알 수 없는 오류'), 'warning');
                }}
                updateSettingsSummaries();
                await refreshData();
            }} catch (e) {{
                addLog('프리셋 적용 오류: ' + e, 'error');
            }}
        }}

        async function updateStockSelection(silent = false) {{
            try {{
                const config = {{
                    min_price_change_ratio: parseFloat(document.getElementById('min_change').value) / 100,
                    max_price_change_ratio: parseFloat(document.getElementById('max_change').value) / 100,
                    min_price: parseInt(document.getElementById('min_price').value),
                    max_price: parseInt(document.getElementById('max_price').value),
                    min_volume: parseInt(document.getElementById('min_volume').value),
                    min_trade_amount: parseInt(document.getElementById('min_trade_amount').value) || 0,
                    max_stocks: parseInt(document.getElementById('max_stocks').value),
                    exclude_risk_stocks: true,

                    market_open_hhmm: (document.getElementById('market_open_hhmm').value || '09:00').trim(),
                    warmup_minutes: parseInt(document.getElementById('warmup_minutes').value) || 0,
                    early_strict: !!document.getElementById('early_strict').checked,
                    early_strict_minutes: parseInt(document.getElementById('early_strict_minutes').value) || 30,
                    early_min_volume: parseInt(document.getElementById('early_min_volume').value) || 0,
                    early_min_trade_amount: parseInt(document.getElementById('early_min_trade_amount').value) || 0,
                    exclude_drawdown: !!document.getElementById('exclude_drawdown').checked,
                    max_drawdown_from_high_ratio: (parseFloat(document.getElementById('max_drawdown_pct').value) || 0) / 100,
                    drawdown_filter_after_hhmm: (document.getElementById('drawdown_filter_after_hhmm').value || '12:00').trim(),
                }};
                const response = await fetch('/api/config/stock-selection', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await response.json();
                if (data.success) {{
                    if (!silent) addLog('종목 선정 기준 저장됨', 'info');
                    updateSettingsSummaries();
                    return true;
                }} else {{
                    if (!silent) addLog('종목 선정 기준 저장 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                    return false;
                }}
            }} catch (error) {{
                if (!silent) addLog('오류: ' + error, 'error');
                return false;
            }}
        }}

        async function loadPreset() {{
            const presetName = document.getElementById('preset_select').value;
            if (!presetName) return;
            
            try {{
                const response = await fetch(`/api/config/preset/${{presetName}}`);
                const data = await response.json();
                if (data.success) {{
                    const preset = data.preset;
                    document.getElementById('min_change').value = (preset.min_price_change_ratio * 100).toFixed(1);
                    document.getElementById('max_change').value = (preset.max_price_change_ratio * 100).toFixed(1);
                    document.getElementById('max_stocks').value = preset.max_stocks;
                    document.getElementById('min_price').value = preset.min_price ?? 1000;
                    document.getElementById('max_price').value = preset.max_price ?? 2000000;
                    document.getElementById('min_volume').value = preset.min_volume ?? 50000;
                    document.getElementById('min_trade_amount').value = preset.min_trade_amount ?? 0;

                    if (preset.market_open_hhmm != null) document.getElementById('market_open_hhmm').value = preset.market_open_hhmm;
                    if (preset.warmup_minutes != null) document.getElementById('warmup_minutes').value = preset.warmup_minutes;
                    if (preset.early_strict != null) document.getElementById('early_strict').checked = !!preset.early_strict;
                    if (preset.early_strict_minutes != null) document.getElementById('early_strict_minutes').value = preset.early_strict_minutes;
                    if (preset.early_min_volume != null) document.getElementById('early_min_volume').value = preset.early_min_volume;
                    if (preset.early_min_trade_amount != null) document.getElementById('early_min_trade_amount').value = preset.early_min_trade_amount;
                    if (preset.exclude_drawdown != null) document.getElementById('exclude_drawdown').checked = !!preset.exclude_drawdown;
                    if (preset.max_drawdown_from_high_ratio != null) document.getElementById('max_drawdown_pct').value = (preset.max_drawdown_from_high_ratio * 100).toFixed(1);
                    if (preset.drawdown_filter_after_hhmm != null) document.getElementById('drawdown_filter_after_hhmm').value = preset.drawdown_filter_after_hhmm;
                    addLog(`프리셋 로드: ${{preset.name}}`, 'info');
                }}
            }} catch (error) {{
                addLog('프리셋 로드 오류: ' + error, 'error');
            }}
        }}

        async function selectStocks(silent = false) {{
            try {{
                const ok = await updateStockSelection(true);
                if (!ok) {{
                    if (!silent) addLog('종목 재선정 중단: 선정 기준 저장 실패', 'warning');
                    return {{ success: false, message: '선정 기준 저장 실패' }};
                }}
                if (!silent) addLog('종목 재선정 중...', 'info');
                const response = await fetch('/api/stocks/select', {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    if (!silent) addLog(`종목 선정 완료: ${{data.stocks.join(', ')}}`, 'info');
                    await refreshData();
                    return data;
                }} else {{
                    if (!silent) addLog('종목 재선정 실패: ' + (data.message || '조건에 맞는 종목 없음'), 'warning');
                    renderSelectedStocks([]);
                    return data;
                }}
            }} catch (error) {{
                if (!silent) addLog('종목 선정 실패: ' + error, 'error');
                return {{ success: false, message: String(error) }};
            }}
        }}

        async function logout() {{
            try {{
                await fetch('/api/auth/logout', {{ method: 'POST' }});
                window.location.href = '/login';
            }} catch (error) {{
                window.location.href = '/login';
            }}
        }}

        // 초기화
        connectWebSocket();
        const _sub = document.getElementById('settingsSubbar');
        if (_sub) _sub.style.display = 'none';
        (async () => {{
            await loadUserSettings();
            updateSettingsSummaries();
            // 로그인 직후: 저장된 "종목 선정 기준"으로 1회 자동 선정해서 바로 보여주기
            if (!window.__initial_auto_selection_done) {{
                window.__initial_auto_selection_done = true;
                addLog('저장된 설정으로 종목 자동 선정 중...', 'info');
                const res = await selectStocks(true);
                if (res && res.success) {{
                    const stocks = (res.stocks || []);
                    const suffix = (stocks && stocks.length) ? `: ${{stocks.join(', ')}}` : '';
                    addLog('저장된 설정으로 종목 자동 선정 완료' + suffix, 'info');
                }} else {{
                    addLog('저장된 설정으로 종목 자동 선정 실패: ' + ((res && res.message) ? res.message : '알 수 없는 오류'), 'warning');
                }}
            }}
            await refreshData();
            await loadPendingSignals();
            setInterval(refreshData, 5000);
        }})();
    </script>
</body>
</html>
    """
