"""
대시보드 HTML 생성 모듈 (모바일 최적화)
"""

def get_dashboard_html(username: str) -> str:
    """대시보드 HTML (반응형)"""
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
        .btn-inline {{
            width: auto;
            margin: 0;
            padding: 6px 10px;
            font-size: 13px;
            white-space: nowrap;
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
        .profile-form label {{ display: block; font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }}
        .profile-form label .label-hint {{ font-weight: 400; font-size: 11px; color: var(--muted); }}
        .profile-section {{ margin-bottom: 16px; }}
        .profile-section-title {{ font-weight: 700; font-size: 13px; color: var(--text); margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--border); }}
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
        .card-header-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        .card-header-row h2 {{
            margin: 0;
            padding: 0;
            border: none;
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
            overflow: visible;
        }}
        .topbar-inner {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 10px var(--container-pad);
            max-width: 1200px;
            margin: 0 auto;
            overflow: visible;
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
            overflow: visible;
        }}
        .user-menu {{
            position: relative;
            display: inline-flex;
            align-items: center;
            overflow: visible;
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
            overflow: visible;
        }}
        .user-dropdown.open {{
            display: block;
        }}
        .user-dropdown .menu-item {{
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
        .menu-item-signout {{
            margin-top: 6px;
            border-top: 1px solid var(--border);
            padding-top: 10px;
            display: block !important;
            visibility: visible !important;
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
        .performance-section {{
            display: none;
        }}
        .performance-section.active {{
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
        .setting-var {{
            font-size: 11px;
            color: var(--muted);
            font-weight: normal;
            margin-left: 6px;
        }}
        .hint {{
            color: var(--muted);
            font-size: 12px;
            line-height: 1.5;
            margin-top: 6px;
        }}
        .help-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            margin-top: 10px;
        }}
        .help-item {{
            padding: 10px 12px;
            border: 1px solid var(--border);
            background: var(--surface-2);
            border-radius: var(--radius);
        }}
        .help-item strong {{
            display: block;
            margin-bottom: 6px;
            color: var(--text);
        }}
        .help-item code {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            font-size: 12px;
        }}
        .doc-section {{ display: none; }}
        .doc-section.active {{ display: block; }}
        .doc-pre {{
            background: var(--log-bg);
            color: var(--log-text);
            padding: 12px;
            border-radius: var(--radius);
            font-size: 12px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .doc-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        .doc-table th, .doc-table td {{
            border: 1px solid var(--border);
            padding: 8px 10px;
            text-align: left;
        }}
        .doc-table th {{ background: var(--surface-2); font-weight: 600; }}
        .doc-table code {{
            font-size: 12px;
            background: var(--surface-2);
            padding: 2px 6px;
            border-radius: 2px;
        }}
        .doc-list {{ margin: 8px 0; padding-left: 20px; line-height: 1.7; }}
        .doc-list code {{
            font-size: 12px;
            background: var(--surface-2);
            padding: 2px 6px;
            border-radius: 2px;
        }}
        .table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12.5px;
        }}
        .table th, .table td {{
            border-bottom: 1px solid var(--border);
            padding: 8px 10px;
            vertical-align: top;
        }}
        .table th {{
            text-align: left;
            color: var(--muted);
            font-weight: 600;
            font-size: 12px;
        }}
        .pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
            border: 1px solid var(--border);
            background: var(--surface-2);
            color: var(--text);
        }}
        .pill.ok {{ border-color: rgba(29,129,2,0.35); color: var(--ok); background: rgba(29,129,2,0.10); }}
        .pill.warn {{ border-color: rgba(222,158,0,0.45); color: #b97d00; background: rgba(222,158,0,0.12); }}
        .pill.err {{ border-color: rgba(209,50,18,0.35); color: var(--err); background: rgba(209,50,18,0.10); }}
        .preflight-box {{
            margin-top: 10px;
            border: 1px dashed var(--border);
            border-radius: 10px;
            padding: 12px;
            background: rgba(255,255,255,0.02);
        }}
        .preflight-kv {{
            display: grid;
            grid-template-columns: 120px 1fr;
            gap: 6px 10px;
            font-size: 12px;
            margin: 10px 0 6px;
        }}
        .preflight-kv .k {{ color: var(--muted); }}
        .preflight-kv code {{ font-size: 12px; }}
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
            <button class="tab active" data-tab="status" onclick="showTab('status')">상태</button>
            <button class="tab" data-tab="positions" onclick="showTab('positions')">포지션</button>
                <button class="tab" data-tab="performance" onclick="showTab('performance')">성과</button>
            <button class="tab" data-tab="settings" onclick="showTab('settings')">설정</button>
                <button class="tab" data-tab="signals" onclick="showTab('signals')">승인대기</button>
            <button class="tab" data-tab="trades" onclick="showTab('trades')">거래내역</button>
            <button class="tab" data-tab="ai-report" onclick="showTab('ai-report')">AI 리포트</button>
            <button class="tab" data-tab="docs" onclick="showTab('docs')">Docs</button>
            </div>
            <div class="nav-right">
                <span id="status" class="status stopped">중지됨</span>
                <div class="user-menu" id="userMenu">
                    <div class="user-avatar" id="userAvatar" role="button" tabindex="0" aria-haspopup="true" aria-expanded="false" onclick="toggleUserMenu()">{username[:1].upper()}</div>
                    <div class="user-dropdown" id="userDropdown" role="menu" aria-label="사용자 메뉴">
                        <div class="menu-header">Signed in as <strong>{username}</strong></div>
                        <button type="button" class="menu-item" onclick="openProfileModal()">개인정보</button>
                        <button type="button" class="menu-item menu-item-signout danger" onclick="logout()">Sign out</button>
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
                    <button type="button" class="subtab" id="subtab-operational" onclick="showSettingsSection('operational')">운영</button>
                    <button type="button" class="subtab" id="subtab-help" onclick="showSettingsSection('help')">도움말</button>
                </div>
            </div>
        </div>
        <div class="topbar-sub" id="performanceSubbar">
            <div class="topbar-sub-inner">
                <div class="subtabs">
                    <button type="button" class="subtab active" id="perf-subtab-summary" onclick="showPerformanceSection('summary')">요약·권장</button>
                    <button type="button" class="subtab" id="perf-subtab-daily" onclick="showPerformanceSection('daily')">일별 성과</button>
                </div>
            </div>
        </div>
        <div class="topbar-sub" id="docsSubbar">
            <div class="topbar-sub-inner">
                <div class="subtabs">
                    <button type="button" class="subtab active" id="doc-subtab-overview" onclick="showDocsSection('overview')">개요·아키텍처</button>
                    <button type="button" class="subtab" id="doc-subtab-workflow" onclick="showDocsSection('workflow')">워크플로우</button>
                    <button type="button" class="subtab" id="doc-subtab-files" onclick="showDocsSection('files')">파일별</button>
                    <button type="button" class="subtab" id="doc-subtab-functions" onclick="showDocsSection('functions')">기능·함수</button>
                </div>
            </div>
        </div>
        </div>

    <div class="container">

        <!-- 상태 탭 -->
        <div id="tab-status" class="tab-content active">
            <div class="card">
                <div class="card-header-row">
                <h2>시스템 상태</h2>
                    <div style="display:flex; align-items:center; gap:10px;">
                        <label style="display:flex; align-items:center; gap:6px; font-size:12px;">
                            <input type="checkbox" id="auto_refresh_enabled">
                            <span>자동 새로고침</span>
                            <select id="auto_refresh_interval" style="width:auto; padding:4px 6px; font-size:12px;">
                                <option value="5000" selected>5초</option>
                                <option value="10000">10초</option>
                                <option value="30000">30초</option>
                                <option value="60000">1분</option>
                            </select>
                        </label>
                        <button class="btn btn-inline" onclick="refreshData()">새로고침</button>
                    </div>
                </div>
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
                    <div style="flex:1; text-align:right; min-width:0;">
                        <span class="metric-value" id="balance">-</span>
                        <span class="metric-hint" id="balance_hint" style="display:block; font-size:11px; color:var(--muted); margin-top:2px;"></span>
                    </div>
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
                <div class="preflight-box" id="preflightBox">
                    <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;">
                        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                            <strong style="font-size:13px;">Preflight (시작 전 강제 점검)</strong>
                            <span id="preflightBadge" class="pill">미실행</span>
                        </div>
                        <div style="display:flex; align-items:center; gap:8px;">
                            <button class="btn btn-inline" onclick="runPreflight(false)">점검 실행</button>
                            <button class="btn btn-inline" onclick="renderPreflight(window.__lastPreflight || null)">결과 보기</button>
                        </div>
                    </div>
                    <div class="hint" style="margin-top:6px;">
                        시작 전 점검으로 필수 설정/리스크 상한/환경을 확인합니다. <strong>issues</strong>가 있으면 시스템 시작이 차단됩니다.
                    </div>
                    <div id="preflightResult" style="margin-top:10px; display:none;"></div>
                </div>
            </div>
            <div class="card">
                <h2 style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">선정 종목 리스트 <a href="#" onclick="openCriteriaModal(); return false;" style="font-size: 13px; font-weight: normal; color: var(--primary); text-decoration: none;">선정 기준 보기</a> <button type="button" class="btn btn-inline" style="font-size: 12px; padding: 4px 10px;" onclick="selectStocks()">종목 재선정</button></h2>
                <div class="hint">안내: <strong>실행 중에는 종목 변경이 불가</strong>합니다. 변경하려면 <strong>시스템 중지 → 종목 재선정 → 시스템 시작</strong> 순서로 진행하세요.</div>
                <div id="selected_stocks">
                    <p style="color: var(--muted); text-align: center; padding: 20px;">선정된 종목이 없습니다.</p>
                </div>
                <div id="stock_selection_debug" style="margin-top:12px;"></div>
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
                <div class="card-header-row">
                    <h2>현재 포지션</h2>
                    <button class="btn btn-inline" onclick="syncPositionsFromBalance()">잔고로 동기화</button>
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin-bottom:14px; padding:10px 0; border-bottom:1px solid var(--border);">
                    <div class="metric">
                        <span class="metric-label">계좌 잔고:</span>
                        <span class="metric-value" id="pos_balance">-</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">일일 손익:</span>
                        <span class="metric-value" id="pos_daily_pnl">-</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">일일 거래 횟수:</span>
                        <span class="metric-value" id="pos_daily_trades">-</span>
                    </div>
                </div>
                <div id="positions">
                    <p style="color: var(--muted); text-align: center; padding: 20px;">보유 종목이 없습니다.</p>
                </div>
            </div>
        </div>

        <!-- 성과 탭 -->
        <div id="tab-performance" class="tab-content">
            <div id="performance-section-summary" class="performance-section active">
                <div class="card">
                    <div class="card-header-row">
                        <h2>일일·세션 성과</h2>
                        <button class="btn btn-inline" onclick="loadPerformanceSummary()">새로고침</button>
                    </div>
                    <div class="hint">당일 거래 기준(DB 있으면 당일 전체 사용 → 일별 성과의 ‘오늘’ 행과 동일). 새로고침 시 최신 집계 반영.</div>
                    <div id="performance_metrics" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap:12px; margin:12px 0;">
                        <p style="color: var(--muted); grid-column: 1/-1;">로딩 중...</p>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header-row">
                        <h2>기간 성과 (최근 1개월)</h2>
                        <button class="btn btn-inline" onclick="loadPerformancePeriodStats()">새로고침</button>
                    </div>
                    <div class="hint">저장된 일별 자산 기준. DynamoDB quant_trading_user_result 사용 시에만 표시.</div>
                    <div id="performance_period_metrics" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap:12px; margin:12px 0;">
                        <p style="color: var(--muted); grid-column: 1/-1;">로딩 중...</p>
                    </div>
                </div>
                <div class="card">
                    <h2>권장 설정 (성과 기반)</h2>
                    <div id="performance_recommendations" style="font-size:14px; line-height:1.6;">
                        <p style="color: var(--muted);">성과 요약 로딩 후 표시됩니다.</p>
                    </div>
                    <div class="hint">자동 적용되지 않습니다. 설정 탭에서 수동으로 조정하세요.</div>
                </div>
            </div>
            <div id="performance-section-daily" class="performance-section">
                <div class="card">
                    <h2>일별 성과 (저장된 데이터)</h2>
                    <div class="hint">중지 시 저장된 일별 데이터를 from ~ to 구간으로 조회합니다. 조회 값이 안 나오면 <a href="#" onclick="showPerformanceStoreStatus(); return false;">저장소 상태</a>에서 조회 사용자(username)와 테이블 연동을 확인하세요.</div>
                    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-bottom:12px;">
                        <div class="form-group" style="margin:0; min-width:auto;">
                            <label style="font-size:12px;">시작일</label>
                            <input type="date" id="perf_date_from" style="width:16ch; padding:6px 8px; font-size:13px;">
                        </div>
                        <div class="form-group" style="margin:0; min-width:auto;">
                            <label style="font-size:12px;">종료일</label>
                            <input type="date" id="perf_date_to" style="width:16ch; padding:6px 8px; font-size:13px;">
                        </div>
                        <button type="button" class="btn btn-inline" onclick="loadPerformanceDaily()" style="height:2rem; padding:0 10px; line-height:2rem;">조회</button>
                        <button type="button" class="btn btn-inline" onclick="exportPerformanceCsv()" style="height:2rem; padding:0 10px; line-height:2rem;">내보내기(CSV)</button>
                        <span id="performance_daily_status" style="margin-left:8px; font-size:13px; color:var(--muted);" aria-live="polite"></span>
                    </div>
                    <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px;">
                        <div style="font-size:12px; color:var(--muted);">
                            페이지 크기:
                            <select id="perf_page_size" onchange="onChangePerformancePageSize()" style="width:auto; padding:6px 8px; font-size:12px;">
                                <option value="10">10개씩 보기</option>
                                <option value="30" selected>30개씩 보기</option>
                                <option value="60">60개씩 보기</option>
                                <option value="90">90개씩 보기</option>
                            </select>
                        </div>
                        <div style="display:flex; align-items:center; gap:6px; font-size:12px;">
                            <button type="button" class="btn btn-inline" style="padding:4px 8px; font-size:12px;" onclick="changePerformancePage(-1)">이전</button>
                            <span id="performance_page_info">- / -</span>
                            <button type="button" class="btn btn-inline" style="padding:4px 8px; font-size:12px;" onclick="changePerformancePage(1)">다음</button>
                        </div>
                    </div>
                    <div id="performance_daily_grid_wrap" style="overflow-x:auto;">
                        <table id="performance_daily_table" class="perf-daily-table" style="display:none; width:100%; margin-top:8px;">
                            <thead>
                                <tr>
                                    <th>일자</th>
                                    <th>시작자산</th>
                                    <th>종료자산</th>
                                    <th>손익</th>
                                    <th>수익률%</th>
                                    <th>거래횟수</th>
                                </tr>
                            </thead>
                            <tbody id="performance_daily_tbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- 설정 탭 -->
        <div id="tab-settings" class="tab-content">
            

            <div id="settings-section-preset" class="settings-section active">
                <div class="card">
                    <h2>추천 프리셋</h2>
                    <div class="hint">
                        리스크·전략·종목선정을 한 번에 적용합니다. 용도에 맞는 프리셋을 선택한 뒤 적용하세요.
                    </div>
                    <div class="form-group">
                        <label>프리셋 선택:</label>
                        <div style="display:inline-flex; align-items:center; gap:10px; flex-wrap:wrap;">
                            <select id="recommended_preset_select" style="width:200px;" onchange="toggleSaveSlotButton()">
                                <option value="">선택하세요</option>
                                <option value="custom">커스텀(DB 저장값)</option>
                                <option value="1">커스텀1</option>
                                <option value="2">커스텀2</option>
                                <option value="3">커스텀3</option>
                                <option value="4">커스텀4</option>
                                <option value="5">커스텀5</option>
                                <option value="scalp_morning">오전 단타(9~12)</option>
                                <option value="scalp_fullday">전일 단타(오전~오후)</option>
                                <option value="scalp_conservative">보수적 단타</option>
                                <option value="scalp_aggressive">공격적 단타</option>
                            </select>
                            <button type="button" class="btn" onclick="applyRecommendedPreset()" style="padding:6px 14px; font-size:0.9rem; width:auto; flex-shrink:0;">프리셋 적용</button>
                            <button type="button" class="btn btn-primary" id="btn_save_to_slot" onclick="saveToSelectedSlot()" style="padding:6px 14px; font-size:0.9rem; display:none;" title="선택한 커스텀 슬롯(1~5)에 현재 설정 저장">선택 슬롯에 저장</button>
                        </div>
                        <div class="hint" style="margin-top:6px;">
                            커스텀: DB 저장값 불러오기. 커스텀1~5: 저장해 둔 설정 불러오기·적용. 적용 후 「선택 슬롯에 저장」으로 현재 설정을 해당 슬롯에 덮어쓸 수 있습니다.
                        </div>
                    </div>
                </div>
            </div>

            <div id="settings-section-risk" class="settings-section">
            <div class="card">
                <h2>리스크 관리</h2>
                    <div class="hint" id="risk_summary"></div>
                <div class="form-group">
                    <label>최대 거래 금액 (원): <code class="setting-var">max_single_trade_amount</code></label>
                    <input type="number" id="max_trade_amount" value="1000000">
                </div>
                    <div class="form-group">
                        <label>최소 매수 수량(주): <code class="setting-var">min_order_quantity</code></label>
                        <input type="number" id="min_order_quantity" value="1" min="1" max="1000">
                    </div>
                <div class="form-group">
                    <label>손절매 비율 (%): <code class="setting-var">stop_loss_ratio</code></label>
                    <input type="number" id="stop_loss" value="0.5" step="0.1" min="0.1" max="10" title="오전 단타는 0.5~1.2% 권장">
                    <div class="hint">오전 단타: 0.5~1.2% 권장. 2%는 스윙에 가깝습니다.</div>
                </div>
                <div class="form-group">
                    <label>익절매 비율 (%): <code class="setting-var">take_profit_ratio</code></label>
                    <input type="number" id="take_profit" value="1" step="0.1" min="0.2" max="20">
                </div>
                <div class="form-group">
                    <label>일일 손실 한도 (원): <code class="setting-var">daily_loss_limit</code></label>
                    <input type="number" id="daily_loss_limit" value="50000" min="0" step="10000">
                </div>
                    <div class="form-group">
                        <label>일일 손실 한도 기준: <code class="setting-var">daily_loss_limit_basis</code></label>
                        <select id="daily_loss_limit_basis">
                            <option value="realized">실현(체결 손익)</option>
                            <option value="total">실현+미실현(가정)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>일일 최대 거래 횟수 (매수+매도=1회): <code class="setting-var">max_trades_per_day</code></label>
                        <input type="number" id="max_trades_per_day" value="12" min="1" max="50">
                    </div>
                    <div class="form-group">
                        <label>종목별 일일 최대 거래 횟수 (0=미적용): <code class="setting-var">max_trades_per_stock_per_day</code></label>
                        <input type="number" id="max_trades_per_stock_per_day" value="0" min="0" max="20" title="각 종목당 오늘 N회까지 매수 허용. 0이면 전역만 적용">
                        <div class="hint">0=미적용(전역 max_trades_per_day만 적용). 1~2 권장. 한 종목이 휩쏘로 횟수를 다 쓰는 것 방지.</div>
                    </div>
                    <div class="form-group">
                        <label>동시 보유 종목 수 상한 (0=제한 없음): <code class="setting-var">max_positions_count</code></label>
                        <input type="number" id="max_positions_count" value="0" min="0" max="50">
                    </div>
                    <div class="form-group">
                        <label style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="expand_position_when_few_stocks" checked> 선정 1~2종목일 때 잔고 활용 확대 <code class="setting-var">expand_position_when_few_stocks</code></label>
                        <div class="hint">켜면: 1종목 100%, 2종목 50% each. 끄면 항상 종목당 max_position_size_ratio(기본 10%)만 사용.</div>
                    </div>
                    <div class="form-group">
                        <label>일일 이익 한도(원) (전량매도 트리거): <code class="setting-var">daily_profit_limit</code></label>
                        <input type="number" id="daily_profit_limit" value="50000" min="0" step="10000">
                        <div class="hint">dailyProfit ≥ dailyLoss 권장(대칭 한도). 예: 5만/5만.</div>
                    </div>
                    <div class="form-group">
                        <label>일일 이익 한도 기준: <code class="setting-var">daily_profit_limit_basis</code></label>
                        <select id="daily_profit_limit_basis">
                            <option value="total">실현+미실현(가정)</option>
                            <option value="realized">실현(체결 손익)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="daily_loss_limit_calendar" checked> 일일 손실 한도 기준일: 캘린더일</label>
                    </div>
                    <div class="form-group">
                        <label style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="daily_profit_limit_calendar" checked> 일일 이익 한도 기준일: 캘린더일</label>
                    </div>
                    <div class="form-group">
                        <label>월간 손실 한도(원,0=미적용):</label>
                        <input type="number" id="monthly_loss_limit" value="0" min="0" step="100000">
                    </div>
                    <div class="form-group">
                        <label>누적 손실 한도(원,0=미적용):</label>
                        <input type="number" id="cumulative_loss_limit" value="0" min="0" step="100000">
                    </div>
                    <div class="form-group">
                        <label style="color:var(--muted);">팁: “실현+미실현” 기반 손실 제한은 위의 ‘일일 손실 한도 기준’을 <strong>total</strong>로 바꾸면 됩니다.</label>
            </div>

                    <details>
                        <summary>고급(주문/재시도/사이징/트레일링)</summary>
                        <div class="form-group">
                            <label>매수 주문 방식:</label>
                            <select id="buy_order_style">
                                <option value="market">시장가</option>
                                <option value="best_limit">최우선 지정가</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>매도 주문 방식:</label>
                            <select id="sell_order_style">
                                <option value="market">시장가</option>
                                <option value="best_limit">최우선 지정가</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>주문 재시도 횟수:</label>
                            <input type="number" id="order_retry_count" value="0" min="0" max="10">
                        </div>
                        <div class="form-group">
                            <label>재시도 지연(ms):</label>
                            <input type="number" id="order_retry_delay_ms" value="300" min="0" max="10000" step="50">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="order_retry_exponential_backoff" checked>
                                네트워크 오류 시 지수 백오프
                            </label>
                        </div>
                        <div class="form-group">
                            <label>백오프 기준 지연(ms):</label>
                            <input type="number" id="order_retry_base_delay_ms" value="1000" min="200" max="10000" step="100">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="order_fallback_to_market" checked>
                                최우선 지정가 실패 시 시장가로 폴백
                            </label>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="enable_volatility_sizing">
                                변동성 기반 포지션 사이징 사용
                            </label>
                        </div>
                        <div class="form-group">
                            <label>변동성 lookback(N틱):</label>
                            <input type="number" id="volatility_lookback_ticks" value="20" min="2" max="300">
                        </div>
                        <div class="form-group">
                            <label>변동성 stop 배수:</label>
                            <input type="number" id="volatility_stop_mult" value="1.0" step="0.1" min="0.1" max="10">
                        </div>
                        <div class="form-group">
                            <label>종목당 최대 손실액(원):</label>
                            <input type="number" id="max_loss_per_stock_krw" value="0" min="0" step="10000">
                            <div class="hint">0이면 금액 기반. &gt;0이면 포지션 수량 = 이 값 / 손절거리(가격×SL%).</div>
                        </div>
                        <div class="form-group">
                            <label>슬리피지·체결지연 보정(bps):</label>
                            <input type="number" id="slippage_bps" value="20" min="0" max="500" step="5" title="손절/익절 판단 시 매수가 불리하게 체결된 것으로 가정">
                            <div class="hint">한국 시장 10~30bps(0.1~0.3%) 흔함. 0이면 미적용.</div>
                            <div class="hint">0=미적용. 10=0.1%, 50=0.5%. 보수적 손익 판단용.</div>
                        </div>
                        <div class="form-group">
                            <label>변동성 하한(가격 대비 비율):</label>
                            <input type="number" id="volatility_floor_ratio" value="0.005" min="0" max="0.05" step="0.001" title="틱 부족 시 최소 변동성(장 초반 사이징)">
                            <div class="hint">예: 0.005=0.5%. 틱 부족 시 이 비율로 risk 계산.</div>
                        </div>
                        <div class="form-group">
                            <label>진입 변동성 상한 (%): <code class="setting-var">max_intraday_vol_pct</code></label>
                            <input type="number" id="max_intraday_vol_pct" value="0" min="0" max="20" step="0.5" title="틱 변동성(가격 대비)이 이 값 초과면 매수 스킵. 0=미적용">
                            <div class="hint">0이면 미적용. 예: 3 = 최근 틱 변동성 3% 초과 시 진입 안 함.</div>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="atr_filter_enabled">
                                ATR(분봉) 변동성 필터 <code class="setting-var">atr_filter_enabled</code>
                            </label>
                            <div class="hint">분봉으로 ATR 계산. ATR/현재가 비율이 상한 초과면 매수 스킵. 0=미적용.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>ATR 기간(봉): <code class="setting-var">atr_period</code></label>
                            <input type="number" id="atr_period" value="14" min="2" max="30">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>ATR 비율 상한(%): <code class="setting-var">atr_ratio_max_pct</code></label>
                            <input type="number" id="atr_ratio_max_pct" value="0" step="0.1" min="0" max="20" placeholder="0=미적용">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="sap_deviation_filter_enabled">
                                SAP(세션 평균가) 이탈 필터 <code class="setting-var">sap_deviation_filter_enabled</code>
                            </label>
                            <div class="hint">당일 분봉 (H+L+C)/3 평균 대비 이탈률이 상한 초과면 매수 스킵(과열/과매도 구간).</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>이탈률 상한(%): <code class="setting-var">sap_deviation_max_pct</code></label>
                            <input type="number" id="sap_deviation_max_pct" value="3" step="0.5" min="0.5" max="20">
                        </div>
                        <details>
                            <summary>레거시(합산 손실 한도)</summary>
                            <div class="form-group">
                                <label>일일 손실 한도(원) (레거시: 실현+미실현, 전량매도):</label>
                                <input type="number" id="daily_total_loss_limit" value="0" min="0" step="10000">
                            </div>
                            <div class="hint" style="margin-top:-6px;">
                                신규 방식은 <code>daily_loss_limit</code> + <code>daily_loss_limit_basis=total</code> 사용을 권장합니다.
                            </div>
                        </details>
                        <div class="form-group">
                            <label>부분 익절 트리거(%): <code class="setting-var">partial_take_profit_ratio</code></label>
                            <input type="number" id="partial_tp_pct" value="0" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label>부분 익절 비율(%): <code class="setting-var">partial_take_profit_fraction</code></label>
                            <input type="number" id="partial_tp_fraction_pct" value="50" step="5" min="0" max="100">
                        </div>
                        <div class="form-group">
                            <label>트레일링 스탑 (%): <code class="setting-var">trailing_stop_ratio</code></label>
                            <input type="number" id="trailing_stop_pct" value="0.5" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label>트레일링 활성화 최소 수익(%): <code class="setting-var">trailing_activation_ratio</code></label>
                            <input type="number" id="trailing_activation_pct" value="0.6" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="use_atr_for_stop_take">
                                ATR(틱 변동성) 배수 손절/익절 사용 <code class="setting-var">use_atr_for_stop_take</code>
                            </label>
                            <div class="hint">체크 시 고정 비율 대신 변동성 배수로 손절/익절 거리 적용</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>ATR 손절 배수:</label>
                            <input type="number" id="atr_stop_mult" value="1.5" step="0.1" min="0.5" max="5">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>ATR 익절 배수:</label>
                            <input type="number" id="atr_take_mult" value="2" step="0.1" min="0.5" max="10">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>ATR lookback(틱):</label>
                            <input type="number" id="atr_lookback_ticks" value="20" min="2" max="300">
                        </div>
                        <div class="form-group">
                            <label>주문 허용 최소 가격 변동(%): <code class="setting-var">min_price_change_ratio</code></label>
                            <input type="number" id="min_price_change_ratio_pct" value="0" step="0.1" min="0" max="10" title="직전 1틱 대비 이만큼 변동해야 매수 실행. 0=미적용(보통 권장), 1% 이상=급등 순간만 매수">
                            <span class="hint">직전 틱 대비. 0=미적용(보편적), 1% 이상이면 급등한 순간만 허용</span>
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
                        <label>프리셋:</label>
                        <select id="strategy_preset_select" onchange="onStrategyPresetChange()">
                            <option value="">직접 설정</option>
                            <optgroup label="MA-only (고급 유지)">
                                <option value="ma_fast_3_10">MA 빠름 3/10</option>
                                <option value="ma_safe_5_20">MA 보수 5/20</option>
                                <option value="ma_mid_8_21">MA 중기 8/21</option>
                            </optgroup>
                            <optgroup label="단타 프리셋 (고급 포함)">
                                <option value="scalp_morning_balanced">오전 단타(밸런스)</option>
                                <option value="scalp_morning_strict">오전 단타(엄격)</option>
                                <option value="scalp_light">단타(가벼움)</option>
                            </optgroup>
                        </select>
                        <div class="hint" style="margin-top:8px;">
                            MA-only는 이동평균만 변경(다른 고급값 유지). 단타 프리셋은 고급(보강/레짐/진입직전/청산)까지 함께 설정합니다.
                        </div>
                    </div>
                    <div class="form-group">
                        <label>단기 이동평균 (틱): <code class="setting-var">short_ma_period</code></label>
                        <input type="number" id="short_ma_period" value="3" min="2" max="60">
                    </div>
                    <div class="form-group">
                        <label>장기 이동평균 (틱): <code class="setting-var">long_ma_period</code></label>
                        <input type="number" id="long_ma_period" value="10" min="3" max="200">
                    </div>
                    <div class="form-group">
                        <label>진입 후 최소 보유 시간(초): <code class="setting-var">min_hold_seconds</code></label>
                        <input type="number" id="min_hold_seconds" value="0" min="0" max="600" title="매수 직후 데드크로스로 즉시 매도되는 것 방지. 0=미적용, 30~60 권장">
                        <span class="hint">0=미적용. 30~60초 권장(같은 가격에 매수→매도 반복 방지)</span>
                    </div>
                    <div class="form-group">
                        <label>신규 매수 허용 시작 (HH:MM, KST): <code class="setting-var">buy_window_start_hhmm</code></label>
                        <input type="text" id="buy_window_start_hhmm" value="09:05" placeholder="09:05">
                    </div>
                    <div class="form-group">
                        <label>신규 매수 허용 종료 (HH:MM, KST): <code class="setting-var">buy_window_end_hhmm</code></label>
                        <input type="text" id="buy_window_end_hhmm" value="11:30" placeholder="11:30">
                    </div>

                    <details>
                        <summary>고급(필터/쿨다운/보강/레짐/청산)</summary>
                        <div class="form-group">
                            <label>단기MA 기울기 최소(%/틱): <code class="setting-var">min_short_ma_slope_ratio</code></label>
                            <input type="number" id="min_short_ma_slope_pct" value="0" step="0.001" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>모멘텀 확인: 최근 N틱 <code class="setting-var">momentum_lookback_ticks</code></label>
                            <input type="number" id="momentum_lookback_ticks" value="0" min="0" max="200">
                        </div>
                        <div class="form-group">
                            <label>모멘텀 최소 상승률(%) <code class="setting-var">min_momentum_ratio</code></label>
                            <input type="number" id="min_momentum_pct" value="0" step="0.01" min="0" max="20">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="avoid_chase_near_high_enabled">
                                진입 직전: 고점 근접 추격 회피 <code class="setting-var">avoid_chase_near_high_enabled</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>고점 lookback(분) / “고점 대비 하락폭” 최소(%) <code class="setting-var">near_high_lookback_minutes</code> / <code class="setting-var">avoid_near_high_ratio</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                                <input type="number" id="near_high_lookback_minutes" value="2" min="1" max="30">
                                <input type="number" id="avoid_near_high_pct" value="0.30" step="0.05" min="0" max="5">
                            </div>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="avoid_near_high_dynamic">
                                고점근접 회피 임계값을 변동성 기반으로 자동 상향 <code class="setting-var">avoid_near_high_dynamic</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>고점근접 정규화 배수(0=사용안함) <code class="setting-var">avoid_near_high_vs_vol_mult</code></label>
                            <input type="number" id="avoid_near_high_vs_vol_mult" value="0" step="0.1" min="0" max="20">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="minute_trend_enabled">
                                진입 직전: 1~2분봉 추세 유지(양봉 유지) <code class="setting-var">minute_trend_enabled</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>분봉 추세 모드: <code class="setting-var">minute_trend_mode</code></label>
                            <select id="minute_trend_mode">
                                <option value="green">양봉 유지(개수)</option>
                                <option value="higher_close">종가 상승 유지</option>
                                <option value="higher_low">저가 상승 유지</option>
                                <option value="hh_hl">고가/저가 상승 유지</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="minute_trend_early_only">
                                분봉 추세 필터를 초반 레짐(09:00~종료)에서만 적용 <code class="setting-var">minute_trend_early_only</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>분봉 lookback(개) / 최소 양봉 개수 <code class="setting-var">minute_trend_lookback_bars</code> / <code class="setting-var">minute_trend_min_green_bars</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                                <input type="number" id="minute_trend_lookback_bars" value="2" min="1" max="5">
                                <input type="number" id="minute_trend_min_green_bars" value="2" min="0" max="5">
                            </div>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="entry_confirm_enabled">
                                진입 보강(2단) 사용: 추세 조건 + 아래 조건 중 N개 이상 <code class="setting-var">entry_confirm_enabled</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>보강 조건 최소 충족 개수(N): <code class="setting-var">entry_confirm_min_count</code></label>
                            <input type="number" id="entry_confirm_min_count" value="1" min="1" max="3">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="confirm_breakout_enabled">
                                (보강) 최근 N틱 신고가 돌파 <code class="setting-var">confirm_breakout_enabled</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>돌파 lookback(N틱) / 버퍼(%) <code class="setting-var">breakout_lookback_ticks</code> / <code class="setting-var">breakout_buffer_ratio</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                                <input type="number" id="breakout_lookback_ticks" value="20" min="2" max="300">
                                <input type="number" id="breakout_buffer_pct" value="0" step="0.01" min="0" max="5">
                            </div>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="confirm_volume_surge_enabled">
                                (보강) 거래량 급증(틱 체결량) <code class="setting-var">confirm_volume_surge_enabled</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>거래량 급증: lookback(N틱) / 배수 <code class="setting-var">volume_surge_lookback_ticks</code> / <code class="setting-var">volume_surge_ratio</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                                <input type="number" id="volume_surge_lookback_ticks" value="20" min="2" max="200">
                                <input type="number" id="volume_surge_ratio" value="2.0" step="0.1" min="1.0" max="20">
                            </div>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="confirm_trade_value_surge_enabled">
                                (보강) 거래대금 급증(틱 체결량×가격) <code class="setting-var">confirm_trade_value_surge_enabled</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>거래대금 급증: lookback(N틱) / 배수 <code class="setting-var">trade_value_surge_lookback_ticks</code> / <code class="setting-var">trade_value_surge_ratio</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                                <input type="number" id="trade_value_surge_lookback_ticks" value="20" min="2" max="200">
                                <input type="number" id="trade_value_surge_ratio" value="2.0" step="0.1" min="1.0" max="50">
                            </div>
                        </div>
                        <div class="form-group">
                            <label>변동성 정규화 lookback(N틱) <code class="setting-var">vol_norm_lookback_ticks</code></label>
                            <input type="number" id="vol_norm_lookback_ticks" value="20" min="2" max="300">
                        </div>
                        <div class="form-group">
                            <label>slope 정규화 배수(0=사용안함) <code class="setting-var">slope_vs_vol_mult</code></label>
                            <input type="number" id="slope_vs_vol_mult" value="0" step="0.1" min="0" max="20">
                        </div>
                        <div class="form-group">
                            <label>range 정규화 배수(0=사용안함) <code class="setting-var">range_vs_vol_mult</code></label>
                            <input type="number" id="range_vs_vol_mult" value="0" step="0.1" min="0" max="20">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="enable_morning_regime_split">
                                오전장 레짐 분기(초반/메인) 사용 <code class="setting-var">enable_morning_regime_split</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>초반 레짐 종료(HH:MM, KST) <code class="setting-var">morning_regime_early_end_hhmm</code></label>
                            <input type="text" id="morning_regime_early_end_hhmm" value="09:10" placeholder="09:10">
                        </div>
                        <div class="form-group">
                            <label>초반 레짐: slope 최소(%/틱) <code class="setting-var">early_min_short_ma_slope_ratio</code></label>
                            <input type="number" id="early_min_short_ma_slope_pct" value="0" step="0.001" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>초반 레짐: 모멘텀 N틱 / 최소 상승률(%) <code class="setting-var">early_momentum_lookback_ticks</code> / <code class="setting-var">early_min_momentum_ratio</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                                <input type="number" id="early_momentum_lookback_ticks" value="0" min="0" max="200">
                                <input type="number" id="early_min_momentum_pct" value="0" step="0.01" min="0" max="20">
                            </div>
                        </div>
                        <div class="form-group">
                            <label>초반 레짐: 진입 확인(연속 틱 수) <code class="setting-var">early_buy_confirm_ticks</code></label>
                            <input type="number" id="early_buy_confirm_ticks" value="1" min="1" max="10">
                        </div>
                        <div class="form-group">
                            <label>초반 레짐: 최대 스프레드(%) <code class="setting-var">early_max_spread_ratio</code></label>
                            <input type="number" id="early_max_spread_pct" value="0" step="0.01" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>초반 레짐: 횡보장 제외(N틱/레인지%) <code class="setting-var">early_range_lookback_ticks</code> / <code class="setting-var">early_min_range_ratio</code></label>
                            <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px;">
                                <input type="number" id="early_range_lookback_ticks" value="0" min="0" max="300">
                                <input type="number" id="early_min_range_pct" value="0" step="0.01" min="0" max="20">
                                <div class="hint" style="margin:0; align-self:center;">(N/%)</div>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>재진입 쿨다운(초): <code class="setting-var">reentry_cooldown_seconds</code></label>
                            <input type="number" id="reentry_cooldown_seconds" value="240" min="0" max="3600">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="consecutive_loss_cooldown_enabled">
                                연속 손실 시 쿨다운 확대 <code class="setting-var">consecutive_loss_cooldown_enabled</code>
                            </label>
                            <div class="hint">연속 N회 손실 후, 재진입 쿨다운 × 배수만큼 대기 후 다음 매수 허용.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>연속 손실 횟수 (N): <code class="setting-var">consecutive_loss_count_threshold</code></label>
                            <input type="number" id="consecutive_loss_count_threshold" value="2" min="2" max="5">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>쿨다운 배수: <code class="setting-var">consecutive_loss_cooldown_mult</code></label>
                            <input type="number" id="consecutive_loss_cooldown_mult" value="2" min="1" max="5" step="0.5">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="circuit_breaker_filter_enabled" checked>
                                거래소 서킷(급락) 필터 <code class="setting-var">circuit_breaker_filter_enabled</code>
                            </label>
                            <div class="hint">전일 대비 지수 하락률이 N% 이하이면 신규 매수 스킵. KRX 1단계 서킷(~-8%) 직전 대응.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>지수: <code class="setting-var">circuit_breaker_market</code></label>
                            <select id="circuit_breaker_market">
                                <option value="0001">코스피(0001)</option>
                                <option value="1001">코스닥(1001)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>하락률 임계(%): <code class="setting-var">circuit_breaker_threshold_pct</code></label>
                            <input type="number" id="circuit_breaker_threshold_pct" value="-7" min="-20" max="0" step="0.5" title="-7 = 7% 하락 시 스킵">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>서킷 시 동작: <code class="setting-var">circuit_breaker_action</code></label>
                            <select id="circuit_breaker_action">
                                <option value="skip_buy_only">신규 매수만 스킵</option>
                                <option value="liquidate_all">전량 청산</option>
                                <option value="liquidate_partial">일부 청산(50%)</option>
                                <option value="no_buy_rest_of_day">당일 매수 금지</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="sidecar_filter_enabled" checked>
                                사이드카 구간 필터 <code class="setting-var">sidecar_filter_enabled</code>
                            </label>
                            <div class="hint">지수 ±5%(코스피)/±6%(코스닥) 변동 시 N분간 신규 매수 스킵. KRX 프로그램매매 5분 정지에 맞춤.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>지수: <code class="setting-var">sidecar_market</code></label>
                            <select id="sidecar_market">
                                <option value="0001">코스피(0001)</option>
                                <option value="1001">코스닥(1001)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>냉각(분): <code class="setting-var">sidecar_cooling_minutes</code></label>
                            <input type="number" id="sidecar_cooling_minutes" value="5" min="1" max="30" title="변동 감지 후 매수 스킵 시간">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>사이드카 시 동작: <code class="setting-var">sidecar_action</code></label>
                            <select id="sidecar_action">
                                <option value="skip_buy_only">신규 매수만 스킵</option>
                                <option value="liquidate_all">전량 청산</option>
                                <option value="liquidate_partial">일부 청산(50%)</option>
                                <option value="no_buy_rest_of_day">당일 매수 금지</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="vi_filter_enabled" checked>
                                VI(종목별 변동성완화장치) 필터 <code class="setting-var">vi_filter_enabled</code>
                            </label>
                            <div class="hint">VI 발동 종목은 N분간 해당 종목만 매수 스킵.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>해당 종목 냉각(분):</label>
                            <input type="number" id="vi_cooling_minutes" value="5" min="1" max="30">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="index_ma_filter_enabled">
                                지수 MA 시장 레짐 필터 <code class="setting-var">index_ma_filter_enabled</code>
                            </label>
                            <div class="hint">지수(코스닥/코스피)가 N일 MA 미만이면 매수 전부 스킵. 하락장 진입 억제.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>지수: <code class="setting-var">index_ma_code</code></label>
                            <select id="index_ma_code">
                                <option value="1001">코스닥(1001)</option>
                                <option value="0001">코스피(0001)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>MA 기간(일): <code class="setting-var">index_ma_period</code></label>
                            <input type="number" id="index_ma_period" value="20" min="5" max="60">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="advance_ratio_filter_enabled">
                                상승 종목 비율 시장 레짐 필터 <code class="setting-var">advance_ratio_filter_enabled</code>
                            </label>
                            <div class="hint">등락률 순위 API 기준 상승/하락 건수 비율. N% 미만이면 매수 스킵.</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>시장:</label>
                            <select id="advance_ratio_market">
                                <option value="1001">코스닥(1001)</option>
                                <option value="0001">코스피(0001)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>상승 비율 하한(%): <code class="setting-var">advance_ratio_min_pct</code></label>
                            <input type="number" id="advance_ratio_min_pct" value="35" min="0" max="100" step="5">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="advance_ratio_down_market_skip" checked>
                                하락장 강화(상승비율 &lt;50% 시 전량 매수 스킵) <code class="setting-var">advance_ratio_down_market_skip</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="trade_value_concentration_filter_enabled">
                                거래대금 집중 시장 레짐 필터 <code class="setting-var">trade_value_concentration_filter_enabled</code>
                            </label>
                            <div class="hint">상위 N종목 거래대금/상위 M종목 비율이 X% 초과면 매수 스킵(좁은 시장).</div>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>시장:</label>
                            <select id="trade_value_concentration_market">
                                <option value="1001">코스닥(1001)</option>
                                <option value="0001">코스피(0001)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>상위 N종목:</label>
                            <input type="number" id="trade_value_concentration_top_n" value="10" min="2" max="20">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>분모 상위 M종목:</label>
                            <input type="number" id="trade_value_concentration_denom_n" value="30" min="5" max="50">
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>집중도 상한(%):</label>
                            <input type="number" id="trade_value_concentration_max_pct" value="45" min="10" max="80" step="5">
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
                            <label>횡보장 제외: 최근 N틱 <code class="setting-var">range_lookback_ticks</code></label>
                            <input type="number" id="range_lookback_ticks" value="0" min="0" max="300">
                        </div>
                        <div class="form-group">
                            <label>횡보장 제외: 최소 레인지(%) <code class="setting-var">min_range_ratio</code></label>
                            <input type="number" id="min_range_pct" value="0" step="0.01" min="0" max="20">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="use_sap_revert_entry">
                                SAP 풀백 진입 보조 사용 <code class="setting-var">use_sap_revert_entry</code>
                            </label>
                            <div class="hint">당일 세션 평균가(SAP) 대비 특정 하단 구간(%)에서만 신규 매수 허용. MA 크로스+필터가 모두 통과해도 SAP 범위를 벗어나면 매수 스킵.</div>
                        </div>
                        <div class="form-group">
                            <label>SAP 풀백 진입 구간(%): <code class="setting-var">sap_revert_entry_from_pct</code> ~ <code class="setting-var">sap_revert_entry_to_pct</code></label>
                            <div style="display:flex; align-items:center; gap:6px;">
                                <input type="number" id="sap_revert_entry_from_pct" value="-1.5" step="0.1" min="-20" max="0">
                                <span>~</span>
                                <input type="number" id="sap_revert_entry_to_pct" value="-0.5" step="0.1" min="-20" max="0">
                            </div>
                            <div class="hint">예: -1.5 ~ -0.5 → SAP보다 0.5~1.5% 아래 구간에서만 신규 매수 허용(실제 변동폭에 맞춤).</div>
                        </div>
                        <div class="form-group">
                            <label>진입 거래량 하한(평균 대비 배수, 0=미적용):</label>
                            <input type="number" id="min_volume_ratio_for_entry" value="0" step="0.1" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>진입 거래대금 하한(평균 대비 배수, 0=미적용):</label>
                            <input type="number" id="min_trade_amount_ratio_for_entry" value="0" step="0.1" min="0" max="5">
                        </div>
                        <div class="form-group">
                            <label>장 초반 매수 스킵(분, 09:00 KST 기준, 0=미적용): <code class="setting-var">skip_buy_first_minutes</code></label>
                            <input type="number" id="skip_buy_first_minutes" value="0" min="0" max="30">
                        </div>
                        <div class="form-group">
                            <label>장 마감 전 N분 매수 스킵(0=미적용): <code class="setting-var">last_minutes_no_buy</code></label>
                            <input type="number" id="last_minutes_no_buy" value="0" min="0" max="60">
                        </div>
                        <div class="form-group">
                            <label>고점 대비 하락 시 매수 스킵(%): <code class="setting-var">skip_buy_below_high_pct</code></label>
                            <input type="number" id="skip_buy_below_high_pct" value="0" min="0" max="20" step="0.1" title="당일 세션 고점 대비 이 비율 이상 하락 시 매수 스킵. 0=미적용. 고점 꺾인 후 하락추세 진입 방지용(예: 1~2%).">
                            <div class="hint">0=미적용. 당일 고점 대비 N% 이상 내려온 구간에서는 매수하지 않습니다(하락추세 진입 방지).</div>
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="relative_strength_filter_enabled">
                                지수 대비 상대 강도 필터(종목 변동률 &gt; 지수+margin일 때만 매수) <code class="setting-var">relative_strength_filter_enabled</code>
                            </label>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>지수:</label>
                            <select id="relative_strength_index_code">
                                <option value="0001">코스피(0001)</option>
                                <option value="1001">코스닥(1001)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-left:12px;">
                            <label>margin(%):</label>
                            <input type="number" id="relative_strength_margin_pct" value="0" step="0.1">
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
                    <label>최소 상승률 (%): <code class="setting-var">min_price_change_ratio</code></label>
                    <input type="number" id="min_change" value="1" step="0.1">
                </div>
                <div class="form-group">
                    <label>최대 상승률 (%): <code class="setting-var">max_price_change_ratio</code></label>
                    <input type="number" id="max_change" value="15" step="0.1">
                </div>
                <div class="form-group">
                        <label>선정 후보군 수(최대 20): <code class="setting-var">max_stocks</code></label>
                        <input type="number" id="max_stocks" value="10" min="1" max="20">
                </div>
                    <div class="form-group">
                        <label>최소 가격 (원): <code class="setting-var">min_price</code></label>
                        <input type="number" id="min_price" value="1000">
                    </div>
                    <div class="form-group">
                        <label>최대 가격 (원): <code class="setting-var">max_price</code></label>
                        <input type="number" id="max_price" value="2000000">
                    </div>
                    <div class="form-group">
                        <label>최소 거래량 (주): <code class="setting-var">min_volume</code></label>
                        <input type="number" id="min_volume" value="50000">
                    </div>
                    <div class="form-group">
                        <label>최소 거래대금 (원): <code class="setting-var">min_trade_amount</code></label>
                        <input type="number" id="min_trade_amount" value="0">
                    </div>
                    <div class="form-group">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="kospi_only">
                            코스피만 (코스닥 제외) <code class="setting-var">kospi_only</code>
                        </label>
                        <div class="hint">체크 시 등락률 순위에서 거래소(코스피) 종목만 선정합니다. 코스닥은 변동성·스프레드가 클 수 있어 제외할 때 유리합니다.</div>
                    </div>

                    <details>
                        <summary>고급(장초/드로우다운)</summary>
                        <div class="form-group">
                            <label>선정 정렬 기준: <code class="setting-var">sort_by</code></label>
                            <select id="stock_sort_by">
                                <option value="change">등락률(기본)</option>
                                <option value="trade_amount">당일 거래대금(가능시)</option>
                                <option value="prev_day_trade_value">전일 거래대금(추정, 느림)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>전일 거래대금 정렬 후보 pool 크기: <code class="setting-var">prev_day_rank_pool_size</code></label>
                            <input type="number" id="prev_day_rank_pool_size" value="80" min="10" max="200" step="10">
                        </div>
                        <div class="form-group">
                            <label>장 시작 시각 (HH:MM): <code class="setting-var">market_open_hhmm</code></label>
                            <input type="text" id="market_open_hhmm" value="09:00" placeholder="09:00">
                        </div>
                        <div class="form-group">
                            <label>장초 워밍업(분): <code class="setting-var">warmup_minutes</code></label>
                            <input type="number" id="warmup_minutes" value="5" min="0" max="60">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="early_strict">
                                장초 강화 필터 사용(초기 변동 노이즈 완화) <code class="setting-var">early_strict</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>장초 강화 적용 시간(분): <code class="setting-var">early_strict_minutes</code></label>
                            <input type="number" id="early_strict_minutes" value="30" min="1" max="180">
                        </div>
                        <div class="form-group">
                            <label>장초 강화 최소 거래량(주): <code class="setting-var">early_min_volume</code></label>
                            <input type="number" id="early_min_volume" value="200000" min="0">
                        </div>
                        <div class="form-group">
                            <label>장초 강화 최소 거래대금(원): <code class="setting-var">early_min_trade_amount</code></label>
                            <input type="number" id="early_min_trade_amount" value="0" min="0">
                        </div>
                        <div class="form-group">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="exclude_drawdown">
                                고점 대비 하락추세 종목 제외(장중 후행 진입 방지) <code class="setting-var">exclude_drawdown</code>
                            </label>
                        </div>
                        <div class="form-group">
                            <label>고점 대비 최대 허용 하락폭(%): <code class="setting-var">max_drawdown_from_high_ratio</code></label>
                            <input type="number" id="max_drawdown_pct" value="12.0" step="0.1" min="0" max="50">
                        </div>
                        <div class="form-group">
                            <label>하락추세 제외 적용 시작 시각(HH:MM): <code class="setting-var">drawdown_filter_after_hhmm</code></label>
                            <input type="text" id="drawdown_filter_after_hhmm" value="12:00" placeholder="12:00">
                            <div class="hint">이 시각 이후에만 고점 대비 하락 필터를 적용합니다. 장초(9~10시) 재선정 시 12:00으로 두면 필터가 적용되지 않아 후보가 잘 걸립니다.</div>
                        </div>
                    </details>

                    <div class="btn-group" style="grid-template-columns: 1fr 1fr;">
                        <button class="btn" onclick="updateStockSelection()">저장</button>
                        <button class="btn" onclick="selectStocks()">종목 재선정</button>
                    </div>
                </div>
            </div>

            <div id="settings-section-operational" class="settings-section">
                <div class="card">
                    <h2>운영 옵션</h2>
                    <div class="form-group">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="enable_auto_rebalance">
                            자동 리밸런싱 (종목 주기 재선정)
                        </label>
                        <div class="hint">시스템 구동 중 설정 간격마다 종목을 재선정합니다. 갱신된 목록은 다음 시스템 시작 시 적용됩니다.</div>
                    </div>
                    <div class="form-group">
                        <label>리밸런싱 간격 (분):</label>
                        <input type="number" id="auto_rebalance_interval_minutes" value="30" min="5" max="120" step="5">
                    </div>
                    <div class="form-group">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="enable_performance_auto_recommend">
                            성과 기반 자동 추천 표시
                        </label>
                        <div class="hint">설정 간격마다 성과 요약을 계산해 권장 문구를 로그에 브로드캐스트합니다. 설정은 자동 적용되지 않습니다.</div>
                    </div>
                    <div class="form-group">
                        <label>추천 알림 간격 (분):</label>
                        <input type="number" id="performance_recommend_interval_minutes" value="5" min="1" max="60" step="1">
                    </div>
                    <div class="form-group">
                        <label>WebSocket 재연결 대기 (초):</label>
                        <input type="number" id="ws_reconnect_sleep_sec" value="5" min="3" max="60" title="연결 끊김 후 재연결 시도 전 대기 시간">
                    </div>
                    <div class="form-group">
                        <label>긴급 청산: 단절 N분 (0=미적용):</label>
                        <input type="number" id="emergency_liquidate_disconnect_minutes" value="0" min="0" max="120" title="WS가 N분 이상 끊긴 뒤 복구 시 전량 매도. 0이면 사용 안 함">
                    </div>
                    <div class="form-group">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="keep_previous_on_empty_selection" checked>
                            종목 선정 결과 0건 시 이전 목록 유지
                        </label>
                        <div class="hint">선정 API가 빈 결과를 반환해도 기존 선정 종목 목록을 비우지 않고 유지합니다.</div>
                    </div>
                    <hr style="margin:16px 0; border:0; border-top:1px solid var(--border);">
                    <h3 style="font-size:14px; margin-bottom:8px;">매일 자동 시작/종료 (KST)</h3>
                    <div class="form-group">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="auto_schedule_enabled">
                            자동 스케줄 사용 (매일 지정 시각에 시작·종료)
                        </label>
                        <div class="hint">앱이 켜져 있는 동안 매일 자동 시작 시각에 시스템 시작, 자동 종료 시각에 시스템 중지합니다. AWS에서는 EventBridge(CloudWatch Events) 규칙으로 cron 표현식(예: 9:30 KST)에 POST /api/system/start·stop 호출도 가능합니다.</div>
                    </div>
                    <div class="form-group">
                        <label>자동 시작 시각 (HH:MM):</label>
                        <input type="text" id="auto_start_hhmm" value="09:30" placeholder="09:30" maxlength="5" style="width:80px;">
                    </div>
                    <div class="form-group">
                        <label>자동 종료 시각 (HH:MM):</label>
                        <input type="text" id="auto_stop_hhmm" value="12:00" placeholder="12:00" maxlength="5" style="width:80px;">
                    </div>
                    <div class="form-group">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="liquidate_on_auto_stop" checked>
                            자동 종료 시 보유 종목 청산
                        </label>
                        <div class="hint">종료 시각에 중지할 때 보유 포지션을 전량 시장가 매도한 뒤 중지합니다.</div>
                    </div>
                    <div class="form-group">
                        <label>자동 스케줄 실행 사용자:</label>
                        <input type="text" id="auto_schedule_username" value="" placeholder="비면 admin" style="width:120px;">
                        <div class="hint">자동 시작/종료 시 사용할 계정. 비우면 admin 사용.</div>
                    </div>
                    <button class="btn" onclick="updateOperationalConfig()">운영 옵션 저장</button>
                </div>
            </div>

            <div id="settings-section-help" class="settings-section">
                <div class="card">
                    <h2>설정 도움말</h2>
                    <div class="hint">
                        아래 설명은 “현재 시스템 구현 기준”으로, 값이 커질수록 보수적/공격적이 되는 방향을 함께 적었습니다.
                        % 항목은 화면에는 퍼센트(예: 2.0)로 넣고, 내부에서는 비율(0.02)로 저장됩니다. 저장 후 다른 탭을 갔다 와도 설정이 유지되도록 각 탭에서 반드시 「저장」 버튼을 눌러 주세요.
                    </div>

                    <details>
                        <summary>추천 프리셋</summary>
                        <div class="help-grid">
                            <div class="help-item">
                                <strong>추천 프리셋이란?</strong>
                                리스크·전략·종목선정 값을 한 번에 맞춰 주는 묶음 설정입니다. 용도에 맞는 항목을 선택한 뒤 「프리셋 적용」을 누르면, 해당 프리셋의 기본값이 폼에 채워지고 저장·종목 재선정까지 순서대로 실행됩니다.
                            </div>
                            <div class="help-item">
                                <strong>오전 단타(9~12)</strong>
                                매수 창 09:05~11:30(KST), 11:55 시간 청산. 손절·익절·일일 한도·변동성 필터(ATR/SAP)·시장 레짐(지수 MA, 상승 비율) 등이 단타에 맞게 설정됩니다.
                            </div>
                            <div class="help-item">
                                <strong>전일 단타(오전~오후)</strong>
                                매수 창 09:05~15:20, 15:25 시간 청산. 오전 단타와 동일한 전략·리스크 구조에, 장 마감 직전까지 매수·청산을 허용하는 버전입니다.
                            </div>
                            <div class="help-item">
                                <strong>보수적 단타 / 공격적 단타</strong>
                                매수 창은 오전 단타와 동일(11:30/11:55). 보수적은 손절·익절을 더 타이트하게, 일일 거래 횟수·동시 보유 종목 수를 줄입니다. 공격적은 손절·익절을 넓히고 거래 횟수·동시 보유 종목을 늘립니다.
                            </div>
                        </div>
                    </details>

                    <details open>
                        <summary>리스크 관리</summary>
                        <div class="help-grid">
                            <div class="help-item">
                                <strong>최대 거래 금액 (원) (<code>max_single_trade_amount</code>)</strong>
                                한 번의 매수에서 쓸 수 있는 최대 금액입니다. 이 값을 넘는 주문은 실행되지 않습니다. 너무 크면 종목당 손익 변동이 커지므로, 단타에서는 50~200만 원 구간을 많이 씁니다.
                            </div>
                            <div class="help-item">
                                <strong>최소 매수 수량(주) (<code>min_order_quantity</code>)</strong>
                                매수 시 최소 수량을 강제합니다. 너무 크게 잡으면 “조건은 좋은데 주문이 거절(수량 부족)”될 수 있습니다.
                            </div>
                            <div class="help-item">
                                <strong>일일 최대 거래 횟수 (<code>max_trades_per_day</code>)</strong>
                                하루에 허용하는 <strong>매수</strong> 횟수입니다(매도는 제한 없음). 예: 5이면 매수를 최대 5번까지 할 수 있고, 그에 대응하는 매도는 제한 없이 가능합니다. <strong>적정값</strong>: 종목선정 “최대 선정 종목 수”(<code>max_stocks</code>)보다 작으면 선정된 종목을 전부 살 수 없으므로, <code>max_stocks</code> 이상으로 두는 것이 좋습니다. 여유를 두려면 max_stocks+2~max_stocks×1.5(예: 선정 5종목 → 5~8, 선정 10종목 → 10~15). 단타·보수적이면 5~8, 조금 더 유연하게 10~15.
                            </div>
                            <div class="help-item">
                                <strong>종목별 일일 최대 거래 횟수 (<code>max_trades_per_stock_per_day</code>)</strong>
                                0이면 미적용(전역 max_trades_per_day만 적용). 1 이상이면 각 종목당 오늘 N회까지만 매수 허용. 한 종목이 휩쏘로 전역 한도를 다 써버리는 것을 막을 수 있습니다. 1~2 권장.
                            </div>
                            <div class="help-item">
                                <strong>동시 보유 종목 수 상한 (<code>max_positions_count</code>)</strong>
                                동시에 보유할 수 있는 종목 수의 상한입니다. 0이면 제한 없음, 1~2로 두면 한두 종목만 보유하는 집중 운영이 됩니다. 리스크 분산을 원하면 3~5 정도로 넉넉히 둡니다.
                            </div>
                            <div class="help-item">
                                <strong>손절매 비율(%) (<code>stop_loss_ratio</code>)</strong>
                                매수가 대비 손실률이 이 값에 도달하면 매도 신호를 냅니다. 값이 작을수록 빨리 손절(보수적)합니다. 단타에서는 0.5~1.2%를 많이 씁니다.
                            </div>
                            <div class="help-item">
                                <strong>익절매 비율(%) (<code>take_profit_ratio</code>)</strong>
                                매수가 대비 수익률이 이 값에 도달하면 매도 신호를 냅니다. 손절 대비 2배 정도(예: 손절 0.8%·익절 1.8%)로 두면 손익비를 맞추기 쉽습니다.
                            </div>
                            <div class="help-item">
                                <strong>ATR(틱 변동성) 배수 손절/익절 (<code>use_atr_for_stop_take</code>)</strong>
                                켜면 고정 % 대신 “최근 틱 변동성(ATR 대용)”의 배수로 손절·익절 거리를 정합니다. 변동성이 큰 종목은 손절선이 넓어지고, 작은 종목은 좁아져 자동으로 맞춥니다. <code>atr_stop_mult</code>(손절 배수), <code>atr_take_mult</code>(익절 배수)로 조절합니다.
                            </div>
                            <div class="help-item">
                                <strong>일일 손실 한도 (원) (<code>daily_loss_limit</code>)</strong>
                                당일 실현 손익(또는 설정에 따라 실현+미실현 합산)이 이 한도 이하로 떨어지면 신규 매수가 차단됩니다. 단타에서는 3~10만 원 구간을 많이 씁니다.
                            </div>
                            <div class="help-item">
                                <strong>일일 이익 한도(원) (<code>daily_profit_limit</code>)</strong>
                                실현+미실현 합산(전량 청산 가정)이 이 값 이상이면 그날 1회 전량 매도 신호가 나옵니다. 0이면 사용하지 않습니다. 일일 손실 한도와 대칭으로 두면(예: 5만/5만) 운영이 단순해집니다.
                            </div>
                            <div class="help-item">
                                <strong>일일 손실 한도 기준 (<code>daily_loss_limit_basis</code>)</strong>
                                <code>realized</code>면 “실제 체결된 손익”만 보고, <code>total</code>이면 “실현+미실현 합산”으로 한도를 적용합니다. total이 더 보수적입니다.
                            </div>
                            <div class="help-item">
                                <strong>일일 손실 한도(원) 레거시 (<code>daily_total_loss_limit</code>)</strong>
                                과거 호환용 필드입니다. 새로 설정할 때는 <code>daily_loss_limit</code>와 <code>daily_loss_limit_basis=total</code> 조합 사용을 권장합니다.
                            </div>
                            <div class="help-item">
                                <strong>월간/누적 손실 한도 (<code>monthly_loss_limit</code> / <code>cumulative_loss_limit</code>)</strong>
                                월간 손실 한도는 해당 달 실현 손익이 한도 이하로 떨어지면 신규 매수 차단, 누적 손실 한도는 설정 시점 이후 누적 실현 손익 기준입니다. 0이면 미적용입니다. 도달 시 알림이 나갑니다.
                            </div>
                            <div class="help-item">
                                <strong>변동성 기반 포지션 사이징 (<code>enable_volatility_sizing</code>)</strong>
                                켜면 “종목당 최대 손실액”과 “틱 변동성(또는 손절 비율)”을 이용해 매수 수량을 자동 계산합니다. 변동성이 큰 종목은 수량이 줄어들어 리스크를 맞춥니다. <code>max_loss_per_stock_krw</code>를 넣어야 동작합니다.
                            </div>
                            <div class="help-item">
                                <strong>진입 변동성 상한·ATR·SAP 필터</strong>
                                <code>max_intraday_vol_pct</code>: 최근 틱의 가격 변동폭(가격 대비 비율)이 이 %를 넘으면 매수 스킵. <code>atr_filter_enabled</code>·<code>atr_ratio_max_pct</code>: 분봉 ATR/현재가가 상한을 넘으면 스킵. <code>sap_deviation_filter_enabled</code>·<code>sap_deviation_max_pct</code>: 당일 세션 평균가(SAP) 대비 이탈률이 너무 크면(과열/과매도 구간) 스킵합니다. 단타 프리셋에서는 ATR·SAP를 켜 두는 것을 권장합니다.
                            </div>
                            <div class="help-item">
                                <strong>슬리피지·체결지연 보정(bps) (<code>slippage_bps</code>)</strong>
                                손절/익절 판단 시 “매수가가 불리하게 체결됐다”고 가정하는 bps입니다. 10=0.1%, 50=0.5%. 체결 지연이나 슬리피지가 있을 때 보수적으로 쓰면 좋습니다.
                            </div>
                            <div class="help-item">
                                <strong>변동성 하한 (<code>volatility_floor_ratio</code>)</strong>
                                장 초반처럼 틱이 적을 때 변동성 기반 사이징이 너무 적은 수량이 나오지 않도록, 변동성에 대한 최소값(가격 대비 비율)을 둡니다. 예: 0.005 = 0.5%.
                            </div>
                            <div class="help-item">
                                <strong>부분 익절 트리거/비율</strong>
                                지정한 수익률에 도달하면 보유 수량의 일부만 매도합니다. 비율은 0~100%로 설정합니다. 1주만 보유 중이면 부분 익절도 전량 매도처럼 처리됩니다.
                            </div>
                            <div class="help-item">
                                <strong>트레일링 스탑/활성화</strong>
                                “활성화 수익률” 이상 오른 뒤, 고점 대비 “트레일링 스탑 %”만큼 내려오면 매도합니다. 추세가 길게 나갈 때 수익을 더 끌어당기면서도 급반전 시 보호할 수 있습니다.
                            </div>
                        </div>
                    </details>

                    <details>
                        <summary>전략 설정</summary>
                        <div class="help-grid">
                            <div class="help-item">
                                <strong>단기/장기 이동평균 (틱) (<code>short_ma_period</code>/<code>long_ma_period</code>)</strong>
                                단기가 짧을수록 민감(신호 잦음), 장기가 길수록 느림(신호 적음)입니다. 일반적으로 <code>short &lt; long</code>이어야 합니다.
                            </div>
                            <div class="help-item">
                                <strong>신규 매수 허용 시간 (KST) (<code>buy_window_start_hhmm</code>~<code>buy_window_end_hhmm</code>)</strong>
                                이 구간에만 신규 매수가 허용됩니다. 매도·청산은 항상 가능합니다. 오전 단타는 09:05~11:30, 전일은 09:05~15:20처럼 끝 시각만 바꿔 쓰면 됩니다.
                            </div>
                            <div class="help-item">
                                <strong>장 초반 N분 매수 스킵 / 마감 N분 전 스킵 (<code>skip_buy_first_minutes</code> / <code>last_minutes_no_buy</code>)</strong>
                                <code>skip_buy_first_minutes</code>: 09:00(KST) 기준으로 이 값(분) 동안은 신규 매수를 하지 않습니다. 장 초반 노이즈를 피할 때 씁니다(예: 5분). <code>last_minutes_no_buy</code>: 매수 창 종료 시각 기준 “끝 N분”에는 신규 매수를 막습니다. 마감 직전 진입을 줄일 때 씁니다(예: 10~15분).
                            </div>
                            <div class="help-item">
                                <strong>단기MA 기울기 최소(%/틱) (<code>min_short_ma_slope_ratio</code>)</strong>
                                단기 이평선이 올라가는 강도가 이 값 이상일 때만 매수합니다. 0이면 검사하지 않고, 값을 키우면 “추세가 더 선명한” 구간만 진입합니다.
                            </div>
                            <div class="help-item">
                                <strong>모멘텀 필터(N틱/%) (<code>momentum_lookback_ticks</code>/<code>min_momentum_ratio</code>)</strong>
                                최근 N틱 전 가격 대비 현재가 상승률이 최소 % 이상일 때만 매수합니다. 0이면 사용하지 않습니다. 단타에서는 8틱·0.2% 정도를 많이 씁니다.
                            </div>
                            <div class="help-item">
                                <strong>진입 보강(2단) (<code>entry_confirm_enabled</code>)</strong>
                                MA/모멘텀 같은 “추세 조건”을 만족하더라도, 돌파/급증 같은 추가 조건을 통과해야만 매수합니다. (과매수/노이즈 구간 진입 감소)
                            </div>
                            <div class="help-item">
                                <strong>돌파/급증 보강 조건</strong>
                                - <code>confirm_breakout_enabled</code>: 최근 N틱 신고가 돌파<br>
                                - <code>confirm_volume_surge_enabled</code>: 틱 체결량 급증<br>
                                - <code>confirm_trade_value_surge_enabled</code>: 틱 거래대금(체결량×가격) 급증<br>
                                위 중 최소 <code>entry_confirm_min_count</code>개 이상 만족해야 매수합니다.
                            </div>
                            <div class="help-item">
                                <strong>변동성 정규화(보조) (<code>slope_vs_vol_mult</code>/<code>range_vs_vol_mult</code>)</strong>
                                평균 변동폭 대비 slope/range 임계값을 보정합니다. 변동성 큰 종목/작은 종목에서 기준이 한쪽으로 치우치는 것을 완화합니다. (0이면 사용 안 함)
                            </div>
                            <div class="help-item">
                                <strong>오전장 레짐 분기 (<code>enable_morning_regime_split</code>)</strong>
                                09:00~초반 종료 시각(<code>morning_regime_early_end_hhmm</code>)과 그 이후를 다른 임계값으로 운영합니다. 초반에는 더 엄격하게(노이즈 방지) 설정하는 것을 권장합니다.
                            </div>
                            <div class="help-item">
                                <strong>진입 직전 추가 필터</strong>
                                - <code>avoid_chase_near_high_enabled</code>: 최근 N분 고점에 너무 근접(고점 대비 하락폭이 너무 작음)하면 “피크 추격”으로 보고 매수 스킵<br>
                                - <code>minute_trend_enabled</code>: 최근 1~2분봉이 양봉 유지 등 “초단기 추세 유지” 조건을 만족할 때만 매수
                            </div>
                            <div class="help-item">
                                <strong>고점근접/분봉 고도화</strong>
                                - <code>avoid_near_high_dynamic</code>: 변동성(평균 변동폭) 기반으로 고점근접 회피 임계값을 자동 상향<br>
                                - <code>minute_trend_mode</code>: 분봉 추세를 “양봉 유지” 외에 “종가/저가/고가+저가 상승 유지”로도 선택 가능<br>
                                - <code>minute_trend_early_only</code>: 분봉 추세 필터를 장 초반 레짐에만 적용
                            </div>
                            <div class="help-item">
                                <strong>시장 레짐: 지수 MA·상승 비율·하락장 강화 (<code>index_ma_filter</code> / <code>advance_ratio_*</code> / <code>advance_ratio_down_market_skip</code>)</strong>
                                지수 MA: 선택한 지수(코스피/코스닥)가 N일 이평선 아래면 매수 스킵. 상승 비율: 시장에서 상승 종목 비율이 N% 미만이면 스킵. <code>advance_ratio_down_market_skip</code>을 켜면 상승 비율이 50% 미만(하락장)일 때 전량 매수 스킵으로 더 강하게 막습니다.
                            </div>
                            <div class="help-item">
                                <strong>서킷브레이커·사이드카·VI (<code>circuit_breaker_*</code> / <code>sidecar_*</code> / <code>vi_*</code>)</strong>
                                서킷: 지수 전일 대비 하락률이 임계값(예: -7%) 이하이면 신규 매수 스킵(또는 설정에 따라 전량/일부 청산). 사이드카: 지수 급등락(코스피 ±5%, 코스닥 ±6%) 시 N분간 매수 스킵. VI: 해당 종목에 변동성완화장치가 걸리면 그 종목만 N분간 매수 스킵. 단타에서는 세 옵션 모두 켜 두는 것을 권장합니다.
                            </div>
                            <div class="help-item">
                                <strong>진입 시 거래량·거래대금 하한 (<code>min_volume_ratio_for_entry</code> / <code>min_trade_amount_ratio_for_entry</code>)</strong>
                                현재 틱의 거래량(또는 거래대금)이 “최근 평균” 대비 이 배수 미만이면 매수 스킵합니다. 0이면 사용 안 함. 유동성이 부족한 구간 진입을 줄일 때 씁니다(예: 0.5 = 평균의 절반 이상일 때만 매수).
                            </div>
                            <div class="help-item">
                                <strong>지수 대비 상대 강도 (<code>relative_strength_filter_enabled</code>)</strong>
                                켜면 “종목 당일 변동률 &gt; 지수 당일 변동률 + margin%”일 때만 매수합니다. 지수보다 강한 종목만 고르는 필터입니다. margin을 0으로 두면 “종목이 지수보다만 올라가면” 허용합니다.
                            </div>
                            <div class="help-item">
                                <strong>거래대금 집중·연속 손실 쿨다운</strong>
                                거래대금 집중: 상위 N종목 거래대금 비율이 X%를 넘으면 “좁은 시장”으로 보고 매수 스킵. 연속 손실 쿨다운: 직전 N회 모두 손실이면 재진입 쿨다운 시간을 배수만큼 늘려, 그동안 같은 종목 재매수를 막습니다.
                            </div>
                            <div class="help-item">
                                <strong>재진입 쿨다운(초) (<code>reentry_cooldown_seconds</code>)</strong>
                                한 종목을 매도한 뒤 이 시간(초) 동안은 같은 종목 매수를 하지 않습니다. 횡보장에서 같은 종목을 반복 매매하는 것을 줄일 때 씁니다. 180초(3분) 정도를 많이 씁니다.
                            </div>
                            <div class="help-item">
                                <strong>진입 확인(연속 틱 수) (<code>buy_confirm_ticks</code>)</strong>
                                매수 조건(MA 크로스·추세·보강 조건 등)이 연속으로 이 틱 수만큼 유지될 때만 실제 매수 주문을 냅니다. 1이면 조건 만족 즉시, 2 이상이면 더 확실한 추세일 때만 진입합니다.
                            </div>
                            <div class="help-item">
                                <strong>최대 스프레드(%) (<code>max_spread_ratio</code>)</strong>
                                매수 호가와 매도 호가 차이(스프레드)가 현재가 대비 이 비율을 넘으면 매수 스킵합니다. 스프레드가 크면 체결 시 불리해지므로, 단타에서는 0.2% 정도로 두는 경우가 많습니다. 너무 작게 잡으면 매수 기회가 줄어듭니다.
                            </div>
                            <div class="help-item">
                                <strong>횡보장 제외(N틱/레인지%) (<code>range_lookback_ticks</code>/<code>min_range_ratio</code>)</strong>
                                최근 N틱 동안의 고가−저가 폭(레인지)이 현재가 대비 이 비율보다 작으면 “움직임이 없는 구간”으로 보고 매수 스킵합니다. 레인지 %를 키우면 더 움직인 구간만 진입합니다.
                            </div>
                            <div class="help-item">
                                <strong>시간기반 청산 (<code>enable_time_liquidation</code> / <code>liquidate_after_hhmm</code>)</strong>
                                켜면 지정 시각(<code>liquidate_after_hhmm</code>)이 지난 뒤, 보유 포지션에 대해 전량 매도 신호를 한 번 생성합니다. 오전 단타는 11:55, 전일 단타는 15:25처럼 “매수 창 종료 직후”로 두면 정리하기 좋습니다.
                            </div>
                        </div>
                    </details>

                    <details>
                        <summary>종목 선정 기준</summary>
                        <div class="help-grid">
                            <div class="help-item">
                                <strong>최소/최대 상승률(%) (<code>min_price_change_ratio</code>/<code>max_price_change_ratio</code>)</strong>
                                KIS 등락률 랭킹에서 이 범위에 들어오는 종목만 후보로 가져옵니다. 예: 1~8%면 “오늘 1%~8% 오른 종목”만 후보가 됩니다. 범위를 너무 좁히면 후보가 0건이 될 수 있습니다.
                            </div>
                            <div class="help-item">
                                <strong>가격/거래량/거래대금 조건</strong>
                                최소 가격(원), 최소 거래량(주), 최소 거래대금(원)으로 후보를 한 번 더 걸러냅니다. 조건을 너무 빡세게 두면 “API는 성공했는데 결과 0건”이 자주 나옵니다. 거래대금 하한을 크게 잡으면 후보가 크게 줄어듭니다.
                            </div>
                            <div class="help-item">
                                <strong>선정 정렬 기준 (<code>sort_by</code>)</strong>
                                후보가 여러 개일 때 어떤 순서로 우선 선택할지 정합니다. 등락률(기본)이면 랭킹 순 그대로, 전일 거래대금이면 “어제 많이 거래된 종목”을 앞에 두어 유동성·관심도를 반영합니다. 전일 거래대금은 API 호출이 추가돼 선정이 조금 느려질 수 있습니다.
                            </div>
                            <div class="help-item">
                                <strong>전일 거래대금 후보 pool 크기 (<code>prev_day_rank_pool_size</code>)</strong>
                                정렬을 “전일 거래대금”으로 쓸 때, 상위 몇 개 후보까지 전일 거래대금을 조회할지 제한합니다. 크게 두면 정확하지만 조회 시간이 길어지고, 작게 두면 빠르지만 상위 몇 개만 정렬됩니다.
                            </div>
                            <div class="help-item">
                                <strong>장초 워밍업(분) (<code>warmup_minutes</code>)</strong>
                                장 시작 후 이 시간(분)이 지날 때까지는 종목 선정·재선정을 하지 않습니다. 장 초반 급등락·체결 왜곡이 진정된 뒤에 선정해, 노이즈에 휘둘리지 않게 합니다.
                            </div>
                            <div class="help-item">
                                <strong>장초 강화 필터 (<code>early_strict</code>)</strong>
                                켜면 장 시작 후 일정 시간 동안 “최소 거래량·거래대금”을 기본값보다 더 높게 적용합니다. 초반 몇 건 체결만으로 랭킹에 올라온 종목을 걸러내는 용도입니다.
                            </div>
                            <div class="help-item">
                                <strong>고점 대비 하락추세 제외 (<code>exclude_drawdown</code> / <code>max_drawdown_from_high_ratio</code>)</strong>
                                켜면 “당일 고점 대비 N% 이상 내려온 종목”을 후보에서 제외합니다. 오후에 선정할 때 “아침에 고점 찍고 밀린 종목”을 빼는 데 씁니다. 고가는 선정 시점까지의 당일 장중 고가이므로, 9:30 선정이면 드로우다운이 작고 13:00 선정이면 같은 N%여도 더 많이 제외됩니다. 실전에서는 10~12% 이상으로 두어야 한두 종목이라도 선정되는 경우가 많습니다.
                            </div>
                        </div>
                    </details>

                    <details>
                        <summary>운영 옵션</summary>
                        <div class="help-grid">
                            <div class="help-item">
                                <strong>자동 리밸런싱(재선정 주기)</strong>
                                주기적으로 종목 선정을 다시 수행해, “지금 시점에 맞는” 후보 목록으로 갱신합니다. 주기를 짧게 두면 시장 변화에 빠르게 맞추지만 API·부하가 늘고, 길게 두면 안정적이지만 반응이 느립니다.
                            </div>
                            <div class="help-item">
                                <strong>WebSocket 재연결 대기</strong>
                                실시간 시세 연결이 끊겼을 때 재연결을 시도하기 전에 잠시 대기하는 시간입니다. 너무 짧으면 서버 부하가 커지고, 너무 길면 그동안 틱을 못 받을 수 있습니다.
                            </div>
                            <div class="help-item">
                                <strong>긴급 청산(연결 단절 N분)</strong>
                                실시간 시세(또는 엔진)가 N분 이상 끊긴 상태가 되면, 보유 포지션을 전량 시장가 매도하고 매매를 중단하는 옵션입니다. 네트워크·장애 시 리스크를 제한할 때 씁니다.
                            </div>
                            <div class="help-item">
                                <strong>선정 결과 0건 시 이전 목록 유지</strong>
                                종목 선정을 돌렸는데 후보가 한 건도 없을 때, “이전에 선정된 목록”을 그대로 쓸지 여부입니다. 켜 두면 선정 실패일 때도 직전 종목 목록으로 계속 매매 후보를 유지할 수 있습니다.
                            </div>
                        </div>
                    </details>
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
                <div class="trade-submenu" style="margin-bottom: 12px;">
                    <button type="button" class="env-btn active" id="btn-trades-system" onclick="showTradeSubtab('system')">매매 시스템 거래내역</button>
                    <button type="button" class="env-btn" id="btn-trades-account" onclick="showTradeSubtab('account')">계좌 거래내역</button>
                </div>
                <!-- 매매 시스템 거래내역 -->
                <div id="trade-panel-system" class="trade-panel">
                    <p class="hint">DB(quant_trading_user_hist) 또는 세션 메모리. 조회일 지정 후 조회.</p>
                    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-bottom:12px;">
                        <div class="form-group" style="margin:0; min-width:auto;">
                            <label style="font-size:12px;">조회일</label>
                            <input type="date" id="trades_system_date" style="width:16ch; padding:6px 8px; font-size:13px;">
                        </div>
                        <button type="button" class="btn btn-inline" onclick="fetchSystemTrades()" style="height:2rem; padding:0 10px; line-height:2rem;">조회</button>
                    </div>
                    <div id="trade_history" style="max-height: 400px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>시간</th>
                                    <th>
                                        종목<br>
                                        <select id="system_trade_filter_stock" style="width:100%; font-size:12px; padding:4px 6px;">
                                            <option value="">전체</option>
                                        </select>
                                    </th>
                                    <th>
                                        상태<br>
                                        <select id="system_trade_filter_status" style="width:100%; font-size:12px; padding:4px 6px;">
                                            <option value="">전체</option>
                                            <option value="filled">체결</option>
                                            <option value="accepted_pending">접수(대기)</option>
                                        </select>
                                    </th>
                                    <th>
                                        유형<br>
                                        <select id="system_trade_filter_side" style="width:100%; font-size:12px; padding:4px 6px;">
                                            <option value="">전체</option>
                                            <option value="buy">매수</option>
                                            <option value="sell">매도</option>
                                        </select>
                                    </th>
                                    <th>수량</th>
                                    <th>가격</th>
                                    <th>손익</th>
                                    <th>사유</th>
                                </tr>
                            </thead>
                            <tbody id="trade_history_body">
                            </tbody>
                        </table>
                    </div>
                </div>
                <!-- 계좌 거래내역 -->
                <div id="trade-panel-account" class="trade-panel" style="display:none;">
                    <p class="hint">한국투자증권 계좌 주문·체결 내역(일별주문체결조회).</p>
                    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-bottom:12px;">
                        <div class="form-group" style="margin:0; min-width:auto;">
                            <label style="font-size:12px;">조회일</label>
                            <input type="date" id="trades_account_date" style="width:16ch; padding:6px 8px; font-size:13px;">
                        </div>
                        <button type="button" class="btn btn-inline" onclick="fetchAccountTrades()" style="height:2rem; padding:0 10px; line-height:2rem;">조회</button>
                    </div>
                    <div id="account_trade_history" style="max-height: 400px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>일자</th>
                                    <th>시간</th>
                                    <th>
                                        구분<br>
                                        <select id="account_trade_filter_side" style="width:100%; font-size:12px; padding:4px 6px;">
                                            <option value="">전체</option>
                                        </select>
                                    </th>
                                    <th>
                                        종목<br>
                                        <select id="account_trade_filter_pdno" style="width:100%; font-size:12px; padding:4px 6px;">
                                            <option value="">전체</option>
                                        </select>
                                    </th>
                                    <th>종목명</th>
                                    <th>주문수량</th>
                                    <th>체결수량</th>
                                    <th>체결가</th>
                                </tr>
                            </thead>
                            <tbody id="account_trade_history_body">
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- AI 리포트 탭 -->
        <div id="tab-ai-report" class="tab-content">
            <div class="card">
                <h2>AI 일일 리포트</h2>
                <p class="hint">
                    Domestic_stock 시스템 로그(<code>system_YYYYMMDD.log</code>), 거래내역(<code>quant_trading_user_hist</code>),
                    설정(<code>quant_trading_user_settings</code>)을 기반으로 AI가 하루 성과·리스크·개선 제안을 요약합니다.
                    서버 환경에 OpenAI SDK와 <code>OPENAI_API_KEY</code>가 설정되어 있어야 동작합니다.
                </p>
                <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-bottom:12px;">
                    <div class="form-group" style="margin:0; min-width:auto;">
                        <label style="font-size:12px;">대상 일자</label>
                        <input type="date" id="ai_report_date" style="width:16ch; padding:6px 8px; font-size:13px;">
                    </div>
                    <button type="button" class="btn btn-inline" onclick="loadAiDailyReport()" style="height:2rem; padding:0 10px; line-height:2rem;">
                        리포트 생성/새로고침
                    </button>
                </div>
                <div id="ai_report_status" class="hint" style="margin-bottom:8px;"></div>
                <div id="ai_report_container" style="display:none; max-height:480px; overflow-y:auto;">
                    <h3 style="font-size:15px; margin-top:0;">요약</h3>
                    <div id="ai_report_summary" class="hint" style="white-space:pre-wrap;"></div>
                    <h3 style="font-size:15px; margin-top:16px;">핵심 지표 해석</h3>
                    <ul id="ai_report_metrics" class="hint" style="padding-left:18px;"></ul>
                    <h3 style="font-size:15px; margin-top:16px;">문제점 / 리스크 포인트</h3>
                    <ul id="ai_report_issues" class="hint" style="padding-left:18px;"></ul>
                    <h3 style="font-size:15px; margin-top:16px;">파라미터 제안</h3>
                    <ul id="ai_report_param_suggestions" class="hint" style="padding-left:18px;"></ul>
                    <h3 style="font-size:15px; margin-top:16px;">내일을 위한 액션 아이템</h3>
                    <ul id="ai_report_actions" class="hint" style="padding-left:18px;"></ul>
                </div>
            </div>
        </div>

        <!-- Docs 탭 -->
        <div id="tab-docs" class="tab-content">
            <div id="doc-section-overview" class="doc-section active">
                <div class="card">
                    <h2>개요</h2>
                    <p>국내 주식 실시간 틱 기반 자동매매 시스템. KIS(한국투자증권) API·WebSocket 연동, 리스크 관리·종목 선정·승인/자동 체결을 웹 대시보드에서 운영.</p>
                </div>
                <div class="card">
                    <h2>아키텍처</h2>
                    <pre class="doc-pre">클라이언트(브라우저)
  → HTTPS/WSS
FastAPI (quant_dashboard.py) + REST (quant_dashboard_api.py)
  → JWT, 설정 CRUD, 종목선정, 시스템 제어, WebSocket 브로드캐스트
매매 엔진 (quant_trading_safe.py, 백그라운드 스레드)
  → create_safe_on_result() 콜백으로 틱 수신
  → QuantStrategy.get_signal(), RiskManager.check_exit_signal(), safe_execute_order()
  → reconcile: 체결 반영
KIS REST (domestic_stock_functions) / KIS WebSocket (domestic_stock_functions_ws) / DynamoDB
  → kis_auth: 토큰·계정·env_dv(실전/모의)</pre>
                    <table class="doc-table">
                        <tr><th>레이어</th><th>파일/역할</th></tr>
                        <tr><td>UI</td><td>dashboard_html.py — 설정·승인대기·거래내역·WebSocket 수신</td></tr>
                        <tr><td>API</td><td>quant_dashboard_api.py — 인증·설정·종목·시스템·성과</td></tr>
                        <tr><td>엔진</td><td>quant_trading_safe.py — 틱→신호→리스크→주문→체결</td></tr>
                        <tr><td>전략</td><td>QuantStrategy — MA 골든/데드 크로스, 필터</td></tr>
                        <tr><td>리스크</td><td>RiskManager — 한도·손절/익절·ATR·pending·reconcile</td></tr>
                        <tr><td>종목선정</td><td>stock_selector.py — 등락률 API, 필터·정렬</td></tr>
                    </table>
                </div>
            </div>
            <div id="doc-section-workflow" class="doc-section">
                <div class="card">
                    <h2>워크플로우 (파일·함수 흐름)</h2>
                    <h3>1. 로그인 → 대시보드</h3>
                    <pre class="doc-pre">auth_manager.login()  ← auth_manager.py
  → JWT 발급
quant_dashboard.get_dashboard_html(username)  ← quant_dashboard.py
  → HTML 렌더 (dashboard_html.get_dashboard_html 호출)
클라이언트: WebSocket 연결 /api/ws → state.broadcast() 수신  ← quant_dashboard.py (TradingState)</pre>
                    <h3>2. 설정 로드/저장</h3>
                    <pre class="doc-pre">API: GET /api/settings/risk 등  ← quant_dashboard_api.py
  → user_settings_store.load_risk_config(username)  ← user_settings_store.py
API: POST /api/settings/risk 등  ← quant_dashboard_api.py
  → user_settings_store.save_risk_config(username, config)  ← user_settings_store.py
  → audit_log(username, "config_save", ...)  ← audit_log.py</pre>
                    <h3>3. 종목 선정</h3>
                    <pre class="doc-pre">API: POST /api/stocks/select  ← quant_dashboard_api.py
  → StockSelector(설정) 생성  ← stock_selector.py
  → selector.select_stocks_by_fluctuation()  ← stock_selector.py
  → domestic_stock_functions.fluctuation()  ← domestic_stock_functions.py
  → state.selected_stocks 갱신
  → audit_log("stock_selection", ...)  ← audit_log.py</pre>
                    <h3>4. 시스템 시작 (매매 엔진)</h3>
                    <pre class="doc-pre">API: POST /api/system/start  ← quant_dashboard_api.py
  → initialize_trading_system()  ← quant_dashboard_api.py
  → create_safe_on_result(strategy, trenv, ...)  ← quant_trading_safe.py
  → 엔진 스레드: domestic_stock_functions_ws 구독 (호가·체결)  ← domestic_stock_functions_ws.py
  → 틱 수신 시 콜백 on_result() 실행  ← quant_trading_safe.py (create_safe_on_result 내부)</pre>
                    <h3>5. 틱 → 신호 → 주문 (엔진 내부)</h3>
                    <pre class="doc-pre">on_result(ws, tr_id, result, data_info)  ← quant_trading_safe.py
  → 선정 종목 필터 (state.selected_stocks)
  → strategy.get_signal(stock_code, current_price)  ← quant_trading_safe.py (QuantStrategy)
       → update_price(), calculate_ma() → 골든/데드 크로스 → "buy"|"sell"|None
  → risk_mgr.check_exit_signal(stock_code, current_price)  ← quant_trading_safe.py (RiskManager)
       → 손절/익절/트레일링/부분익절 판단
  → risk_mgr.can_trade(stock_code, price, quantity)  ← quant_trading_safe.py (RiskManager)
  → safe_execute_order(signal, stock_code, price, strategy, trenv, ...)  ← quant_trading_safe.py
       → order_cash()  ← domestic_stock_functions.py
       → set_pending_order(), update_position()  ← quant_trading_safe.py (RiskManager)
  → reconcile 루프: _check_filled_order(), clear_pending_order()  ← quant_trading_safe.py</pre>
                    <h3>6. 승인 대기 (수동 모드)</h3>
                    <pre class="doc-pre">엔진: manual_approval이 True면 safe_execute_order 내부 input() 대기  ← quant_trading_safe.py
대시보드: 신호 발생 시 pending_signals 적재 → API GET /api/signals/pending  ← quant_dashboard_api.py
  → 사용자 승인: POST /api/signals/approve  ← quant_dashboard_api.py
  → safe_execute_order(..., manual_approval=False)  ← quant_trading_safe.py
  → audit_log("signal_approve"|"signal_reject", ...)  ← audit_log.py</pre>
                </div>
            </div>
            <div id="doc-section-files" class="doc-section">
                <div class="card">
                    <h2>파일별 설명</h2>
                    <table class="doc-table">
                        <tr><th>파일</th><th>역할</th></tr>
                        <tr><td>quant_dashboard.py</td><td>FastAPI 앱, TradingState, 로그인/JWT, WebSocket, create_safe_on_result 등록</td></tr>
                        <tr><td>quant_dashboard_api.py</td><td>REST: 설정 CRUD, 종목선정, 시스템 시작/중지, 승인/거절, 성과 export, 지수/서킷/VI 캐시</td></tr>
                        <tr><td>dashboard_html.py</td><td>단일 HTML/CSS/JS 대시보드, 설정 폼·프리셋·도움말·Docs</td></tr>
                        <tr><td>quant_trading_safe.py</td><td>RiskManager, QuantStrategy, safe_execute_order, create_safe_on_result, reconcile</td></tr>
                        <tr><td>stock_selector.py</td><td>StockSelector, select_stocks_by_fluctuation(), 등락률 API·필터·정렬</td></tr>
                        <tr><td>stock_selection_presets.py</td><td>종목선정 프리셋, get_preset(), list_presets()</td></tr>
                        <tr><td>user_settings_store.py</td><td>DynamoDBUserSettingsStore, 사용자별 설정 저장/로드</td></tr>
                        <tr><td>user_result_store.py</td><td>일별 성과 DynamoDB 저장·조회·내보내기</td></tr>
                        <tr><td>audit_log.py</td><td>audit_log(username, action, details), 설정/수동주문/승인 기록</td></tr>
                        <tr><td>notifier.py</td><td>send_alert(level, message, title), log_only | telegram</td></tr>
                        <tr><td>auth_manager.py</td><td>로그인·회원가입·JWT·get_current_user</td></tr>
                        <tr><td>kis_auth.py</td><td>KIS 토큰·config_root·token_root·env_dv</td></tr>
                        <tr><td>domestic_stock_functions.py</td><td>order_cash, 잔고·체결·지수·등락률(fluctuation) REST</td></tr>
                        <tr><td>domestic_stock_functions_ws.py</td><td>asking_price_krx, ccnl_krx 등 WebSocket 호가·체결</td></tr>
                    </table>
                </div>
            </div>
            <div id="doc-section-functions" class="doc-section">
                <div class="card">
                    <h2>기능별 주요 함수</h2>
                    <h3>RiskManager (quant_trading_safe.py)</h3>
                    <ul class="doc-list">
                        <li><code>can_trade(stock_code, price, quantity)</code> → (bool, reason): 일일 한도·거래 횟수·동시 보유·pending·시간대 검사</li>
                        <li><code>check_exit_signal(stock_code, current_price)</code> → "sell"|None: 손절/익절/ATR/트레일링/부분익절</li>
                        <li><code>calculate_quantity(price)</code>, <code>calculate_quantity_with_volatility(...)</code>: 매수 수량</li>
                        <li><code>update_position(stock_code, price, quantity, action)</code>: positions 갱신 (Lock)</li>
                        <li><code>has_pending_order</code>, <code>set_pending_order</code>, <code>clear_pending_order</code>: 접수 후 체결 대기</li>
                        <li><code>get_unrealized_pnl()</code>, <code>get_total_pnl()</code>: 손익 집계</li>
                    </ul>
                    <h3>QuantStrategy (quant_trading_safe.py)</h3>
                    <ul class="doc-list">
                        <li><code>update_price(stock_code, price)</code>: price_history·last_prices 반영</li>
                        <li><code>calculate_ma(stock_code, period)</code>: 최근 period틱 종가 평균</li>
                        <li><code>get_signal(stock_code, current_price)</code> → "buy"|"sell"|None: MA 골든/데드 크로스</li>
                    </ul>
                    <h3>주문 실행 (quant_trading_safe.py)</h3>
                    <ul class="doc-list">
                        <li><code>safe_execute_order(signal, stock_code, price, strategy, trenv, ...)</code>: can_trade → 수량 계산 → order_cash·재시도·폴백</li>
                        <li><code>_extract_order_response(df)</code>: ODNO·RT_CD 등 추출</li>
                        <li><code>_check_filled_order</code>, <code>_check_unfilled_order_acceptance</code>: 체결/미체결 조회</li>
                        <li><code>create_safe_on_result(strategy, trenv, ...)</code>: WebSocket 틱 콜백 등록, 신호→주문→reconcile</li>
                    </ul>
                    <h3>종목 선정 (stock_selector.py)</h3>
                    <ul class="doc-list">
                        <li><code>select_stocks_by_fluctuation()</code> → List[str]: 등락률 API 후 필터·정렬·워밍업·고점 대비 제외</li>
                    </ul>
                    <h3>API (quant_dashboard_api.py)</h3>
                    <ul class="doc-list">
                        <li>설정: load_risk_config, save_risk_config 등 → user_settings_store</li>
                        <li>종목: POST /api/stocks/select → StockSelector().select_stocks_by_fluctuation()</li>
                        <li>시스템: start/stop, set-env, set-trade-mode</li>
                        <li>승인: GET /api/signals/pending, POST /api/signals/approve|reject</li>
                        <li>성과: GET /api/performance/export (CSV/JSON, 슬리피지·수수료 옵션)</li>
                    </ul>
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

    <!-- 선정 기준 모달 -->
    <div id="criteriaModalOverlay" class="modal-overlay" style="display:none;" onclick="closeCriteriaModal(event)">
        <div class="modal" onclick="event.stopPropagation()" style="max-width: 420px;">
            <div class="modal-header" style="display:flex; justify-content:space-between; align-items:center;">
                <span>선정 기준</span>
                <button type="button" class="btn" style="padding: 3px 10px; font-size: 11px; margin-left: auto; min-width: auto;" onclick="closeCriteriaModal()">닫기</button>
            </div>
            <div class="modal-body" id="criteria_modal_body" style="font-size: 13px; line-height: 1.6;">
                <p style="color: var(--muted);">기준을 불러오는 중...</p>
            </div>
        </div>
    </div>

    <!-- 프로필 모달 (quant_trading_users 조회/수정) -->
    <div id="profileModalOverlay" class="modal-overlay" style="display:none;" onclick="closeProfileModal(event)">
        <div class="modal" onclick="event.stopPropagation()" style="max-width: 520px;">
            <div class="modal-body" id="profile_modal_body">
                <div class="profile-form">
                    <div class="profile-section">
                        <div class="profile-section-title">계정</div>
                        <label>이메일</label>
                        <input type="text" id="profile_email" placeholder="email@example.com" style="width:100%; margin-bottom:10px;">
                    </div>
                    <div class="profile-section">
                        <div class="profile-section-title">실전 계좌</div>
                        <label>캐노(실전) <span class="label-hint">— 계좌 앞 8자리, 한국투자증권 등</span></label>
                        <input type="text" id="profile_real_cano" placeholder="8자리" style="width:100%; margin-bottom:8px;">
                        <label>계좌번호(실전)</label>
                        <input type="text" id="profile_real_acnt_no" placeholder="계좌번호" style="width:100%; margin-bottom:10px;">
                    </div>
                    <div class="profile-section">
                        <div class="profile-section-title">모의 계좌</div>
                        <label>캐노(모의) <span class="label-hint">— 계좌 앞 8자리</span></label>
                        <input type="text" id="profile_paper_cano" placeholder="8자리" style="width:100%; margin-bottom:8px;">
                        <label>계좌번호(모의)</label>
                        <input type="text" id="profile_paper_acnt_no" placeholder="계좌번호" style="width:100%; margin-bottom:10px;">
                    </div>
                    <div class="profile-section">
                        <div class="profile-section-title">비밀번호 변경</div>
                        <label>현재 비밀번호</label>
                        <input type="password" id="profile_current_password" placeholder="현재 비밀번호" style="width:100%; margin-bottom:8px;">
                        <label>새 비밀번호</label>
                        <input type="password" id="profile_new_password" placeholder="4자 이상" style="width:100%; margin-bottom:8px;">
                        <label>새 비밀번호 확인</label>
                        <input type="password" id="profile_new_password_confirm" placeholder="다시 입력" style="width:100%; margin-bottom:10px;">
                        <button type="button" class="btn" style="margin-top:4px;" onclick="changePassword()">비밀번호 변경</button>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn" onclick="closeProfileModal()">취소</button>
                <button type="button" class="btn btn-primary" onclick="saveProfile()">저장</button>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let reconnectInterval = null;
        let pendingSignals = {{}};
        let autoRefreshTimer = null;
        let performanceDailyRows = [];
        let performanceDailyCurrentPage = 1;
        let performanceDailyPageSize = 30;

        function showTab(tabName) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const tabEl = document.querySelector(`.tab[data-tab="${{tabName}}"]`);
            if (tabEl) tabEl.classList.add('active');
            else if (typeof event !== 'undefined' && event && event.target) event.target.classList.add('active');
            const content = document.getElementById(`tab-${{tabName}}`);
            if (content) content.classList.add('active');
            const settingsSub = document.getElementById('settingsSubbar');
            const perfSub = document.getElementById('performanceSubbar');
            const docsSub = document.getElementById('docsSubbar');
            if (settingsSub) settingsSub.style.display = (tabName === 'settings') ? 'block' : 'none';
            if (perfSub) perfSub.style.display = (tabName === 'performance') ? 'block' : 'none';
            if (docsSub) docsSub.style.display = (tabName === 'docs') ? 'block' : 'none';
            if (tabName === 'performance') {{
                showPerformanceSection('summary');
                loadPerformanceSummary();
                setDefaultPerformanceDailyRange();
                if (!window.__performanceDailyInitialized) {{
                    window.__performanceDailyInitialized = true;
                    loadPerformanceDaily();
                }}
            }}
            if (tabName === 'docs') showDocsSection('overview');
            if (tabName === 'positions') {{
                // 포지션 탭 최초 진입 시 1회: MTS/계좌 잔고 기준으로 강제 동기화
                if (!window.__positionsTabInitialized) {{
                    window.__positionsTabInitialized = true;
                    syncPositionsFromBalance();
                }}
            }}
            if (tabName === 'trades') {{
                const today = new Date().toISOString().slice(0, 10);
                const sysDateEl = document.getElementById('trades_system_date');
                const accEl = document.getElementById('trades_account_date');
                if (sysDateEl && !sysDateEl.value) sysDateEl.value = today;
                if (accEl && !accEl.value) accEl.value = today;
                showTradeSubtab('system');
                // 첫 오픈 시 당일로 조회 자동 실행 (이후에는 사용자가 날짜·조회 버튼으로 변경)
                if (!window.__tradesTabInitialized) {{
                    window.__tradesTabInitialized = true;
                    if (sysDateEl) sysDateEl.value = today;
                    if (accEl) accEl.value = today;
                    fetchSystemTrades();
                    fetchAccountTrades();
                }}
            }}
            if (tabName === 'ai-report') {{
                const dateEl = document.getElementById('ai_report_date');
                if (dateEl && !dateEl.value) {{
                    const today = new Date().toISOString().slice(0, 10);
                    dateEl.value = today;
                }}
            }}
        }}

        async function loadAiDailyReport() {{
            const dateEl = document.getElementById('ai_report_date');
            const statusEl = document.getElementById('ai_report_status');
            const containerEl = document.getElementById('ai_report_container');
            if (!dateEl || !statusEl || !containerEl) return;
            const dateStr = (dateEl.value || '').trim().replace(/[-/]/g, '').slice(0, 8);
            if (dateStr.length !== 8) {{
                statusEl.textContent = '대상 일자를 선택해 주세요.';
                containerEl.style.display = 'none';
                return;
            }}
            statusEl.textContent = 'AI 리포트 생성 중... (수 초 소요될 수 있습니다)';
            containerEl.style.display = 'none';
            try {{
                const r = await fetch(`/api/ai/report/daily?date=${{encodeURIComponent(dateStr)}}`, {{
                    credentials: 'include',
                    headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }}
                }});
                const data = await r.json().catch(() => ({{}}));
                if (!r.ok || !data.success) {{
                    statusEl.textContent = data.message || ('리포트 생성 실패: ' + r.status);
                    containerEl.style.display = 'none';
                    return;
                }}
                const report = data.report || {{}};
                statusEl.textContent = (report.date_summary || '') || (`${{data.date}} 기준 리포트`);

                const $ = (id) => document.getElementById(id);

                const summaryEl = $('ai_report_summary');
                if (summaryEl) summaryEl.textContent = report.summary || report.overview || '';

                const metricsEl = $('ai_report_metrics');
                if (metricsEl) {{
                    metricsEl.innerHTML = '';
                    const metrics = report.key_metrics || report.metrics || [];
                    if (Array.isArray(metrics)) {{
                        metrics.forEach((m) => {{
                            const li = document.createElement('li');
                            const name = m.name || m.label || '';
                            const value = (m.value !== undefined && m.value !== null) ? m.value : '';
                            const comment = m.comment || m.note || '';
                            li.textContent = name
                                ? (name + (value !== '' ? `: ${{value}}` : '') + (comment ? ` - ${{comment}}` : ''))
                                : (comment || JSON.stringify(m));
                            metricsEl.appendChild(li);
                        }});
                    }}
                }}

                const issuesEl = $('ai_report_issues');
                if (issuesEl) {{
                    issuesEl.innerHTML = '';
                    const issues = report.issues || report.risks || [];
                    if (Array.isArray(issues)) {{
                        issues.forEach((it) => {{
                            const li = document.createElement('li');
                            const txt = it.detail || it.description || it.message || JSON.stringify(it);
                            li.textContent = txt;
                            issuesEl.appendChild(li);
                        }});
                    }}
                }}

                const paramsEl = $('ai_report_param_suggestions');
                if (paramsEl) {{
                    paramsEl.innerHTML = '';
                    const params = report.parameter_suggestions || report.param_suggestions || [];
                    if (Array.isArray(params)) {{
                        params.forEach((p) => {{
                            const li = document.createElement('li');
                            const name = p.param || p.name || '';
                            const cur = p.current;
                            const sugg = p.suggested;
                            const reason = p.reason || p.comment || '';
                            let txt = name ? name : '';
                            if (name && (cur !== undefined || sugg !== undefined)) {{
                                txt += `: ${{cur}} → ${{sugg}}`;
                            }}
                            if (reason) {{
                                txt += txt ? ` - ${{reason}}` : reason;
                            }}
                            if (!txt) txt = JSON.stringify(p);
                            li.textContent = txt;
                            paramsEl.appendChild(li);
                        }});
                    }}
                }}

                const actionsEl = $('ai_report_actions');
                if (actionsEl) {{
                    actionsEl.innerHTML = '';
                    const actions = report.action_items || report.actions || [];
                    if (Array.isArray(actions)) {{
                        actions.forEach((a) => {{
                            const li = document.createElement('li');
                            const txt = typeof a === 'string' ? a : (a.detail || a.description || JSON.stringify(a));
                            li.textContent = txt;
                            actionsEl.appendChild(li);
                        }});
                    }}
                }}

                containerEl.style.display = 'block';
            }} catch (e) {{
                statusEl.textContent = '리포트 생성 실패: ' + (e.message || e);
                containerEl.style.display = 'none';
            }}
        }}

        function setDefaultPerformanceDailyRange() {{
            const fromEl = document.getElementById('perf_date_from');
            const toEl = document.getElementById('perf_date_to');
            if (!fromEl || !toEl) return;
            const now = new Date();
            const to = now;
            const from = new Date(now.getFullYear(), now.getMonth(), 1);
            const fmt = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
            if (!fromEl.value) fromEl.value = fmt(from);
            if (!toEl.value) toEl.value = fmt(to);
        }}
        function ensurePerformanceDailyRangeAndLoad() {{
            setDefaultPerformanceDailyRange();
            const fromEl = document.getElementById('perf_date_from');
            const toEl = document.getElementById('perf_date_to');
            if (fromEl && toEl && fromEl.value && toEl.value) loadPerformanceDaily();
        }}

        async function showPerformanceStoreStatus() {{
            try {{
                const r = await fetch('/api/performance/store-status', {{ credentials: 'include', headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }} }});
                const d = await r.json().catch(() => ({{}}));
                const lines = [
                    '저장소: ' + (d.enabled ? '연동됨' : '비연동'),
                    '테이블: ' + (d.table_name || '-'),
                    '리전: ' + (d.region || '-'),
                    '조회 사용자(username): ' + (d.current_user || '-'),
                    (d.init_error ? '오류: ' + d.init_error : ''),
                    d.message || ''
                ].filter(Boolean);
                alert(lines.join('\\n'));
            }} catch (e) {{
                alert('저장소 상태 조회 실패: ' + (e.message || e));
            }}
        }}

        async function loadPerformanceDaily() {{
            const fromEl = document.getElementById('perf_date_from');
            const toEl = document.getElementById('perf_date_to');
            const statusEl = document.getElementById('performance_daily_status');
            const tableEl = document.getElementById('performance_daily_table');
            if (!fromEl || !toEl || !statusEl || !tableEl) return;
            const date_from = (fromEl.value || '').trim().replace(/[-/]/g, '').slice(0, 8);
            const date_to = (toEl.value || '').trim().replace(/[-/]/g, '').slice(0, 8);
            if (date_from.length !== 8 || date_to.length !== 8) {{
                statusEl.textContent = '시작일·종료일을 선택해 주세요.';
                tableEl.style.display = 'none';
                performanceDailyRows = [];
                const pageInfoEl = document.getElementById('performance_page_info');
                if (pageInfoEl) pageInfoEl.textContent = '- / -';
                return;
            }}
            statusEl.textContent = '조회 중...';
            tableEl.style.display = 'none';
            try {{
                const r = await fetch(`/api/performance/daily?date_from=${{encodeURIComponent(date_from)}}&date_to=${{encodeURIComponent(date_to)}}`, {{ credentials: 'include', headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }} }});
                if (!r.ok) {{
                    const err = await r.json().catch(() => ({{}}));
                    statusEl.textContent = err.message || ('조회 실패 ' + r.status);
                    return;
                }}
                const data = await r.json();
                if (!data.success) {{
                    statusEl.textContent = data.message || '조회 실패';
                    performanceDailyRows = [];
                    return;
                }}
                const rows = data.rows || [];
                if (rows.length === 0) {{
                    let msg = '해당 구간에 저장된 일별 성과가 없습니다.';
                    if (data.hint) msg += ' ' + data.hint;
                    statusEl.textContent = msg;
                    statusEl.title = data.queried_user ? ('조회 사용자: ' + data.queried_user) : '';
                    performanceDailyRows = [];
                    const pageInfoEl = document.getElementById('performance_page_info');
                    if (pageInfoEl) pageInfoEl.textContent = '0 / 0';
                    return;
                }}
                performanceDailyRows = rows;
                performanceDailyCurrentPage = 1;
                const sizeSel = document.getElementById('perf_page_size');
                if (sizeSel) {{
                    const v = parseInt(sizeSel.value, 10);
                    if (!isNaN(v) && v > 0) performanceDailyPageSize = v;
                }}
                renderPerformanceDailyPage();
            }} catch (e) {{
                statusEl.textContent = '로드 실패: ' + (e.message || '');
                performanceDailyRows = [];
            }}
        }}

        async function exportPerformanceCsv() {{
            const fromEl = document.getElementById('perf_date_from');
            const toEl = document.getElementById('perf_date_to');
            if (!fromEl || !toEl) return;
            const date_from = (fromEl.value || '').trim().replace(/[-/]/g, '').slice(0, 8);
            const date_to = (toEl.value || '').trim().replace(/[-/]/g, '').slice(0, 8);
            if (date_from.length !== 8 || date_to.length !== 8) {{
                alert('시작일·종료일을 선택한 뒤 내보내기를 실행해 주세요.');
                return;
            }}
            try {{
                const r = await fetch(`/api/performance/export?date_from=${{encodeURIComponent(date_from)}}&date_to=${{encodeURIComponent(date_to)}}&format=csv`, {{ credentials: 'include', headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }} }});
                if (!r.ok) {{ const j = await r.json().catch(() => ({{}})); throw new Error(j.message || r.statusText); }}
                const blob = await r.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'performance_' + date_from + '_' + date_to + '.csv';
                a.click();
                URL.revokeObjectURL(url);
            }} catch (e) {{
                alert('내보내기 실패: ' + (e.message || ''));
            }}
        }}

        function renderPerformanceDailyPage() {{
            const statusEl = document.getElementById('performance_daily_status');
            const tableEl = document.getElementById('performance_daily_table');
            const tbodyEl = document.getElementById('performance_daily_tbody');
            const pageInfoEl = document.getElementById('performance_page_info');
            if (!statusEl || !tableEl || !tbodyEl) return;
            const total = performanceDailyRows.length || 0;
            if (!total) {{
                tableEl.style.display = 'none';
                if (pageInfoEl) pageInfoEl.textContent = '0 / 0';
                return;
            }}
            const size = performanceDailyPageSize && performanceDailyPageSize > 0 ? performanceDailyPageSize : 30;
            const totalPages = Math.max(1, Math.ceil(total / size));
            if (performanceDailyCurrentPage < 1) performanceDailyCurrentPage = 1;
            if (performanceDailyCurrentPage > totalPages) performanceDailyCurrentPage = totalPages;
            const start = (performanceDailyCurrentPage - 1) * size;
            const pageRows = performanceDailyRows.slice(start, start + size);
            const fmtDate = s => s && s.length >= 8 ? s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8) : s;
            const fmtNum = n => (n != null && !isNaN(n)) ? Number(n).toLocaleString() : '-';
            const num = (v) => (v != null && v !== '' && !isNaN(Number(v))) ? Number(v) : null;
            tbodyEl.innerHTML = pageRows.map(row => {{
                const es = num(row.equity_start);
                const ee = num(row.equity_end);
                const pnlRaw = num(row.pnl);
                const pnl = pnlRaw != null ? pnlRaw : (ee != null && es != null ? ee - es : null);
                const pctRaw = num(row.return_pct);
                const pct = pctRaw != null ? pctRaw : (es && es !== 0 && pnl != null ? (pnl / es * 100) : null);
                const pnlCl = (pnl != null && pnl < 0) ? 'negative' : (pnl != null && pnl > 0) ? 'positive' : '';
                return `<tr>
                    <td>${{fmtDate(row.date)}}</td>
                    <td>${{fmtNum(row.equity_start)}}</td>
                    <td>${{fmtNum(row.equity_end)}}</td>
                    <td class="metric-value ${{pnlCl}}">${{pnl != null ? (pnl >= 0 ? '+' : '') + fmtNum(pnl) : '-'}}</td>
                    <td class="metric-value ${{pnlCl}}">${{pct != null ? (pct >= 0 ? '+' : '') + Number(pct).toFixed(2) + '%' : '-'}}</td>
                    <td>${{row.trade_count != null ? fmtNum(row.trade_count) : '-'}}</td>
                </tr>`;
            }}).join('');
            tableEl.style.display = 'table';
            statusEl.textContent = `총 ${{total.toLocaleString()}}건, ${{performanceDailyCurrentPage}} / ${{totalPages}} 페이지`;
            if (pageInfoEl) pageInfoEl.textContent = `${{performanceDailyCurrentPage}} / ${{totalPages}}`;
        }}

        function changePerformancePage(delta) {{
            const total = performanceDailyRows.length || 0;
            if (!total) return;
            const size = performanceDailyPageSize && performanceDailyPageSize > 0 ? performanceDailyPageSize : 30;
            const totalPages = Math.max(1, Math.ceil(total / size));
            let next = performanceDailyCurrentPage + delta;
            if (next < 1) next = 1;
            if (next > totalPages) next = totalPages;
            if (next === performanceDailyCurrentPage) return;
            performanceDailyCurrentPage = next;
            renderPerformanceDailyPage();
        }}

        function onChangePerformancePageSize() {{
            const sizeSel = document.getElementById('perf_page_size');
            if (!sizeSel) return;
            const v = parseInt(sizeSel.value, 10);
            if (!isNaN(v) && v > 0) {{
                performanceDailyPageSize = v;
                performanceDailyCurrentPage = 1;
                renderPerformanceDailyPage();
            }}
        }}

        async function loadPerformanceSummary() {{
            const metricsEl = document.getElementById('performance_metrics');
            const recEl = document.getElementById('performance_recommendations');
            if (!metricsEl || !recEl) return;
            try {{
                const r = await fetch('/api/performance/summary', {{ headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }} }});
                const data = await r.json();
                if (!data.success || !data.summary) {{
                    metricsEl.innerHTML = '<p style="color:var(--muted);">집계할 거래가 없거나 오류가 발생했습니다.</p>';
                    recEl.innerHTML = '<p style="color:var(--muted);">-</p>';
                    return;
                }}
                const s = data.summary;
                const pf = s.profit_factor != null ? Number(s.profit_factor).toFixed(2) : (s.losses === 0 && s.wins > 0 ? '∞' : '-');
                metricsEl.innerHTML = `
                    <div class="metric"><span class="metric-label" title="당일 매도 체결 손익 합계(거래내역 매도 행 손익 합계)">일일 실현손익</span><span class="metric-value">${{(s.total_pnl >= 0 ? '+' : '')}}${{Number(s.total_pnl).toLocaleString()}}원</span></div>
                    <div class="metric"><span class="metric-label" title="매수 체결 건수(매수+매도=1회 기준, 거래내역 체결 매수 행 개수)">거래 횟수</span><span class="metric-value">${{s.trade_count}}회</span></div>
                    <div class="metric"><span class="metric-label" title="승/(승+패) %, 0원은 승패 제외">Win rate</span><span class="metric-value">${{s.win_rate_pct}}%</span></div>
                    <div class="metric"><span class="metric-label" title="총 수익 / |총 손실|">Profit factor</span><span class="metric-value">${{pf}}</span></div>
                    <div class="metric"><span class="metric-label" title="매도 실현 중 수익 건수 / 손실 건수">승/패</span><span class="metric-value">${{s.wins}} / ${{s.losses}}</span></div>
                    <div class="metric"><span class="metric-label" title="수익 낸 매도 건당 평균">평균 수익</span><span class="metric-value">${{Number(s.avg_win).toLocaleString()}}원</span></div>
                    <div class="metric"><span class="metric-label" title="손실 낸 매도 건당 평균">평균 손실</span><span class="metric-value">${{Number(s.avg_loss).toLocaleString()}}원</span></div>
                    <div class="metric"><span class="metric-label" title="당일 누적 손익 구간 최대 낙폭">Max drawdown (세션)</span><span class="metric-value">${{Number(s.session_max_drawdown).toLocaleString()}}원 (${{s.session_max_drawdown_pct}}%)</span></div>
                `;
                if (s.recommendations && s.recommendations.length) {{
                    recEl.innerHTML = s.recommendations.map(rec => `
                        <p style="margin:6px 0; padding:8px; border-left:4px solid ${{rec.level === 'warning' ? '#e67e22' : rec.level === 'success' ? '#27ae60' : '#3498db'}};">${{rec.message}}</p>
                    `).join('');
                }} else {{
                    recEl.innerHTML = '<p style="color:var(--muted);">현재 성과 기준 권장 사항이 없습니다.</p>';
                }}
            }} catch (e) {{
                metricsEl.innerHTML = '<p style="color:var(--error);">로드 실패: ' + (e.message || '') + '</p>';
                recEl.innerHTML = '<p style="color:var(--muted);">-</p>';
            }}
            loadPerformancePeriodStats();
        }}

        async function loadPerformancePeriodStats() {{
            const el = document.getElementById('performance_period_metrics');
            if (!el) return;
            try {{
                const r = await fetch('/api/performance/period-stats?months=1', {{ headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }} }});
                const data = await r.json();
                if (!data.success) {{
                    el.innerHTML = '<p style="color:var(--muted);">' + (data.message || '기간 성과를 불러올 수 없습니다.') + '</p>';
                    return;
                }}
                const p = data.period_stats || {{}};
                const monthlyPct = p.monthly_return_pct != null ? (p.monthly_return_pct >= 0 ? '+' : '') + Number(p.monthly_return_pct).toFixed(2) + '%' : '-';
                const ddPct = p.period_max_drawdown_pct != null ? Number(p.period_max_drawdown_pct).toFixed(2) + '%' : '-';
                const monthlyCl = (p.monthly_return_pct != null && p.monthly_return_pct < 0) ? 'negative' : (p.monthly_return_pct != null && p.monthly_return_pct > 0) ? 'positive' : '';
                const winRatePct = p.period_win_rate_pct != null ? Number(p.period_win_rate_pct).toFixed(1) + '%' : '-';
                const pfVal = p.period_profit_factor != null ? Number(p.period_profit_factor).toFixed(2) : (p.period_trade_count > 0 ? '∞' : '-');
                el.innerHTML = `
                    <div class="metric"><span class="metric-label">Monthly return</span><span class="metric-value ${{monthlyCl}}">${{monthlyPct}}</span></div>
                    <div class="metric"><span class="metric-label">Max drawdown (기간)</span><span class="metric-value">${{ddPct}}</span></div>
                    <div class="metric"><span class="metric-label">Win rate (기간)</span><span class="metric-value">${{winRatePct}}</span></div>
                    <div class="metric"><span class="metric-label">Profit factor (기간)</span><span class="metric-value">${{pfVal}}</span></div>
                    <div class="metric"><span class="metric-label">기간 거래 횟수</span><span class="metric-value">${{(p.period_trade_count != null ? p.period_trade_count : 0)}}</span></div>
                `;
            }} catch (e) {{
                el.innerHTML = '<p style="color:var(--error);">로드 실패: ' + (e.message || '') + '</p>';
            }}
        }}

        function toggleUserMenu() {{
            const dd = document.getElementById('userDropdown');
            const av = document.getElementById('userAvatar');
            if (!dd || !av) return;
            const open = dd.classList.toggle('open');
            av.setAttribute('aria-expanded', open ? 'true' : 'false');
        }}

        function openProfileModal() {{
            closeUserMenu();
            const ov = document.getElementById('profileModalOverlay');
            if (ov) {{ ov.style.display = 'flex'; }}
            loadProfile();
        }}

        function closeProfileModal(ev) {{
            if (ev && ev.target !== ev.currentTarget) return;
            const ov = document.getElementById('profileModalOverlay');
            if (ov) {{ ov.style.display = 'none'; }}
        }}

        async function loadProfile() {{
            try {{
                const response = await fetch('/api/profile', {{ credentials: 'include' }});
                const data = await response.json();
                if (data.success && data.profile) {{
                    const p = data.profile;
                    const set = (id, val) => {{ const el = document.getElementById(id); if (el) el.value = (val != null && val !== undefined) ? String(val) : ''; }};
                    set('profile_email', p.email);
                    set('profile_real_cano', p.real_cano);
                    set('profile_real_acnt_no', p.real_acnt_no);
                    set('profile_paper_cano', p.paper_cano);
                    set('profile_paper_acnt_no', p.paper_acnt_no);
                }} else {{
                    addLog('프로필 로드 실패: ' + (data.message || '알 수 없음'), 'warning');
                }}
            }} catch (e) {{
                addLog('프로필 로드 오류: ' + (e.message || ''), 'error');
            }}
        }}

        async function saveProfile() {{
            try {{
                const get = (id) => {{ const el = document.getElementById(id); return el ? (el.value || '').trim() : ''; }};
                const body = {{
                    email: get('profile_email'),
                    real_cano: get('profile_real_cano'),
                    real_acnt_no: get('profile_real_acnt_no'),
                    paper_cano: get('profile_paper_cano'),
                    paper_acnt_no: get('profile_paper_acnt_no'),
                }};
                const response = await fetch('/api/profile', {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    credentials: 'include',
                    body: JSON.stringify(body)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog('프로필이 저장되었습니다.', 'info');
                    closeProfileModal();
                }} else {{
                    addLog('프로필 저장 실패: ' + (data.message || '알 수 없음'), 'error');
                }}
            }} catch (e) {{
                addLog('프로필 저장 오류: ' + (e.message || ''), 'error');
            }}
        }}

        async function changePassword() {{
            const current = (document.getElementById('profile_current_password')?.value || '').trim();
            const newPw = (document.getElementById('profile_new_password')?.value || '').trim();
            const confirmPw = (document.getElementById('profile_new_password_confirm')?.value || '').trim();
            if (!current) {{
                addLog('현재 비밀번호를 입력하세요.', 'warning');
                return;
            }}
            if (newPw.length < 4) {{
                addLog('새 비밀번호는 4자 이상이어야 합니다.', 'warning');
                return;
            }}
            if (newPw !== confirmPw) {{
                addLog('새 비밀번호가 일치하지 않습니다.', 'warning');
                return;
            }}
            try {{
                const response = await fetch('/api/auth/change-password', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    credentials: 'include',
                    body: JSON.stringify({{ current_password: current, new_password: newPw }})
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog('비밀번호가 변경되었습니다.', 'info');
                    document.getElementById('profile_current_password').value = '';
                    document.getElementById('profile_new_password').value = '';
                    document.getElementById('profile_new_password_confirm').value = '';
                }} else {{
                    addLog(data.message || '비밀번호 변경 실패', 'error');
                }}
            }} catch (e) {{
                addLog('비밀번호 변경 오류: ' + (e.message || ''), 'error');
            }}
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
            const sections = ['preset', 'risk', 'strategy', 'stocks', 'operational', 'help'];
            sections.forEach(s => {{
                const sec = document.getElementById(`settings-section-${{s}}`);
                const btn = document.getElementById(`subtab-${{s}}`);
                if (sec) sec.classList.toggle('active', s === name);
                if (btn) btn.classList.toggle('active', s === name);
            }});
            updateSettingsSummaries();
        }}

        function showDocsSection(name) {{
            const sections = ['overview', 'workflow', 'files', 'functions'];
            sections.forEach(s => {{
                const sec = document.getElementById(`doc-section-${{s}}`);
                const btn = document.getElementById(`doc-subtab-${{s}}`);
                if (sec) sec.classList.toggle('active', s === name);
                if (btn) btn.classList.toggle('active', s === name);
            }});
        }}

        function showPerformanceSection(name) {{
            const sections = ['summary', 'daily'];
            sections.forEach(s => {{
                const sec = document.getElementById(`performance-section-${{s}}`);
                const btn = document.getElementById(`perf-subtab-${{s}}`);
                if (sec) sec.classList.toggle('active', s === name);
                if (btn) btn.classList.toggle('active', s === name);
            }});
            if (name === 'daily') ensurePerformanceDailyRangeAndLoad();
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
            }} else if (data.type === 'selected_stocks') {{
                const d = data.data || {{}};
                renderSelectedStocks(d.info || d.codes || []);
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
            window._systemRunning = !!data.is_running;
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
            const hintEl = document.getElementById('balance_hint');
            if (hintEl) {{
                if (data.kis_account_balance_ok) {{
                    const kisVal = data.kis_account_balance != null ? Number(data.kis_account_balance) : null;
                    const dispVal = data.account_balance != null ? Number(data.account_balance) : null;
                    if (kisVal != null && dispVal != null && kisVal !== dispVal) {{
                        hintEl.textContent = 'KIS: ' + formatNumber(kisVal) + '원 (표시와 상이 시 확인)';
                        hintEl.title = '표시 잔고와 KIS API 잔고가 다릅니다.';
                    }} else {{
                        hintEl.textContent = 'KIS API와 일치';
                        hintEl.title = '당일 조회한 KIS 잔고와 동일합니다.';
                    }}
                }} else {{
                    hintEl.textContent = data.is_paper_trading ? '표시: 시작잔고+일일손익 (모의투자)' : 'KIS 미조회';
                    hintEl.title = '모의투자 시 KIS가 거래 반영이 늦을 수 있어 시작잔고+일일손익으로 표시합니다.';
                }}
            }}
            document.getElementById('daily_pnl').textContent = formatNumber(data.daily_pnl) + '원';
            document.getElementById('daily_pnl').className = 'metric-value ' + (data.daily_pnl >= 0 ? 'positive' : 'negative');
            document.getElementById('daily_trades').textContent = data.daily_trades + '회';
            const posBalance = document.getElementById('pos_balance');
            if (posBalance) {{ posBalance.textContent = formatNumber(data.account_balance) + '원'; }}
            const posPnl = document.getElementById('pos_daily_pnl');
            if (posPnl) {{ posPnl.textContent = formatNumber(data.daily_pnl) + '원'; posPnl.className = 'metric-value ' + (data.daily_pnl >= 0 ? 'positive' : 'negative'); }}
            const posTrades = document.getElementById('pos_daily_trades');
            if (posTrades) {{ posTrades.textContent = data.daily_trades + '회'; }}
            // 설정 입력 중에는 서버 폴링 값으로 덮어쓰지 않음(저장 전 '되돌아감' 방지)
            const activeId = (document.activeElement && document.activeElement.id) ? document.activeElement.id : '';
            if (data.short_ma_period != null) {{
                const el = document.getElementById('short_ma_period');
                if (el && activeId !== 'short_ma_period') el.value = data.short_ma_period;
            }}
            if (data.long_ma_period != null) {{
                const el = document.getElementById('long_ma_period');
                if (el && activeId !== 'long_ma_period') el.value = data.long_ma_period;
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
            window.__lastStockSelectionCriteria = data.stock_selection_criteria || null;
            window.__selected_stock_info = data.selected_stock_info || data.selected_stocks || [];
            renderStockSelectionDebug(data.stock_selection_last_debug || null, data.stock_selection_last_error || '');
            if (data.positions != null) updatePositions(data.positions);
            renderBuySkipStats(data.buy_skip_stats || null);
            if (data.enable_auto_rebalance != null) {{
                const el = document.getElementById('enable_auto_rebalance');
                if (el) el.checked = !!data.enable_auto_rebalance;
            }}
            if (data.auto_rebalance_interval_minutes != null) {{
                const el = document.getElementById('auto_rebalance_interval_minutes');
                if (el) el.value = data.auto_rebalance_interval_minutes;
            }}
            if (data.enable_performance_auto_recommend != null) {{
                const el = document.getElementById('enable_performance_auto_recommend');
                if (el) el.checked = !!data.enable_performance_auto_recommend;
            }}
            if (data.performance_recommend_interval_minutes != null) {{
                const el = document.getElementById('performance_recommend_interval_minutes');
                if (el) el.value = data.performance_recommend_interval_minutes;
            }}
            // Preflight badge/status
            if (window._systemRunning) {{
                _setPreflightBadge('warn', '실행 중');
                const box = document.getElementById('preflightResult');
                if (box) box.style.display = 'none';
            }} else {{
                if (!window.__lastPreflight) {{
                    _setPreflightBadge('', '미실행');
                }}
            }}
            updateSettingsSummaries();
        }}

        function _labelSkipKey(key) {{
            const k = (key || '').toString();
            const map = {{
                spread: '스프레드 과대',
                range: '횡보장 제외',
                slope: '단기MA 기울기 부족',
                momentum: '모멘텀 부족',
                near_high: '고점 근접(추격) 회피',
                below_high: '고점 대비 하락(하락추세)',
                minute_trend: '분봉 추세 유지 실패',
                cooldown: '재진입 쿨다운',
                confirm: '진입 확인 대기',
                confirm2: '진입 보강 조건 미충족',
                time_window: '신규매수 시간외',
                unknown: '기타',
            }};
            return map[k] || k;
        }}

        function renderBuySkipStats(stats) {{
            const el = document.getElementById('skip_stats');
            if (!el) return;
            // null/미수신 시에도 0 기준으로 동일 레이아웃 표시 (상태 탭에서 항상 누적 스킵 등 정보 노출)
            const total = (stats && stats.total != null) ? stats.total : 0;
            const byReason = (stats && Array.isArray(stats.by_reason)) ? stats.by_reason : [];
            const topStocks = (stats && Array.isArray(stats.top_stocks)) ? stats.top_stocks : [];

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
                    const dtl = document.getElementById('daily_total_loss_limit')?.value || '0';
                    const dlb = document.getElementById('daily_loss_limit_basis')?.value || 'realized';
                    const dpb = document.getElementById('daily_profit_limit_basis')?.value || 'total';
                    const mtpd = document.getElementById('max_trades_per_day')?.value || '12';
                    const pt = document.getElementById('partial_tp_pct')?.value || '0';
                    const tr = document.getElementById('trailing_stop_pct')?.value || '0';
                    const legacyLoss = (parseInt(dtl || '0') > 0) ? (' · legacyTotalLoss=' + dtl + '원') : '';
                    risk.textContent =
                        'max=' + maxAmt + '원 · ' +
                        'minQty=' + minQty + '주 · ' +
                        'SL=' + sl + '%/TP=' + tp + '% · ' +
                        'dailyLoss=' + dly + '원(' + dlb + ') · ' +
                        'maxTrades=' + mtpd + '회/일 · ' +
                        'dailyProfit=' + dpr + '원(' + dpb + ')' +
                        legacyLoss + ' · ' +
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
                    const momN = document.getElementById('momentum_lookback_ticks')?.value || '0';
                    const momP = document.getElementById('min_momentum_pct')?.value || '0';
                    const ec = !!document.getElementById('entry_confirm_enabled')?.checked;
                    const cd = document.getElementById('reentry_cooldown_seconds')?.value || '240';
                    const conf = document.getElementById('buy_confirm_ticks')?.value || '1';
                    const spr = document.getElementById('max_spread_pct')?.value || '0';
                    const n = document.getElementById('range_lookback_ticks')?.value || '0';
                    const rr = document.getElementById('min_range_pct')?.value || '0';
                    const liqOn = !!document.getElementById('enable_time_liquidation')?.checked;
                    const liqAt = document.getElementById('liquidate_after_hhmm')?.value || '-';
                    const idxMaOn = !!document.getElementById('index_ma_filter_enabled')?.checked;
                    const idxCode = document.getElementById('index_ma_code')?.value || '1001';
                    const idxPeriod = document.getElementById('index_ma_period')?.value || '20';
                    const idxLabel = (idxCode === '1001' ? '코스닥' : '코스피') + idxPeriod + 'd';
                    const advOn = !!document.getElementById('advance_ratio_filter_enabled')?.checked;
                    const advMin = document.getElementById('advance_ratio_min_pct')?.value || '40';
                    const tvcOn = !!document.getElementById('trade_value_concentration_filter_enabled')?.checked;
                    const tvcTop = document.getElementById('trade_value_concentration_top_n')?.value || '10';
                    const tvcMax = document.getElementById('trade_value_concentration_max_pct')?.value || '45';
                    strat.textContent =
                        'MA=' + sma + '/' + lma + ' · ' +
                        'buy=' + bwS + '-' + bwE + ' · ' +
                        'slope≥' + slope + '%/t · ' +
                        'mom≥' + momP + '%/N' + momN + ' · ' +
                        'confirm2=' + (ec ? 'on' : 'off') + ' · ' +
                        'cd=' + cd + 's · ' +
                        (idxMaOn ? '지수MA=' + idxLabel + ' · ' : '') +
                        (advOn ? '상승비율≥' + advMin + '% · ' : '') +
                        (tvcOn ? '거래대금집중<' + tvcMax + '%(상위' + tvcTop + ') · ' : '') +
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
                    const sb = document.getElementById('stock_sort_by')?.value || 'change';
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
                        'sort=' + sb + ' · ' +
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

        function renderStockSelectionDebug(debug, errMsg) {{
            const el = document.getElementById('stock_selection_debug');
            if (!el) return;
            const dbg = (debug && typeof debug === 'object') ? debug : {{}};
            const keys = Object.keys(dbg || {{}}).sort();
            const hasKeys = keys.length > 0;
            const errTxt = (errMsg == null) ? '' : String(errMsg);
            const hasErr = errTxt.trim().length > 0;

            if (!hasKeys && !hasErr) {{
                el.innerHTML = '<div class="hint" style="margin-top:6px;">선정 디버그가 없습니다. (선정 시도 후 업데이트)</div>';
                return;
            }}

            let html = '';
            html += '<div class="preflight-box" style="margin-top:0;">';
            html += '<div style="font-size:12px; color:var(--muted); font-weight:600; margin-bottom:8px;">선정 디버그 (StockSelector)</div>';
            if (hasErr) {{
                html += '<div class="hint" style="margin-bottom:8px; color:var(--err);">error: ' + _escapeHtml(errTxt) + '</div>';
            }}
            html += '<div style="max-height:140px; overflow:auto;">';
            html += '<table class="table"><thead><tr><th style="width:45%;">key</th><th>value</th></tr></thead><tbody>';
            const limit = Math.min(25, keys.length);
            for (let i = 0; i < limit; i++) {{
                const k = keys[i];
                let v = null;
                try {{
                    v = dbg[k];
                }} catch (e) {{
                    v = null;
                }}
                let vStr = '';
                try {{
                    if (v == null) vStr = '-';
                    else if (typeof v === 'object') vStr = JSON.stringify(v);
                    else vStr = String(v);
                }} catch (e) {{
                    vStr = '-';
                }}
                html += '<tr><td>' + _escapeHtml(k) + '</td><td>' + _escapeHtml(vStr) + '</td></tr>';
            }}
            if (keys.length > limit) {{
                html += '<tr><td colspan="2" style="color:var(--muted);">... ' + (keys.length - limit) + ' more</td></tr>';
            }}
            html += '</tbody></table>';
            html += '</div>';
            html += '</div>';

            el.innerHTML = html;
        }}

        function criteriaToHtml(criteria) {{
            if (!criteria || typeof criteria !== 'object') {{
                return '<p style="color: var(--muted);">저장된 선정 기준이 없습니다. 설정 탭에서 종목선정 조건을 저장하면 여기에 표시됩니다.</p>';
            }}
            const fmt = (v) => (v == null || v === '') ? '—' : String(v);
            const pct = (v) => (v != null && v !== '') ? (Number(v) * 100).toFixed(1) + '%' : '—';
            const num = (v) => (v != null && v !== '') ? Number(v).toLocaleString() : '—';
            const sortLabels = {{ 'change': '등락률', 'trade_amount': '거래대금', 'prev_day_trade_value': '전일 거래대금' }};
            const lines = [
                ['등락률 범위', pct(criteria.min_price_change_ratio) + ' ~ ' + pct(criteria.max_price_change_ratio)],
                ['가격 범위', num(criteria.min_price) + '원 ~ ' + num(criteria.max_price) + '원'],
                ['최소 거래량', num(criteria.min_volume) + '주'],
                ['최소 거래대금', (criteria.min_trade_amount && Number(criteria.min_trade_amount) > 0) ? num(criteria.min_trade_amount) + '원' : '미적용'],
                ['최대 선정 종목 수', fmt(criteria.max_stocks)],
                ['정렬 기준', sortLabels[criteria.sort_by] || fmt(criteria.sort_by)],
                ['위험/경고 종목 제외', criteria.exclude_risk_stocks ? '예' : '아니오'],
                ['장 시작 워밍업', fmt(criteria.warmup_minutes) + '분'],
                ['장초 강화(early_strict)', criteria.early_strict ? '예' : '아니오'],
                ['장초 최소 거래량', num(criteria.early_min_volume)],
                ['장초 최소 거래대금', (criteria.early_min_trade_amount && Number(criteria.early_min_trade_amount) > 0) ? num(criteria.early_min_trade_amount) + '원' : '미적용'],
                ['고점 대비 하락 제외', criteria.exclude_drawdown ? '예' : '아니오'],
                ['코스피만', criteria.kospi_only ? '예' : '아니오'],
            ];
            return '<dl style="margin:0; padding:0;">' + lines.map(([label, value]) => `<dt style="margin:6px 0 2px 0; color: var(--muted); font-weight:600;">${{label}}</dt><dd style="margin:0 0 8px 0;">${{value}}</dd>`).join('') + '</dl>';
        }}

        function openCriteriaModal() {{
            const body = document.getElementById('criteria_modal_body');
            const overlay = document.getElementById('criteriaModalOverlay');
            if (body) body.innerHTML = criteriaToHtml(window.__lastStockSelectionCriteria || null);
            if (overlay) overlay.style.display = 'flex';
        }}

        function closeCriteriaModal(event) {{
            if (event && event.target !== document.getElementById('criteriaModalOverlay')) return;
            const overlay = document.getElementById('criteriaModalOverlay');
            if (overlay) overlay.style.display = 'none';
        }}

        function updatePositions(positions) {{
            const container = document.getElementById('positions');
            if (!positions || Object.keys(positions).length === 0) {{
                container.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 20px;">보유 종목이 없습니다.</p>';
                return;
            }}
            const infoList = window.__selected_stock_info || [];
            const codeToName = {{}};
            infoList.forEach(function(item) {{ const c = (item.code || '').toString().trim(); if (c) codeToName[c] = (item.name || '').toString().trim(); }});
            let html = '<table><thead><tr><th>종목</th><th>수량</th><th>매수가</th><th>매수금액</th><th>현재가</th><th>평가금액</th><th>손익</th><th>동작</th></tr></thead><tbody>';
            for (const [code, pos] of Object.entries(positions)) {{
                const name = (pos.stock_name || pos.name || codeToName[code] || '').toString().trim();
                const stockLabel = (name && name.length) ? (code + ' ' + name) : code;
                const buyAmt = (pos.buy_price || 0) * (pos.quantity || 0);
                const evalAmt = (pos.current_price || 0) * (pos.quantity || 0);
                const pnl = evalAmt - buyAmt;
                html += `<tr>
                    <td>${{stockLabel}}</td>
                    <td>${{pos.quantity}}주</td>
                    <td>${{formatNumber(pos.buy_price)}}원</td>
                    <td>${{formatNumber(Math.round(buyAmt))}}원</td>
                    <td>${{formatNumber(pos.current_price)}}원</td>
                    <td>${{formatNumber(Math.round(evalAmt))}}원</td>
                    <td class="${{pnl >= 0 ? 'positive' : 'negative'}}">${{formatNumber(pnl)}}원</td>
                    <td><button type="button" class="btn btn-inline" style="font-size: 12px; padding: 4px 10px;" onclick="liquidatePosition('${{code}}', this)">청산</button></td>
                </tr>`;
            }}
            html += '</tbody></table>';
            container.innerHTML = html;
        }}

        async function liquidatePosition(code, btnEl) {{
            if (!code) return;
            if (!confirm('해당 종목(' + code + ') 전량 매도 신호를 보낼까요? 수동 모드면 승인 대기, 자동 모드면 즉시 주문됩니다.')) return;
            const btn = btnEl && btnEl.nodeName ? btnEl : document.querySelector('[data-liquidate="' + code + '"]');
            if (btn) {{ btn.disabled = true; btn.textContent = '처리중...'; }}
            try {{
                const r = await fetch('/api/positions/liquidate', {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
                    body: JSON.stringify({{ stock_code: code }})
                }});
                const data = await r.json();
                if (data.success) {{
                    if (typeof addLog === 'function') addLog(data.message || '청산 신호 처리됨', 'info');
                    refreshData();
                }} else {{
                    if (typeof addLog === 'function') addLog(data.message || '청산 요청 실패', 'error');
                    alert(data.message || '청산 요청 실패');
                }}
            }} catch (e) {{
                if (typeof addLog === 'function') addLog('청산 요청 오류: ' + (e.message || e), 'error');
                alert('청산 요청 오류: ' + (e.message || e));
            }}
            if (btn) {{ btn.disabled = false; btn.textContent = '청산'; }}
        }}

        function _stockLabelFromTrade(tr) {{
            const code = (tr.stock_code || tr.stockCode || '').toString().trim();
            let name = (tr.stock_name || tr.stockName || '').toString().trim();
            if (!name && code && window.__selected_stock_info && Array.isArray(window.__selected_stock_info)) {{
                for (const item of window.__selected_stock_info) {{
                    if ((item.code || '').toString().trim() === code) {{ name = (item.name || '').toString().trim(); break; }}
                }}
            }}
            return (name && name.length) ? (code + ' ' + name) : (code || '-');
        }}

        let systemTradeRows = [];

        function _systemTradeNormStatus(t) {{
            const st = (t.order_status || t.status || '').toString().toLowerCase();
            if (st === 'accepted_pending' || st === 'pending' || st === '접수' || st === '대기') return 'accepted_pending';
            if (st) return 'filled';
            return '';
        }}

        function _systemTradeStatusLabel(norm) {{
            if (norm === 'accepted_pending') return '접수(대기)';
            if (norm === 'filled') return '체결';
            return '-';
        }}

        function updateSystemTradeFilters() {{
            const stockSel = document.getElementById('system_trade_filter_stock');
            const sideSel = document.getElementById('system_trade_filter_side');
            const statusSel = document.getElementById('system_trade_filter_status');
            if (stockSel && !stockSel.__bound) {{
                stockSel.__bound = true;
                stockSel.addEventListener('change', renderSystemTrades);
            }}
            if (sideSel && !sideSel.__bound) {{
                sideSel.__bound = true;
                sideSel.addEventListener('change', renderSystemTrades);
            }}
            if (statusSel && !statusSel.__bound) {{
                statusSel.__bound = true;
                statusSel.addEventListener('change', renderSystemTrades);
            }}
            if (!stockSel) return;
            const cur = stockSel.value;
            const codes = new Set();
            (systemTradeRows || []).forEach(t => {{
                const code = (t.stock_code || '').toString().trim();
                if (code) codes.add(code);
            }});
            const values = Array.from(codes).sort();
            stockSel.innerHTML = '<option value="">전체</option>' + values.map(v => `<option value="${{v}}">${{v}}</option>`).join('');
            if (values.includes(cur)) stockSel.value = cur;
        }}

        function renderSystemTrades() {{
            const tbody = document.getElementById('trade_history_body');
            if (!tbody) return;
            tbody.innerHTML = '';
            const stockFilter = (document.getElementById('system_trade_filter_stock')?.value || '').trim();
            const sideFilter = (document.getElementById('system_trade_filter_side')?.value || '').trim();
            const statusFilter = (document.getElementById('system_trade_filter_status')?.value || '').trim();

            const rows = (systemTradeRows || []).filter(t => {{
                const code = (t.stock_code || '').toString().trim();
                const side = (t.order_type || '').toString().toLowerCase();
                const normStatus = _systemTradeNormStatus(t);
                if (stockFilter && code !== stockFilter) return false;
                if (sideFilter && side !== sideFilter) return false;
                if (statusFilter && normStatus !== statusFilter) return false;
                return true;
            }});

            if (!rows.length) {{
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--muted);">해당 조건의 거래내역이 없습니다.</td></tr>';
                return;
            }}

            rows.forEach(t => {{
                const ts = t.timestamp || (t.date && t.time ? t.date.replace(/(\\d{{4}})(\\d{{2}})(\\d{{2}})/, '$1-$2-$3') + 'T' + (t.time || '000000').replace(/(\\d{{2}})(\\d{{2}})(\\d{{2}})/, '$1:$2:$3') : '');
                const reason = (t.reason || '').toString().trim() || '-';
                const pnl = t.pnl != null ? formatNumber(t.pnl) + '원' : '-';
                const stockLabel = _stockLabelFromTrade(t);
                const normStatus = _systemTradeNormStatus(t);
                const statusLabel = _systemTradeStatusLabel(normStatus);
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${{ts ? new Date(ts).toLocaleTimeString() : '-'}}</td>
                    <td>${{stockLabel}}</td>
                    <td style="color:${{statusLabel.startsWith('접수') ? 'var(--muted)' : 'var(--text)'}};">${{statusLabel}}</td>
                    <td>${{(t.order_type || '').toLowerCase() === 'buy' ? '매수' : '매도'}}</td>
                    <td>${{t.quantity != null ? t.quantity + '주' : '-'}}</td>
                    <td>${{t.price != null ? formatNumber(t.price) + '원' : '-'}}</td>
                    <td class="${{t.pnl != null && t.pnl < 0 ? 'negative' : (t.pnl > 0 ? 'positive' : '')}}">${{pnl}}</td>
                    <td style="max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${{reason}}">${{reason}}</td>
                `;
                tbody.appendChild(row);
            }});
        }}

        function addTradeToHistory(trade) {{
            // 실시간 trade 이벤트도 필터 대상이므로 배열에 누적 후 렌더
            try {{
                systemTradeRows = [trade, ...(systemTradeRows || [])];
                if (systemTradeRows.length > 500) systemTradeRows = systemTradeRows.slice(0, 500);
            }} catch (e) {{}}
            updateSystemTradeFilters();
            renderSystemTrades();
        }}

        function showTradeSubtab(kind) {{
            document.getElementById('btn-trades-system').classList.toggle('active', kind === 'system');
            document.getElementById('btn-trades-account').classList.toggle('active', kind === 'account');
            document.getElementById('trade-panel-system').style.display = kind === 'system' ? 'block' : 'none';
            document.getElementById('trade-panel-account').style.display = kind === 'account' ? 'block' : 'none';
            if (kind === 'system') {{
                const today = new Date().toISOString().slice(0, 10);
                const el = document.getElementById('trades_system_date');
                if (el && !el.value) el.value = today;
            }} else if (kind === 'account') {{
                if (!document.getElementById('trades_account_date').value)
                    document.getElementById('trades_account_date').value = new Date().toISOString().slice(0, 10);
            }}
        }}

        async function fetchSystemTrades() {{
            const dateEl = document.getElementById('trades_system_date');
            const dateStr = dateEl ? dateEl.value.replace(/-/g, '') : new Date().toISOString().slice(0, 10).replace(/-/g, '');
            try {{
                const q = new URLSearchParams();
                if (dateStr) {{ q.set('date_from', dateStr); q.set('date_to', dateStr); }}
                const resp = await fetch('/api/trades/system?' + q.toString());
                const data = await resp.json();
                systemTradeRows = Array.isArray(data) ? data : [];
                updateSystemTradeFilters();
                renderSystemTrades();
            }} catch (e) {{
                addLog('시스템 거래내역 조회 실패: ' + e, 'error');
            }}
        }}

        let accountTradeRows = [];

        function _accountTradeKey(r, ...keys) {{
            for (const k of keys) {{
                const v = r[k] ?? r[(k || '').toUpperCase()];
                if (v !== undefined && v !== null && v !== '') return v;
            }}
            return '';
        }}

        function renderAccountTrades() {{
            const tbody = document.getElementById('account_trade_history_body');
            if (!tbody) return;
            tbody.innerHTML = '';

            const sideFilter = (document.getElementById('account_trade_filter_side')?.value || '').trim();
            const pdnoFilter = (document.getElementById('account_trade_filter_pdno')?.value || '').trim();

            const rows = (accountTradeRows || []).filter(r => {{
                const sllBuy = _accountTradeKey(r, 'sll_buy_dvsn_cd', 'SLL_BUY_DVSN_CD');
                const side = (sllBuy === '02' || String(sllBuy).toLowerCase() === '02') ? '매수' : (sllBuy === '01' ? '매도' : String(sllBuy || ''));
                const pdno = _accountTradeKey(r, 'pdno', 'PDNO') || '-';
                if (sideFilter && side !== sideFilter) return false;
                if (pdnoFilter && pdno !== pdnoFilter) return false;
                return true;
            }});

            if (!rows.length) {{
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--muted);">해당 조건의 거래내역이 없습니다.</td></tr>';
                return;
            }}

            rows.forEach(r => {{
                const ordDt = _accountTradeKey(r, 'ord_dt', 'ORD_DT') || '';
                const ordTmd = _accountTradeKey(r, 'ord_tmd', 'ORD_TMD') || '';
                const sllBuy = _accountTradeKey(r, 'sll_buy_dvsn_cd', 'SLL_BUY_DVSN_CD');
                const side = (sllBuy === '02' || String(sllBuy).toLowerCase() === '02') ? '매수' : (sllBuy === '01' ? '매도' : String(sllBuy || ''));
                const pdno = _accountTradeKey(r, 'pdno', 'PDNO') || '-';
                const prdtName = _accountTradeKey(r, 'prdt_name', 'PRDT_NAME', 'hts_kor_isnm', 'HTS_KOR_ISNM', 'prd_name', 'PRD_NAME');
                const ordQty = _accountTradeKey(r, 'ord_qty', 'ORD_QTY');
                const ccldQty = _accountTradeKey(r, 'ccld_qty', 'CCLD_QTY', 'tot_ccld_qty', 'TOT_CCLD_QTY', 'ccld_qty_tot', 'CCLD_QTY_TOT') || ordQty;
                const avgPrc = _accountTradeKey(r, 'avg_prvs', 'AVG_PRC', 'ccld_unpr', 'CCLD_UNPR', 'ord_unpr', 'ORD_UNPR');
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${{ordDt ? ordDt.replace(/(\\d{{4}})(\\d{{2}})(\\d{{2}})/, '$1-$2-$3') : '-'}}</td>
                    <td>${{ordTmd ? (String(ordTmd).slice(0,2) + ':' + String(ordTmd).slice(2,4) + ':' + String(ordTmd).slice(4,6)) : '-'}}</td>
                    <td>${{side || '-'}}</td>
                    <td>${{pdno}}</td>
                    <td style="max-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${{prdtName || ''}}">${{prdtName || '-'}}</td>
                    <td>${{ordQty != null && ordQty !== '' ? formatNumber(Number(ordQty)) : '-'}}</td>
                    <td>${{ccldQty != null && ccldQty !== '' ? formatNumber(Number(ccldQty)) : (ordQty != null && ordQty !== '' ? formatNumber(Number(ordQty)) : '-')}}</td>
                    <td>${{avgPrc != null && avgPrc !== '' ? formatNumber(Number(avgPrc)) + '원' : '-'}}</td>
                `;
                tbody.appendChild(row);
            }});
        }}

        function _setSelectOptions(sel, values) {{
            if (!sel) return;
            const cur = sel.value;
            sel.innerHTML = '<option value="">전체</option>' + values.map(v => `<option value="${{v}}">${{v}}</option>`).join('');
            if (values.includes(cur)) sel.value = cur;
        }}

        function updateAccountTradeFilters() {{
            const sideSel = document.getElementById('account_trade_filter_side');
            const pdnoSel = document.getElementById('account_trade_filter_pdno');
            const sides = new Set();
            const pdnos = new Set();
            (accountTradeRows || []).forEach(r => {{
                const sllBuy = _accountTradeKey(r, 'sll_buy_dvsn_cd', 'SLL_BUY_DVSN_CD');
                const side = (sllBuy === '02' || String(sllBuy).toLowerCase() === '02') ? '매수' : (sllBuy === '01' ? '매도' : String(sllBuy || ''));
                const pdno = _accountTradeKey(r, 'pdno', 'PDNO') || '-';
                if (side) sides.add(side);
                if (pdno) pdnos.add(pdno);
            }});
            _setSelectOptions(sideSel, Array.from(sides).sort());
            _setSelectOptions(pdnoSel, Array.from(pdnos).sort());
            if (sideSel && !sideSel.__bound) {{
                sideSel.__bound = true;
                sideSel.addEventListener('change', renderAccountTrades);
            }}
            if (pdnoSel && !pdnoSel.__bound) {{
                pdnoSel.__bound = true;
                pdnoSel.addEventListener('change', renderAccountTrades);
            }}
        }}

        async function fetchAccountTrades() {{
            const dateEl = document.getElementById('trades_account_date');
            const dateStr = dateEl ? dateEl.value.replace(/-/g, '') : new Date().toISOString().slice(0, 10).replace(/-/g, '');
            try {{
                const resp = await fetch('/api/trades/account?date=' + encodeURIComponent(dateStr));
                const data = await resp.json();
                const tbody = document.getElementById('account_trade_history_body');
                tbody.innerHTML = '';
                if (data.error && !data.rows) {{
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--danger);">' + (data.error || '조회 실패') + '</td></tr>';
                    return;
                }}
                accountTradeRows = data.rows || [];
                updateAccountTradeFilters();
                renderAccountTrades();
                if (!accountTradeRows.length) {{
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--muted);">' + (data.date || dateStr) + ' 거래내역이 없습니다.</td></tr>';
                }}
            }} catch (e) {{
                addLog('계좌 거래내역 조회 실패: ' + e, 'error');
            }}
        }}

        async function syncPositionsFromBalance() {{
            try {{
                const r = await fetch('/api/positions/sync-from-balance', {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
                }});
                const data = await r.json();
                if (!data.success) {{
                    addLog('포지션 동기화 실패: ' + (data.message || '오류'), 'error');
                    return;
                }}
                addLog('포지션 동기화 완료: ' + (data.message || ''), 'info');
                if (data.attempt) {{
                    try {{
                        addLog('포지션 동기화 attempt: ' + JSON.stringify(data.attempt), 'info');
                    }} catch (e) {{}}
                }}
                await refreshData();
            }} catch (e) {{
                addLog('포지션 동기화 오류: ' + e, 'error');
            }}
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
                // 시작 전 Preflight를 먼저 실행해 UI에 차단 사유를 즉시 표시
                const pf = await runPreflight(true);
                if (pf && pf.success && pf.preflight && pf.preflight.ok === false) {{
                    renderPreflight(pf.preflight);
                    addLog('시스템 시작 차단(Preflight): issues를 해결한 뒤 다시 시도하세요.', 'error');
                    return;
                }}
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
                const response = await fetch('/api/system/status?t=' + Date.now());
                if (!response.ok) {{
                    renderBuySkipStats(null);
                    return;
                }}
                const data = await response.json();
                updateStatus(data);
            }} catch (error) {{
                renderBuySkipStats(null);
                addLog('새로고침 오류: ' + error, 'error');
            }}
        }}

        async function loadUserSettings() {{
            try {{
                const response = await fetch('/api/config/user-settings', {{ credentials: 'include' }});
                const data = await response.json();
                if (!data.success) {{
                    if (response.status === 401) addLog('설정 로드: 로그인이 필요합니다.', 'warning');
                    return;
                }}
                const s = data.settings || {{}};
                window.__custom_slots = s.custom_slots || {{}};
                refreshCustomSlotDropdown();
                const risk = s.risk_config || null;
                const strat = s.strategy_config || null;
                const stocksel = s.stock_selection_config || null;
                const oper = s.operational_config || null;

                if (risk) {{
                    if (risk.max_single_trade_amount != null && risk.max_single_trade_amount !== undefined) document.getElementById('max_trade_amount').value = String(risk.max_single_trade_amount);
                    if (risk.min_order_quantity != null) document.getElementById('min_order_quantity').value = risk.min_order_quantity;
                    if (risk.stop_loss_ratio != null) document.getElementById('stop_loss').value = (risk.stop_loss_ratio * 100).toFixed(1);
                    if (risk.take_profit_ratio != null) document.getElementById('take_profit').value = (risk.take_profit_ratio * 100).toFixed(1);
                    if (risk.daily_loss_limit != null) document.getElementById('daily_loss_limit').value = risk.daily_loss_limit;
                    if (risk.daily_profit_limit != null) document.getElementById('daily_profit_limit').value = risk.daily_profit_limit;
                    if (risk.daily_total_loss_limit != null) document.getElementById('daily_total_loss_limit').value = risk.daily_total_loss_limit;
                    if (risk.daily_loss_limit_basis != null) document.getElementById('daily_loss_limit_basis').value = risk.daily_loss_limit_basis;
                    if (risk.max_trades_per_day != null) document.getElementById('max_trades_per_day').value = risk.max_trades_per_day;
                    if (risk.max_trades_per_stock_per_day != null) document.getElementById('max_trades_per_stock_per_day').value = risk.max_trades_per_stock_per_day;
                    if (risk.max_positions_count != null) document.getElementById('max_positions_count').value = risk.max_positions_count;
                    if (risk.expand_position_when_few_stocks !== undefined && risk.expand_position_when_few_stocks !== null) {{ const el = document.getElementById('expand_position_when_few_stocks'); if (el) el.checked = !!risk.expand_position_when_few_stocks; }}
                    if (risk.daily_profit_limit_basis != null) document.getElementById('daily_profit_limit_basis').value = risk.daily_profit_limit_basis;
                    if (risk.buy_order_style != null) document.getElementById('buy_order_style').value = risk.buy_order_style;
                    if (risk.sell_order_style != null) document.getElementById('sell_order_style').value = risk.sell_order_style;
                    if (risk.order_retry_count != null) document.getElementById('order_retry_count').value = risk.order_retry_count;
                    if (risk.order_retry_delay_ms != null) document.getElementById('order_retry_delay_ms').value = risk.order_retry_delay_ms;
                    if (risk.order_retry_exponential_backoff != null) {{ const el = document.getElementById('order_retry_exponential_backoff'); if (el) el.checked = !!risk.order_retry_exponential_backoff; }}
                    if (risk.order_retry_base_delay_ms != null) {{ const el = document.getElementById('order_retry_base_delay_ms'); if (el) el.value = risk.order_retry_base_delay_ms; }}
                    if (risk.daily_loss_limit_calendar != null) {{ const el = document.getElementById('daily_loss_limit_calendar'); if (el) el.checked = !!risk.daily_loss_limit_calendar; }}
                    if (risk.daily_profit_limit_calendar != null) {{ const el = document.getElementById('daily_profit_limit_calendar'); if (el) el.checked = !!risk.daily_profit_limit_calendar; }}
                    if (risk.monthly_loss_limit != null) {{ const el = document.getElementById('monthly_loss_limit'); if (el) el.value = risk.monthly_loss_limit; }}
                    if (risk.cumulative_loss_limit != null) {{ const el = document.getElementById('cumulative_loss_limit'); if (el) el.value = risk.cumulative_loss_limit; }}
                    if (risk.order_fallback_to_market != null) document.getElementById('order_fallback_to_market').checked = !!risk.order_fallback_to_market;
                    if (risk.enable_volatility_sizing != null) document.getElementById('enable_volatility_sizing').checked = !!risk.enable_volatility_sizing;
                    if (risk.volatility_lookback_ticks != null) document.getElementById('volatility_lookback_ticks').value = risk.volatility_lookback_ticks;
                    if (risk.volatility_stop_mult != null) document.getElementById('volatility_stop_mult').value = risk.volatility_stop_mult;
                    if (risk.max_loss_per_stock_krw != null) document.getElementById('max_loss_per_stock_krw').value = risk.max_loss_per_stock_krw;
                    if (risk.slippage_bps != null) document.getElementById('slippage_bps').value = risk.slippage_bps;
                    if (risk.volatility_floor_ratio != null) document.getElementById('volatility_floor_ratio').value = risk.volatility_floor_ratio;
                    if (risk.max_intraday_vol_pct != null) document.getElementById('max_intraday_vol_pct').value = risk.max_intraday_vol_pct;
                    if (risk.atr_filter_enabled != null) document.getElementById('atr_filter_enabled').checked = !!risk.atr_filter_enabled;
                    if (risk.atr_period != null) document.getElementById('atr_period').value = risk.atr_period;
                    if (risk.atr_ratio_max_pct != null) document.getElementById('atr_ratio_max_pct').value = risk.atr_ratio_max_pct;
                    if (risk.sap_deviation_filter_enabled != null) document.getElementById('sap_deviation_filter_enabled').checked = !!risk.sap_deviation_filter_enabled;
                    if (risk.sap_deviation_max_pct != null) document.getElementById('sap_deviation_max_pct').value = risk.sap_deviation_max_pct;
                    if (risk.trailing_stop_ratio != null) document.getElementById('trailing_stop_pct').value = (risk.trailing_stop_ratio * 100).toFixed(1);
                    if (risk.trailing_activation_ratio != null) document.getElementById('trailing_activation_pct').value = (risk.trailing_activation_ratio * 100).toFixed(1);
                    if (risk.partial_take_profit_ratio != null) document.getElementById('partial_tp_pct').value = (risk.partial_take_profit_ratio * 100).toFixed(1);
                    if (risk.partial_take_profit_fraction != null) document.getElementById('partial_tp_fraction_pct').value = (risk.partial_take_profit_fraction * 100).toFixed(0);
                    if (risk.min_price_change_ratio != null) document.getElementById('min_price_change_ratio_pct').value = (risk.min_price_change_ratio * 100).toFixed(1);
                    if (risk.use_atr_for_stop_take != null) document.getElementById('use_atr_for_stop_take').checked = !!risk.use_atr_for_stop_take;
                    if (risk.atr_stop_mult != null) document.getElementById('atr_stop_mult').value = risk.atr_stop_mult;
                    if (risk.atr_take_mult != null) document.getElementById('atr_take_mult').value = risk.atr_take_mult;
                    if (risk.atr_lookback_ticks != null) document.getElementById('atr_lookback_ticks').value = risk.atr_lookback_ticks;
                }}
                if (strat) {{
                    var shortMa = strat.short_ma_period;
                    var longMa = strat.long_ma_period;
                    if (shortMa !== undefined && shortMa !== null) document.getElementById('short_ma_period').value = String(Number(shortMa));
                    if (longMa !== undefined && longMa !== null) document.getElementById('long_ma_period').value = String(Number(longMa));
                    if (strat.min_hold_seconds != null) document.getElementById('min_hold_seconds').value = strat.min_hold_seconds;
                    if (strat.buy_window_start_hhmm != null) document.getElementById('buy_window_start_hhmm').value = strat.buy_window_start_hhmm;
                    if (strat.buy_window_end_hhmm != null) document.getElementById('buy_window_end_hhmm').value = strat.buy_window_end_hhmm;
                    if (strat.min_short_ma_slope_ratio != null) document.getElementById('min_short_ma_slope_pct').value = (strat.min_short_ma_slope_ratio * 100).toFixed(3);
                    if (strat.momentum_lookback_ticks != null) document.getElementById('momentum_lookback_ticks').value = strat.momentum_lookback_ticks;
                    if (strat.min_momentum_ratio != null) document.getElementById('min_momentum_pct').value = (strat.min_momentum_ratio * 100).toFixed(2);
                    if (strat.avoid_chase_near_high_enabled != null) document.getElementById('avoid_chase_near_high_enabled').checked = !!strat.avoid_chase_near_high_enabled;
                    if (strat.near_high_lookback_minutes != null) document.getElementById('near_high_lookback_minutes').value = strat.near_high_lookback_minutes;
                    if (strat.avoid_near_high_ratio != null) document.getElementById('avoid_near_high_pct').value = (strat.avoid_near_high_ratio * 100).toFixed(2);
                    if (strat.avoid_near_high_dynamic != null) document.getElementById('avoid_near_high_dynamic').checked = !!strat.avoid_near_high_dynamic;
                    if (strat.avoid_near_high_vs_vol_mult != null) document.getElementById('avoid_near_high_vs_vol_mult').value = strat.avoid_near_high_vs_vol_mult;
                    if (strat.minute_trend_enabled != null) document.getElementById('minute_trend_enabled').checked = !!strat.minute_trend_enabled;
                    if (strat.minute_trend_lookback_bars != null) document.getElementById('minute_trend_lookback_bars').value = strat.minute_trend_lookback_bars;
                    if (strat.minute_trend_min_green_bars != null) document.getElementById('minute_trend_min_green_bars').value = strat.minute_trend_min_green_bars;
                    if (strat.minute_trend_mode != null) document.getElementById('minute_trend_mode').value = strat.minute_trend_mode;
                    if (strat.minute_trend_early_only != null) document.getElementById('minute_trend_early_only').checked = !!strat.minute_trend_early_only;
                    if (strat.entry_confirm_enabled != null) document.getElementById('entry_confirm_enabled').checked = !!strat.entry_confirm_enabled;
                    if (strat.entry_confirm_min_count != null) document.getElementById('entry_confirm_min_count').value = strat.entry_confirm_min_count;
                    if (strat.confirm_breakout_enabled != null) document.getElementById('confirm_breakout_enabled').checked = !!strat.confirm_breakout_enabled;
                    if (strat.breakout_lookback_ticks != null) document.getElementById('breakout_lookback_ticks').value = strat.breakout_lookback_ticks;
                    if (strat.breakout_buffer_ratio != null) document.getElementById('breakout_buffer_pct').value = (strat.breakout_buffer_ratio * 100).toFixed(2);
                    if (strat.confirm_volume_surge_enabled != null) document.getElementById('confirm_volume_surge_enabled').checked = !!strat.confirm_volume_surge_enabled;
                    if (strat.volume_surge_lookback_ticks != null) document.getElementById('volume_surge_lookback_ticks').value = strat.volume_surge_lookback_ticks;
                    if (strat.volume_surge_ratio != null) document.getElementById('volume_surge_ratio').value = strat.volume_surge_ratio;
                    if (strat.confirm_trade_value_surge_enabled != null) document.getElementById('confirm_trade_value_surge_enabled').checked = !!strat.confirm_trade_value_surge_enabled;
                    if (strat.trade_value_surge_lookback_ticks != null) document.getElementById('trade_value_surge_lookback_ticks').value = strat.trade_value_surge_lookback_ticks;
                    if (strat.trade_value_surge_ratio != null) document.getElementById('trade_value_surge_ratio').value = strat.trade_value_surge_ratio;
                    if (strat.vol_norm_lookback_ticks != null) document.getElementById('vol_norm_lookback_ticks').value = strat.vol_norm_lookback_ticks;
                    if (strat.slope_vs_vol_mult != null) document.getElementById('slope_vs_vol_mult').value = strat.slope_vs_vol_mult;
                    if (strat.range_vs_vol_mult != null) document.getElementById('range_vs_vol_mult').value = strat.range_vs_vol_mult;
                    if (strat.enable_morning_regime_split != null) document.getElementById('enable_morning_regime_split').checked = !!strat.enable_morning_regime_split;
                    if (strat.morning_regime_early_end_hhmm != null) document.getElementById('morning_regime_early_end_hhmm').value = strat.morning_regime_early_end_hhmm;
                    if (strat.early_min_short_ma_slope_ratio != null) document.getElementById('early_min_short_ma_slope_pct').value = (strat.early_min_short_ma_slope_ratio * 100).toFixed(3);
                    if (strat.early_momentum_lookback_ticks != null) document.getElementById('early_momentum_lookback_ticks').value = strat.early_momentum_lookback_ticks;
                    if (strat.early_min_momentum_ratio != null) document.getElementById('early_min_momentum_pct').value = (strat.early_min_momentum_ratio * 100).toFixed(2);
                    if (strat.early_buy_confirm_ticks != null) document.getElementById('early_buy_confirm_ticks').value = strat.early_buy_confirm_ticks;
                    if (strat.early_max_spread_ratio != null) document.getElementById('early_max_spread_pct').value = (strat.early_max_spread_ratio * 100).toFixed(2);
                    if (strat.early_range_lookback_ticks != null) document.getElementById('early_range_lookback_ticks').value = strat.early_range_lookback_ticks;
                    if (strat.early_min_range_ratio != null) document.getElementById('early_min_range_pct').value = (strat.early_min_range_ratio * 100).toFixed(2);
                    if (strat.reentry_cooldown_seconds != null) document.getElementById('reentry_cooldown_seconds').value = strat.reentry_cooldown_seconds;
                    if (strat.consecutive_loss_cooldown_enabled != null) document.getElementById('consecutive_loss_cooldown_enabled').checked = !!strat.consecutive_loss_cooldown_enabled;
                    if (strat.consecutive_loss_count_threshold != null) document.getElementById('consecutive_loss_count_threshold').value = strat.consecutive_loss_count_threshold;
                    if (strat.consecutive_loss_cooldown_mult != null) document.getElementById('consecutive_loss_cooldown_mult').value = strat.consecutive_loss_cooldown_mult;
                    if (strat.circuit_breaker_filter_enabled != null) document.getElementById('circuit_breaker_filter_enabled').checked = !!strat.circuit_breaker_filter_enabled;
                    if (strat.circuit_breaker_market != null) document.getElementById('circuit_breaker_market').value = strat.circuit_breaker_market;
                    if (strat.circuit_breaker_threshold_pct != null) document.getElementById('circuit_breaker_threshold_pct').value = strat.circuit_breaker_threshold_pct;
                    if (strat.circuit_breaker_action != null) {{ const el = document.getElementById('circuit_breaker_action'); if (el) el.value = strat.circuit_breaker_action; }}
                    if (strat.sidecar_filter_enabled != null) document.getElementById('sidecar_filter_enabled').checked = !!strat.sidecar_filter_enabled;
                    if (strat.sidecar_market != null) document.getElementById('sidecar_market').value = strat.sidecar_market;
                    if (strat.sidecar_cooling_minutes != null) document.getElementById('sidecar_cooling_minutes').value = strat.sidecar_cooling_minutes;
                    if (strat.sidecar_action != null) {{ const el = document.getElementById('sidecar_action'); if (el) el.value = strat.sidecar_action; }}
                    if (strat.vi_filter_enabled != null) document.getElementById('vi_filter_enabled').checked = !!strat.vi_filter_enabled;
                    if (strat.vi_cooling_minutes != null) document.getElementById('vi_cooling_minutes').value = strat.vi_cooling_minutes;
                    if (strat.index_ma_filter_enabled != null) document.getElementById('index_ma_filter_enabled').checked = !!strat.index_ma_filter_enabled;
                    if (strat.index_ma_code != null) document.getElementById('index_ma_code').value = strat.index_ma_code;
                    if (strat.index_ma_period != null) document.getElementById('index_ma_period').value = strat.index_ma_period;
                    if (strat.advance_ratio_filter_enabled != null) document.getElementById('advance_ratio_filter_enabled').checked = !!strat.advance_ratio_filter_enabled;
                    if (strat.advance_ratio_market != null) document.getElementById('advance_ratio_market').value = strat.advance_ratio_market;
                    if (strat.advance_ratio_min_pct != null) document.getElementById('advance_ratio_min_pct').value = strat.advance_ratio_min_pct;
                    if (strat.trade_value_concentration_filter_enabled != null) document.getElementById('trade_value_concentration_filter_enabled').checked = !!strat.trade_value_concentration_filter_enabled;
                    if (strat.trade_value_concentration_market != null) document.getElementById('trade_value_concentration_market').value = strat.trade_value_concentration_market;
                    if (strat.trade_value_concentration_top_n != null) document.getElementById('trade_value_concentration_top_n').value = strat.trade_value_concentration_top_n;
                    if (strat.trade_value_concentration_denom_n != null) document.getElementById('trade_value_concentration_denom_n').value = strat.trade_value_concentration_denom_n;
                    if (strat.trade_value_concentration_max_pct != null) document.getElementById('trade_value_concentration_max_pct').value = strat.trade_value_concentration_max_pct;
                    if (strat.buy_confirm_ticks != null) document.getElementById('buy_confirm_ticks').value = strat.buy_confirm_ticks;
                    if (strat.enable_time_liquidation != null) document.getElementById('enable_time_liquidation').checked = !!strat.enable_time_liquidation;
                    if (strat.liquidate_after_hhmm != null) document.getElementById('liquidate_after_hhmm').value = strat.liquidate_after_hhmm;
                    if (strat.max_spread_ratio != null) document.getElementById('max_spread_pct').value = (strat.max_spread_ratio * 100).toFixed(2);
                    if (strat.range_lookback_ticks != null) document.getElementById('range_lookback_ticks').value = strat.range_lookback_ticks;
                    if (strat.min_range_ratio != null) document.getElementById('min_range_pct').value = (strat.min_range_ratio * 100).toFixed(2);
                    if (strat.min_volume_ratio_for_entry != null) document.getElementById('min_volume_ratio_for_entry').value = strat.min_volume_ratio_for_entry;
                    if (strat.min_trade_amount_ratio_for_entry != null) document.getElementById('min_trade_amount_ratio_for_entry').value = strat.min_trade_amount_ratio_for_entry;
                    if (strat.skip_buy_first_minutes != null) document.getElementById('skip_buy_first_minutes').value = strat.skip_buy_first_minutes;
                    if (strat.last_minutes_no_buy != null) document.getElementById('last_minutes_no_buy').value = strat.last_minutes_no_buy;
                    if (strat.skip_buy_below_high_pct != null) document.getElementById('skip_buy_below_high_pct').value = (Number(strat.skip_buy_below_high_pct) * 100).toFixed(1);
                    if (strat.relative_strength_filter_enabled != null) document.getElementById('relative_strength_filter_enabled').checked = !!strat.relative_strength_filter_enabled;
                    if (strat.relative_strength_index_code != null) {{ const el = document.getElementById('relative_strength_index_code'); if (el) el.value = strat.relative_strength_index_code; }}
                    if (strat.relative_strength_margin_pct != null) document.getElementById('relative_strength_margin_pct').value = strat.relative_strength_margin_pct;
                    if (strat.advance_ratio_down_market_skip != null) document.getElementById('advance_ratio_down_market_skip').checked = !!strat.advance_ratio_down_market_skip;
                    if (strat.use_sap_revert_entry != null) document.getElementById('use_sap_revert_entry').checked = !!strat.use_sap_revert_entry;
                    if (strat.sap_revert_entry_from_pct != null) document.getElementById('sap_revert_entry_from_pct').value = strat.sap_revert_entry_from_pct;
                    if (strat.sap_revert_entry_to_pct != null) document.getElementById('sap_revert_entry_to_pct').value = strat.sap_revert_entry_to_pct;
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
                    if (stocksel.sort_by != null) document.getElementById('stock_sort_by').value = stocksel.sort_by;
                    if (stocksel.prev_day_rank_pool_size != null) document.getElementById('prev_day_rank_pool_size').value = stocksel.prev_day_rank_pool_size;

                    if (stocksel.market_open_hhmm != null) document.getElementById('market_open_hhmm').value = stocksel.market_open_hhmm;
                    if (stocksel.warmup_minutes != null) document.getElementById('warmup_minutes').value = stocksel.warmup_minutes;
                    if (stocksel.early_strict != null) document.getElementById('early_strict').checked = !!stocksel.early_strict;
                    if (stocksel.early_strict_minutes != null) document.getElementById('early_strict_minutes').value = stocksel.early_strict_minutes;
                    if (stocksel.early_min_volume != null) document.getElementById('early_min_volume').value = stocksel.early_min_volume;
                    if (stocksel.early_min_trade_amount != null) document.getElementById('early_min_trade_amount').value = stocksel.early_min_trade_amount;
                    if (stocksel.kospi_only != null) document.getElementById('kospi_only').checked = !!stocksel.kospi_only;
                    if (stocksel.exclude_drawdown != null) document.getElementById('exclude_drawdown').checked = !!stocksel.exclude_drawdown;
                    if (stocksel.max_drawdown_from_high_ratio != null) document.getElementById('max_drawdown_pct').value = (stocksel.max_drawdown_from_high_ratio * 100).toFixed(1);
                    if (stocksel.drawdown_filter_after_hhmm != null) document.getElementById('drawdown_filter_after_hhmm').value = stocksel.drawdown_filter_after_hhmm;
                }}
                if (oper) {{
                    if (oper.enable_auto_rebalance != null) document.getElementById('enable_auto_rebalance').checked = !!oper.enable_auto_rebalance;
                    if (oper.auto_rebalance_interval_minutes != null) document.getElementById('auto_rebalance_interval_minutes').value = oper.auto_rebalance_interval_minutes;
                    if (oper.enable_performance_auto_recommend != null) document.getElementById('enable_performance_auto_recommend').checked = !!oper.enable_performance_auto_recommend;
                    if (oper.performance_recommend_interval_minutes != null) document.getElementById('performance_recommend_interval_minutes').value = oper.performance_recommend_interval_minutes;
                    if (oper.ws_reconnect_sleep_sec != null) {{ const el = document.getElementById('ws_reconnect_sleep_sec'); if (el) el.value = oper.ws_reconnect_sleep_sec; }}
                    if (oper.emergency_liquidate_disconnect_minutes != null) {{ const el = document.getElementById('emergency_liquidate_disconnect_minutes'); if (el) el.value = oper.emergency_liquidate_disconnect_minutes; }}
                    if (oper.keep_previous_on_empty_selection != null) {{ const el = document.getElementById('keep_previous_on_empty_selection'); if (el) el.checked = !!oper.keep_previous_on_empty_selection; }}
                    if (oper.auto_schedule_enabled != null) {{ const el = document.getElementById('auto_schedule_enabled'); if (el) el.checked = !!oper.auto_schedule_enabled; }}
                    if (oper.auto_start_hhmm != null) {{ const el = document.getElementById('auto_start_hhmm'); if (el) el.value = oper.auto_start_hhmm; }}
                    if (oper.auto_stop_hhmm != null) {{ const el = document.getElementById('auto_stop_hhmm'); if (el) el.value = oper.auto_stop_hhmm; }}
                    if (oper.liquidate_on_auto_stop != null) {{ const el = document.getElementById('liquidate_on_auto_stop'); if (el) el.checked = !!oper.liquidate_on_auto_stop; }}
                    if (oper.auto_schedule_username != null) {{ const el = document.getElementById('auto_schedule_username'); if (el) el.value = oper.auto_schedule_username || ''; }}
                }}
                updateSettingsSummaries();
            }} catch (e) {{
                // ignore
            }}
        }}

        function refreshCustomSlotDropdown() {{
            const sel = document.getElementById('recommended_preset_select');
            const slots = window.__custom_slots || {{}};
            if (sel) {{
                // 디폴트: 커스텀(DB 저장값)
                if (!sel.value) sel.value = 'custom';
                for (let i = 1; i <= 5; i++) {{
                    const opt = sel.querySelector('option[value="' + i + '"]');
                    if (opt) opt.textContent = (slots[i] && slots[i].name) ? slots[i].name : ('커스텀' + i);
                }}
            }}
            toggleSaveSlotButton();
        }}

        async function saveToSelectedSlot() {{
            const v = document.getElementById('recommended_preset_select')?.value || '';
            const slotId = parseInt(v, 10);
            if (slotId < 1 || slotId > 5) {{
                addLog('커스텀 1~5 중 하나를 선택한 뒤 저장하세요', 'warning');
                return;
            }}
            const slots = window.__custom_slots || {{}};
            const name = (slots[String(slotId)] && slots[String(slotId)].name) ? slots[String(slotId)].name : ('커스텀' + slotId);
            try {{
                await updateRiskConfig();
                await updateStrategyConfig();
                await updateStockSelection(true);
                await updateOperationalConfig();
                const response = await fetch('/api/config/custom-slots/save', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
                    body: JSON.stringify({{ slot_id: slotId, name: name }})
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog(data.message || '커스텀 슬롯 저장됨', 'info');
                    await loadUserSettings();
                }} else {{
                    addLog('커스텀 슬롯 저장 실패: ' + (data.message || ''), 'error');
                }}
            }} catch (e) {{
                addLog('커스텀 슬롯 저장 오류: ' + e, 'error');
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
                    daily_total_loss_limit: parseInt(document.getElementById('daily_total_loss_limit').value) || 0,
                    daily_loss_limit_basis: (document.getElementById('daily_loss_limit_basis')?.value || 'realized'),
                    daily_profit_limit_basis: (document.getElementById('daily_profit_limit_basis')?.value || 'total'),
                    buy_order_style: (document.getElementById('buy_order_style')?.value || 'market'),
                    sell_order_style: (document.getElementById('sell_order_style')?.value || 'market'),
                    order_retry_count: parseInt(document.getElementById('order_retry_count')?.value) || 0,
                    order_retry_delay_ms: parseInt(document.getElementById('order_retry_delay_ms')?.value) || 300,
                    order_retry_exponential_backoff: !!document.getElementById('order_retry_exponential_backoff')?.checked,
                    order_retry_base_delay_ms: parseInt(document.getElementById('order_retry_base_delay_ms')?.value) || 1000,
                    daily_loss_limit_calendar: !!document.getElementById('daily_loss_limit_calendar')?.checked,
                    daily_profit_limit_calendar: !!document.getElementById('daily_profit_limit_calendar')?.checked,
                    monthly_loss_limit: parseInt(document.getElementById('monthly_loss_limit')?.value) || 0,
                    cumulative_loss_limit: parseInt(document.getElementById('cumulative_loss_limit')?.value) || 0,
                    order_fallback_to_market: !!document.getElementById('order_fallback_to_market')?.checked,
                    enable_volatility_sizing: !!document.getElementById('enable_volatility_sizing')?.checked,
                    volatility_lookback_ticks: parseInt(document.getElementById('volatility_lookback_ticks')?.value) || 20,
                    volatility_stop_mult: parseFloat(document.getElementById('volatility_stop_mult')?.value) || 1.0,
                    max_loss_per_stock_krw: parseInt(document.getElementById('max_loss_per_stock_krw')?.value) || 0,
                    slippage_bps: parseInt(document.getElementById('slippage_bps')?.value) || 0,
                    volatility_floor_ratio: parseFloat(document.getElementById('volatility_floor_ratio')?.value) || 0.005,
                    max_intraday_vol_pct: parseFloat(document.getElementById('max_intraday_vol_pct')?.value) || 0,
                    atr_filter_enabled: !!document.getElementById('atr_filter_enabled')?.checked,
                    atr_period: parseInt(document.getElementById('atr_period')?.value) || 14,
                    atr_ratio_max_pct: parseFloat(document.getElementById('atr_ratio_max_pct')?.value) || 0,
                    sap_deviation_filter_enabled: !!document.getElementById('sap_deviation_filter_enabled')?.checked,
                    sap_deviation_max_pct: parseFloat(document.getElementById('sap_deviation_max_pct')?.value) || 3,
                    max_trades_per_day: parseInt(document.getElementById('max_trades_per_day')?.value) || 12,
                    max_trades_per_stock_per_day: parseInt(document.getElementById('max_trades_per_stock_per_day')?.value) || 0,
                    max_positions_count: parseInt(document.getElementById('max_positions_count')?.value) || 0,
                    expand_position_when_few_stocks: !!document.getElementById('expand_position_when_few_stocks')?.checked,
                    max_position_size_ratio: 0.1,
                    trailing_stop_ratio: (parseFloat(document.getElementById('trailing_stop_pct').value) || 0) / 100,
                    trailing_activation_ratio: (parseFloat(document.getElementById('trailing_activation_pct').value) || 0) / 100,
                    partial_take_profit_ratio: (parseFloat(document.getElementById('partial_tp_pct').value) || 0) / 100,
                    partial_take_profit_fraction: (parseFloat(document.getElementById('partial_tp_fraction_pct').value) || 0) / 100,
                    min_price_change_ratio: (function(){{ var el = document.getElementById('min_price_change_ratio_pct'); if (!el) return 0; var v = parseFloat(el.value); return Number.isNaN(v) ? 0 : v / 100; }})(),
                    use_atr_for_stop_take: !!document.getElementById('use_atr_for_stop_take')?.checked,
                    atr_stop_mult: parseFloat(document.getElementById('atr_stop_mult')?.value) || 1.5,
                    atr_take_mult: parseFloat(document.getElementById('atr_take_mult')?.value) || 2,
                    atr_lookback_ticks: parseInt(document.getElementById('atr_lookback_ticks')?.value) || 20,
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
                    min_hold_seconds: parseInt(document.getElementById('min_hold_seconds').value) || 0,
                    buy_window_start_hhmm: (document.getElementById('buy_window_start_hhmm').value || '09:05').trim(),
                    buy_window_end_hhmm: (document.getElementById('buy_window_end_hhmm').value || '11:30').trim(),
                    min_short_ma_slope_ratio: (parseFloat(document.getElementById('min_short_ma_slope_pct').value) || 0) / 100,
                    momentum_lookback_ticks: parseInt(document.getElementById('momentum_lookback_ticks').value) || 0,
                    min_momentum_ratio: (parseFloat(document.getElementById('min_momentum_pct').value) || 0) / 100,
                    avoid_chase_near_high_enabled: !!document.getElementById('avoid_chase_near_high_enabled').checked,
                    near_high_lookback_minutes: parseInt(document.getElementById('near_high_lookback_minutes').value) || 2,
                    avoid_near_high_ratio: (parseFloat(document.getElementById('avoid_near_high_pct').value) || 0) / 100,
                    avoid_near_high_dynamic: !!document.getElementById('avoid_near_high_dynamic').checked,
                    avoid_near_high_vs_vol_mult: parseFloat(document.getElementById('avoid_near_high_vs_vol_mult').value) || 0,
                    minute_trend_enabled: !!document.getElementById('minute_trend_enabled').checked,
                    minute_trend_lookback_bars: parseInt(document.getElementById('minute_trend_lookback_bars').value) || 2,
                    minute_trend_min_green_bars: parseInt(document.getElementById('minute_trend_min_green_bars').value) || 2,
                    minute_trend_mode: (document.getElementById('minute_trend_mode')?.value || 'green'),
                    minute_trend_early_only: !!document.getElementById('minute_trend_early_only')?.checked,
                    entry_confirm_enabled: !!document.getElementById('entry_confirm_enabled').checked,
                    entry_confirm_min_count: parseInt(document.getElementById('entry_confirm_min_count').value) || 1,
                    confirm_breakout_enabled: !!document.getElementById('confirm_breakout_enabled').checked,
                    breakout_lookback_ticks: parseInt(document.getElementById('breakout_lookback_ticks').value) || 20,
                    breakout_buffer_ratio: (parseFloat(document.getElementById('breakout_buffer_pct').value) || 0) / 100,
                    confirm_volume_surge_enabled: !!document.getElementById('confirm_volume_surge_enabled').checked,
                    volume_surge_lookback_ticks: parseInt(document.getElementById('volume_surge_lookback_ticks').value) || 20,
                    volume_surge_ratio: parseFloat(document.getElementById('volume_surge_ratio').value) || 2.0,
                    confirm_trade_value_surge_enabled: !!document.getElementById('confirm_trade_value_surge_enabled').checked,
                    trade_value_surge_lookback_ticks: parseInt(document.getElementById('trade_value_surge_lookback_ticks').value) || 20,
                    trade_value_surge_ratio: parseFloat(document.getElementById('trade_value_surge_ratio').value) || 2.0,
                    vol_norm_lookback_ticks: parseInt(document.getElementById('vol_norm_lookback_ticks').value) || 20,
                    slope_vs_vol_mult: parseFloat(document.getElementById('slope_vs_vol_mult').value) || 0,
                    range_vs_vol_mult: parseFloat(document.getElementById('range_vs_vol_mult').value) || 0,
                    enable_morning_regime_split: !!document.getElementById('enable_morning_regime_split').checked,
                    morning_regime_early_end_hhmm: (document.getElementById('morning_regime_early_end_hhmm').value || '09:10').trim(),
                    early_min_short_ma_slope_ratio: (parseFloat(document.getElementById('early_min_short_ma_slope_pct').value) || 0) / 100,
                    early_momentum_lookback_ticks: parseInt(document.getElementById('early_momentum_lookback_ticks').value) || 0,
                    early_min_momentum_ratio: (parseFloat(document.getElementById('early_min_momentum_pct').value) || 0) / 100,
                    early_buy_confirm_ticks: parseInt(document.getElementById('early_buy_confirm_ticks').value) || 1,
                    early_max_spread_ratio: (parseFloat(document.getElementById('early_max_spread_pct').value) || 0) / 100,
                    early_range_lookback_ticks: parseInt(document.getElementById('early_range_lookback_ticks').value) || 0,
                    early_min_range_ratio: (parseFloat(document.getElementById('early_min_range_pct').value) || 0) / 100,
                    reentry_cooldown_seconds: parseInt(document.getElementById('reentry_cooldown_seconds').value) || 240,
                    consecutive_loss_cooldown_enabled: !!document.getElementById('consecutive_loss_cooldown_enabled').checked,
                    consecutive_loss_count_threshold: parseInt(document.getElementById('consecutive_loss_count_threshold').value) || 2,
                    consecutive_loss_cooldown_mult: parseFloat(document.getElementById('consecutive_loss_cooldown_mult').value) || 2,
                    circuit_breaker_filter_enabled: !!document.getElementById('circuit_breaker_filter_enabled').checked,
                    circuit_breaker_market: (document.getElementById('circuit_breaker_market')?.value || '0001'),
                    circuit_breaker_threshold_pct: parseFloat(document.getElementById('circuit_breaker_threshold_pct').value) || -7,
                    circuit_breaker_action: (document.getElementById('circuit_breaker_action')?.value || 'skip_buy_only'),
                    sidecar_filter_enabled: !!document.getElementById('sidecar_filter_enabled').checked,
                    sidecar_market: (document.getElementById('sidecar_market')?.value || '0001'),
                    sidecar_cooling_minutes: parseInt(document.getElementById('sidecar_cooling_minutes').value) || 5,
                    sidecar_action: (document.getElementById('sidecar_action')?.value || 'skip_buy_only'),
                    vi_filter_enabled: !!document.getElementById('vi_filter_enabled').checked,
                    vi_cooling_minutes: parseInt(document.getElementById('vi_cooling_minutes').value) || 5,
                    index_ma_filter_enabled: !!document.getElementById('index_ma_filter_enabled').checked,
                    index_ma_code: (document.getElementById('index_ma_code')?.value || '1001'),
                    index_ma_period: parseInt(document.getElementById('index_ma_period').value) || 20,
                    advance_ratio_filter_enabled: !!document.getElementById('advance_ratio_filter_enabled').checked,
                    advance_ratio_market: (document.getElementById('advance_ratio_market')?.value || '1001'),
                    advance_ratio_min_pct: parseFloat(document.getElementById('advance_ratio_min_pct').value) || 35,
                    trade_value_concentration_filter_enabled: !!document.getElementById('trade_value_concentration_filter_enabled').checked,
                    trade_value_concentration_market: (document.getElementById('trade_value_concentration_market')?.value || '1001'),
                    trade_value_concentration_top_n: parseInt(document.getElementById('trade_value_concentration_top_n').value) || 10,
                    trade_value_concentration_denom_n: parseInt(document.getElementById('trade_value_concentration_denom_n').value) || 30,
                    trade_value_concentration_max_pct: parseFloat(document.getElementById('trade_value_concentration_max_pct').value) || 45,
                    buy_confirm_ticks: parseInt(document.getElementById('buy_confirm_ticks').value) || 1,
                    enable_time_liquidation: !!document.getElementById('enable_time_liquidation').checked,
                    liquidate_after_hhmm: (document.getElementById('liquidate_after_hhmm').value || '11:55').trim(),
                    max_spread_ratio: (parseFloat(document.getElementById('max_spread_pct').value) || 0) / 100,
                    range_lookback_ticks: parseInt(document.getElementById('range_lookback_ticks').value) || 0,
                    min_range_ratio: (parseFloat(document.getElementById('min_range_pct').value) || 0) / 100,
                    min_volume_ratio_for_entry: parseFloat(document.getElementById('min_volume_ratio_for_entry')?.value) || 0,
                    min_trade_amount_ratio_for_entry: parseFloat(document.getElementById('min_trade_amount_ratio_for_entry')?.value) || 0,
                    skip_buy_first_minutes: parseInt(document.getElementById('skip_buy_first_minutes')?.value) || 0,
                    last_minutes_no_buy: parseInt(document.getElementById('last_minutes_no_buy')?.value) || 0,
                    skip_buy_below_high_pct: (parseFloat(document.getElementById('skip_buy_below_high_pct')?.value) || 0) / 100,
                    relative_strength_filter_enabled: !!document.getElementById('relative_strength_filter_enabled')?.checked,
                    relative_strength_index_code: (document.getElementById('relative_strength_index_code')?.value || '0001').trim(),
                    relative_strength_margin_pct: parseFloat(document.getElementById('relative_strength_margin_pct')?.value) || 0,
                    advance_ratio_down_market_skip: !!document.getElementById('advance_ratio_down_market_skip')?.checked,
                    use_sap_revert_entry: !!document.getElementById('use_sap_revert_entry')?.checked,
                    // 주의: JS에서 0은 falsy라 `||`로 처리하면 기본값(-0.5)으로 덮어써짐.
                    // 0도 유효한 설정값이므로 Number.isFinite로만 보정.
                    sap_revert_entry_from_pct: (() => {{ const v = parseFloat(document.getElementById('sap_revert_entry_from_pct')?.value); return Number.isFinite(v) ? v : -1.5; }})(),
                    sap_revert_entry_to_pct: (() => {{ const v = parseFloat(document.getElementById('sap_revert_entry_to_pct')?.value); return Number.isFinite(v) ? v : -0.5; }})(),
                }};
                const response = await fetch('/api/config/strategy', {{
                    method: 'POST',
                    credentials: 'include',
                    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
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

        async function applyStrategyPreset(name) {{
            try {{
                const n = (name || '').toString();
                if (!n) return;

                // MA-only 프리셋: 고급값은 유지하고 MA만 변경
                if (n === 'ma_fast_3_10' || n === 'ma_safe_5_20' || n === 'ma_mid_8_21') {{
                    if (n === 'ma_fast_3_10') {{
                        document.getElementById('short_ma_period').value = 3;
                        document.getElementById('long_ma_period').value = 10;
                    }} else if (n === 'ma_safe_5_20') {{
                        document.getElementById('short_ma_period').value = 5;
                        document.getElementById('long_ma_period').value = 20;
                    }} else {{
                        document.getElementById('short_ma_period').value = 8;
                        document.getElementById('long_ma_period').value = 21;
                    }}
                    addLog('MA 프리셋 적용: ' + n, 'info');
                    await updateStrategyConfig();
                    updateSettingsSummaries();
                    return;
                }}

                // 공통: 기본값(고급 포함)
                document.getElementById('enable_time_liquidation').checked = true;
                document.getElementById('liquidate_after_hhmm').value = '11:55';
                document.getElementById('reentry_cooldown_seconds').value = 180;
                document.getElementById('buy_window_start_hhmm').value = '09:05';
                document.getElementById('buy_window_end_hhmm').value = '11:30';

                document.getElementById('vol_norm_lookback_ticks').value = 20;
                document.getElementById('slope_vs_vol_mult').value = 0;
                document.getElementById('range_vs_vol_mult').value = 0;

                document.getElementById('enable_morning_regime_split').checked = true;
                document.getElementById('morning_regime_early_end_hhmm').value = '09:10';

                // 진입 직전(피크 추격 방지)
                document.getElementById('avoid_chase_near_high_enabled').checked = true;
                document.getElementById('near_high_lookback_minutes').value = 2;
                document.getElementById('avoid_near_high_pct').value = 0.30;
                document.getElementById('avoid_near_high_dynamic').checked = true;
                document.getElementById('avoid_near_high_vs_vol_mult').value = 3.0;

                // 보강(2단)
                document.getElementById('entry_confirm_enabled').checked = true;
                document.getElementById('entry_confirm_min_count').value = 1;
                document.getElementById('confirm_breakout_enabled').checked = true;
                document.getElementById('breakout_lookback_ticks').value = 20;
                document.getElementById('breakout_buffer_pct').value = 0.10;
                document.getElementById('confirm_volume_surge_enabled').checked = false;
                document.getElementById('volume_surge_lookback_ticks').value = 20;
                document.getElementById('volume_surge_ratio').value = 2.0;
                document.getElementById('confirm_trade_value_surge_enabled').checked = true;
                document.getElementById('trade_value_surge_lookback_ticks').value = 20;
                document.getElementById('trade_value_surge_ratio').value = 2.0;

                // 분봉 추세(초반만)
                document.getElementById('minute_trend_enabled').checked = true;
                document.getElementById('minute_trend_early_only').checked = true;
                document.getElementById('minute_trend_lookback_bars').value = 2;
                document.getElementById('minute_trend_min_green_bars').value = 2;
                document.getElementById('minute_trend_mode').value = 'hh_hl';

                if (n === 'scalp_light') {{
                    // 가벼움: 진입 기회↑
                    document.getElementById('short_ma_period').value = 3;
                    document.getElementById('long_ma_period').value = 10;
                    document.getElementById('min_short_ma_slope_pct').value = 0.008;
                    document.getElementById('momentum_lookback_ticks').value = 6;
                    document.getElementById('min_momentum_pct').value = 0.15;
                    document.getElementById('buy_confirm_ticks').value = 1;
                    document.getElementById('max_spread_pct').value = 0.30;
                    document.getElementById('range_lookback_ticks').value = 40;
                    document.getElementById('min_range_pct').value = 0.20;

                    document.getElementById('early_min_short_ma_slope_pct').value = 0.015;
                    document.getElementById('early_momentum_lookback_ticks').value = 6;
                    document.getElementById('early_min_momentum_pct').value = 0.20;
                    document.getElementById('early_buy_confirm_ticks').value = 1;
                    document.getElementById('early_max_spread_pct').value = 0.35;
                    document.getElementById('early_range_lookback_ticks').value = 40;
                    document.getElementById('early_min_range_pct').value = 0.25;
                }} else if (n === 'scalp_morning_strict') {{
                    // 엄격: 노이즈↓
                    document.getElementById('short_ma_period').value = 3;
                    document.getElementById('long_ma_period').value = 12;
                    document.getElementById('min_short_ma_slope_pct').value = 0.015;
                    document.getElementById('momentum_lookback_ticks').value = 8;
                    document.getElementById('min_momentum_pct').value = 0.25;
                    document.getElementById('buy_confirm_ticks').value = 2;
                    document.getElementById('max_spread_pct').value = 0.18;
                    document.getElementById('range_lookback_ticks').value = 70;
                    document.getElementById('min_range_pct').value = 0.28;

                    document.getElementById('early_min_short_ma_slope_pct').value = 0.030;
                    document.getElementById('early_momentum_lookback_ticks').value = 8;
                    document.getElementById('early_min_momentum_pct').value = 0.40;
                    document.getElementById('early_buy_confirm_ticks').value = 2;
                    document.getElementById('early_max_spread_pct').value = 0.22;
                    document.getElementById('early_range_lookback_ticks').value = 70;
                    document.getElementById('early_min_range_pct').value = 0.35;

                    // 보강조건 2개 이상
                    document.getElementById('entry_confirm_min_count').value = 2;
                    document.getElementById('confirm_volume_surge_enabled').checked = true;
                }} else {{
                    // 밸런스
                    document.getElementById('short_ma_period').value = 3;
                    document.getElementById('long_ma_period').value = 10;
                    document.getElementById('min_short_ma_slope_pct').value = 0.010;
                    document.getElementById('momentum_lookback_ticks').value = 8;
                    document.getElementById('min_momentum_pct').value = 0.20;
                    document.getElementById('buy_confirm_ticks').value = 2;
                    document.getElementById('max_spread_pct').value = 0.20;
                    document.getElementById('range_lookback_ticks').value = 60;
                    document.getElementById('min_range_pct').value = 0.25;

                    document.getElementById('early_min_short_ma_slope_pct').value = 0.020;
                    document.getElementById('early_momentum_lookback_ticks').value = 8;
                    document.getElementById('early_min_momentum_pct').value = 0.30;
                    document.getElementById('early_buy_confirm_ticks').value = 2;
                    document.getElementById('early_max_spread_pct').value = 0.25;
                    document.getElementById('early_range_lookback_ticks').value = 60;
                    document.getElementById('early_min_range_pct').value = 0.30;
                }}

                addLog('전략 프리셋 적용: ' + n, 'info');
                await updateStrategyConfig();
                updateSettingsSummaries();
            }} catch (e) {{
                addLog('전략 프리셋 적용 오류: ' + e, 'error');
            }}
        }}

        async function onStrategyPresetChange() {{
            try {{
                const sel = document.getElementById('strategy_preset_select');
                if (!sel) return;
                const v = (sel.value || '').toString();
                if (!v) return;
                await applyStrategyPreset(v);
                // 적용 후에는 "직접 설정"으로 되돌려 혼선 방지
                sel.value = '';
            }} catch (e) {{
                addLog('전략 프리셋 변경 오류: ' + e, 'error');
            }}
        }}

        async function applyRecommendedPreset() {{
            const presetId = document.getElementById('recommended_preset_select')?.value || '';
            if (!presetId) {{
                addLog('프리셋을 선택하세요', 'warning');
                return;
            }}
            if (presetId === 'custom') {{
                addLog('커스텀: DB(quant_trading_user_settings) 저장값 불러오는 중...', 'info');
                await loadUserSettings();
                addLog('커스텀(DB 저장값) 적용 완료. 리스크·전략·종목선정·운영 설정이 DB 값으로 세팅되었습니다.', 'info');
                return;
            }}
            if (presetId === '1' || presetId === '2' || presetId === '3' || presetId === '4' || presetId === '5') {{
                const slotId = parseInt(presetId, 10);
                addLog('커스텀 슬롯 ' + slotId + ' 불러오는 중...', 'info');
                const r = await fetch('/api/config/custom-slots/load', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
                    body: JSON.stringify({{ slot_id: slotId }})
                }});
                const data = await r.json();
                if (data.success) {{
                    await loadUserSettings();
                    addLog(data.message || ('커스텀' + slotId + ' 적용 완료'), 'info');
                }} else {{
                    addLog(data.message || ('슬롯 ' + slotId + ' 불러오기 실패'), 'warning');
                }}
                return;
            }}
            await applyScalpPresetWithOptions(presetId);
        }}

        function toggleSaveSlotButton() {{
            const v = document.getElementById('recommended_preset_select')?.value || '';
            const btn = document.getElementById('btn_save_to_slot');
            if (btn) btn.style.display = (v === '1' || v === '2' || v === '3' || v === '4' || v === '5') ? 'inline-block' : 'none';
        }}

        async function applyScalpPresetWithOptions(variant) {{
            const overrides = {{
                buy_window_end_hhmm: '11:30',
                liquidate_after_hhmm: '11:55',
                stop_loss: 0.8,
                take_profit: 1.8,
                daily_loss_limit: 50000,
                daily_profit_limit: 50000,
                max_trades_per_day: 12,
                max_positions_count: 2,
                last_minutes_no_buy: 10,
                name: '오전 단타'
            }};
            if (variant === 'scalp_fullday') {{
                overrides.buy_window_end_hhmm = '15:20';
                overrides.liquidate_after_hhmm = '15:25';
                overrides.last_minutes_no_buy = 15;
                overrides.name = '전일 단타';
            }} else if (variant === 'scalp_conservative') {{
                overrides.stop_loss = 0.6;
                overrides.take_profit = 1.2;
                overrides.daily_loss_limit = 30000;
                overrides.daily_profit_limit = 30000;
                overrides.max_trades_per_day = 3;
                overrides.max_positions_count = 1;
                overrides.name = '보수적 단타';
            }} else if (variant === 'scalp_aggressive') {{
                overrides.stop_loss = 1.0;
                overrides.take_profit = 2.5;
                overrides.daily_loss_limit = 80000;
                overrides.daily_profit_limit = 80000;
                overrides.max_trades_per_day = 12;
                overrides.max_positions_count = 3;
                overrides.name = '공격적 단타';
            }}
            try {{
                addLog(overrides.name + ' 프리셋 적용 중...', 'info');

                // 리스크: Position size = risk / stop distance, dailyProfit ≥ dailyLoss, 슬리피지 20bps. 직전틱 1%는 급등만 허용되므로 단타 프리셋은 0(미적용)
                document.getElementById('max_trade_amount').value = 1000000;
                document.getElementById('min_order_quantity').value = 2;
                const minPriceChgEl = document.getElementById('min_price_change_ratio_pct');
                if (minPriceChgEl) minPriceChgEl.value = 0;
                document.getElementById('stop_loss').value = overrides.stop_loss;
                document.getElementById('take_profit').value = overrides.take_profit;
                document.getElementById('daily_loss_limit').value = overrides.daily_loss_limit;
                document.getElementById('daily_profit_limit').value = overrides.daily_profit_limit;
                document.getElementById('max_loss_per_stock_krw').value = 50000;
                document.getElementById('partial_tp_pct').value = 0.8;
                document.getElementById('partial_tp_fraction_pct').value = 50;
                document.getElementById('trailing_stop_pct').value = 0.5;
                document.getElementById('trailing_activation_pct').value = 0.8;
                document.getElementById('max_intraday_vol_pct').value = 3;
                document.getElementById('slippage_bps').value = 20;
                document.getElementById('order_retry_delay_ms').value = 300;
                // 변동성 필터: ATR(분봉) / SAP(세션 평균가) 이탈 — 단타에서 과열·과매도 구간 진입 억제
                document.getElementById('atr_filter_enabled').checked = true;
                document.getElementById('atr_period').value = 14;
                document.getElementById('atr_ratio_max_pct').value = 2.5;
                document.getElementById('sap_deviation_filter_enabled').checked = true;
                document.getElementById('sap_deviation_max_pct').value = 3;
                // 단타: 일일 거래 횟수·동시 보유 종목 상한, 변동성 배수 손절/익절, 변동성 사이징
                document.getElementById('max_trades_per_day').value = overrides.max_trades_per_day;
                document.getElementById('max_positions_count').value = overrides.max_positions_count;
                document.getElementById('use_atr_for_stop_take').checked = true;
                document.getElementById('atr_stop_mult').value = 1.5;
                document.getElementById('atr_take_mult').value = 2;
                document.getElementById('atr_lookback_ticks').value = 20;
                document.getElementById('enable_volatility_sizing').checked = true;
                document.getElementById('volatility_lookback_ticks').value = 20;
                document.getElementById('volatility_stop_mult').value = 1.0;
                await updateRiskConfig();

                // 전략(빠른 MA + 신규 매수 시간 제한 + 진입 후 최소 보유로 즉시 매도 방지)
                document.getElementById('short_ma_period').value = 3;
                document.getElementById('long_ma_period').value = 10;
                const minHoldEl = document.getElementById('min_hold_seconds');
                if (minHoldEl) minHoldEl.value = 30;
                document.getElementById('buy_window_start_hhmm').value = '09:05';
                document.getElementById('buy_window_end_hhmm').value = overrides.buy_window_end_hhmm;
                document.getElementById('min_short_ma_slope_pct').value = 0.010;
                document.getElementById('momentum_lookback_ticks').value = 8;
                document.getElementById('min_momentum_pct').value = 0.20;
                document.getElementById('avoid_chase_near_high_enabled').checked = true;
                document.getElementById('near_high_lookback_minutes').value = 2;
                document.getElementById('avoid_near_high_pct').value = 0.30;
                document.getElementById('avoid_near_high_dynamic').checked = true;
                document.getElementById('avoid_near_high_vs_vol_mult').value = 3.0;
                // 초반 레짐(09:00~09:10)에서만 분봉 추세 필터 ON (노이즈/피크 추격 완화)
                document.getElementById('minute_trend_enabled').checked = true;
                document.getElementById('minute_trend_lookback_bars').value = 2;
                document.getElementById('minute_trend_min_green_bars').value = 2;
                document.getElementById('minute_trend_mode').value = 'hh_hl';
                document.getElementById('minute_trend_early_only').checked = true;
                document.getElementById('entry_confirm_enabled').checked = true;
                document.getElementById('entry_confirm_min_count').value = 1;
                document.getElementById('confirm_breakout_enabled').checked = true;
                document.getElementById('breakout_lookback_ticks').value = 20;
                document.getElementById('breakout_buffer_pct').value = 0.10;
                document.getElementById('confirm_volume_surge_enabled').checked = false;
                document.getElementById('volume_surge_lookback_ticks').value = 20;
                document.getElementById('volume_surge_ratio').value = 2.0;
                document.getElementById('confirm_trade_value_surge_enabled').checked = true;
                document.getElementById('trade_value_surge_lookback_ticks').value = 20;
                document.getElementById('trade_value_surge_ratio').value = 2.0;
                document.getElementById('vol_norm_lookback_ticks').value = 20;
                document.getElementById('slope_vs_vol_mult').value = 0;
                document.getElementById('range_vs_vol_mult').value = 0;
                document.getElementById('enable_morning_regime_split').checked = true;
                document.getElementById('morning_regime_early_end_hhmm').value = '09:10';
                document.getElementById('early_min_short_ma_slope_pct').value = 0.020;
                document.getElementById('early_momentum_lookback_ticks').value = 8;
                document.getElementById('early_min_momentum_pct').value = 0.30;
                document.getElementById('early_buy_confirm_ticks').value = 2;
                document.getElementById('early_max_spread_pct').value = 0.25;
                document.getElementById('early_range_lookback_ticks').value = 60;
                document.getElementById('early_min_range_pct').value = 0.30;
                document.getElementById('reentry_cooldown_seconds').value = 180;
                document.getElementById('buy_confirm_ticks').value = 2;
                // 연속 손실 시 쿨다운 확대 (2연패 시 재진입 대기 2배)
                document.getElementById('consecutive_loss_cooldown_enabled').checked = true;
                document.getElementById('consecutive_loss_count_threshold').value = 2;
                document.getElementById('consecutive_loss_cooldown_mult').value = 2;
                // 시장 레짐: 지수 MA + 상승 비율 (하락장 진입 억제)
                document.getElementById('index_ma_filter_enabled').checked = true;
                document.getElementById('index_ma_code').value = '1001';
                document.getElementById('index_ma_period').value = 20;
                document.getElementById('advance_ratio_filter_enabled').checked = true;
                document.getElementById('advance_ratio_market').value = '1001';
                document.getElementById('advance_ratio_min_pct').value = 35;
                document.getElementById('advance_ratio_down_market_skip').checked = true;
                // 서킷/사이드카/VI: 급락·변동 시 매수 스킵 (단타 보호)
                document.getElementById('circuit_breaker_filter_enabled').checked = true;
                document.getElementById('circuit_breaker_market').value = '0001';
                document.getElementById('circuit_breaker_threshold_pct').value = -7;
                document.getElementById('sidecar_filter_enabled').checked = true;
                document.getElementById('vi_filter_enabled').checked = true;
                // 시간대: 장 초반 N분 스킵, 마감 N분 전 신규 매수 스킵
                document.getElementById('skip_buy_first_minutes').value = 5;
                document.getElementById('last_minutes_no_buy').value = overrides.last_minutes_no_buy;
                // 스프레드/횡보장 필터 기본값 튜닝(너무 타이트하면 매수 자체가 안 걸릴 수 있음)
                document.getElementById('max_spread_pct').value = 0.20;
                document.getElementById('range_lookback_ticks').value = 60;
                document.getElementById('min_range_pct').value = 0.25;
                document.getElementById('enable_time_liquidation').checked = true;
                document.getElementById('liquidate_after_hhmm').value = overrides.liquidate_after_hhmm;
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
                    addLog(overrides.name + ' 프리셋 적용 완료', 'info');
                }} else {{
                    addLog(overrides.name + ' 프리셋 적용 완료(재선정 실패): ' + ((res && res.message) ? res.message : '알 수 없는 오류'), 'warning');
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
                    sort_by: (document.getElementById('stock_sort_by')?.value || 'change'),
                    prev_day_rank_pool_size: parseInt(document.getElementById('prev_day_rank_pool_size')?.value) || 80,

                    market_open_hhmm: (document.getElementById('market_open_hhmm').value || '09:00').trim(),
                    warmup_minutes: parseInt(document.getElementById('warmup_minutes').value) || 0,
                    early_strict: !!document.getElementById('early_strict').checked,
                    early_strict_minutes: parseInt(document.getElementById('early_strict_minutes').value) || 30,
                    early_min_volume: parseInt(document.getElementById('early_min_volume').value) || 0,
                    early_min_trade_amount: parseInt(document.getElementById('early_min_trade_amount').value) || 0,
                    kospi_only: !!document.getElementById('kospi_only').checked,
                    exclude_drawdown: !!document.getElementById('exclude_drawdown').checked,
                    max_drawdown_from_high_ratio: (parseFloat(document.getElementById('max_drawdown_pct').value) || 12) / 100,
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

        function applyAutoRefreshSettings(initial = false) {{
            const enabledEl = document.getElementById('auto_refresh_enabled');
            const intervalEl = document.getElementById('auto_refresh_interval');
            if (!enabledEl || !intervalEl) return;
            if (autoRefreshTimer) {{
                clearInterval(autoRefreshTimer);
                autoRefreshTimer = null;
            }}
            if (!enabledEl.checked) return;
            const ms = parseInt(intervalEl.value, 10) || 0;
            if (ms <= 0) return;
            autoRefreshTimer = setInterval(refreshData, ms);
            if (!initial) {{
                refreshData();
            }}
        }}

        function onChangeAutoRefresh() {{
            applyAutoRefreshSettings(false);
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
                    if (preset.kospi_only != null) document.getElementById('kospi_only').checked = !!preset.kospi_only;
                    if (preset.exclude_drawdown != null) document.getElementById('exclude_drawdown').checked = !!preset.exclude_drawdown;
                    if (preset.max_drawdown_from_high_ratio != null) document.getElementById('max_drawdown_pct').value = (preset.max_drawdown_from_high_ratio * 100).toFixed(1);
                    if (preset.drawdown_filter_after_hhmm != null) document.getElementById('drawdown_filter_after_hhmm').value = preset.drawdown_filter_after_hhmm;
                    addLog(`프리셋 로드: ${{preset.name}}`, 'info');
                }}
            }} catch (error) {{
                addLog('프리셋 로드 오류: ' + error, 'error');
            }}
        }}

        async function updateOperationalConfig() {{
            try {{
                const body = {{
                    enable_auto_rebalance: !!document.getElementById('enable_auto_rebalance').checked,
                    auto_rebalance_interval_minutes: parseInt(document.getElementById('auto_rebalance_interval_minutes').value) || 30,
                    enable_performance_auto_recommend: !!document.getElementById('enable_performance_auto_recommend').checked,
                    performance_recommend_interval_minutes: parseInt(document.getElementById('performance_recommend_interval_minutes').value) || 5,
                    ws_reconnect_sleep_sec: parseInt(document.getElementById('ws_reconnect_sleep_sec').value) || 5,
                    emergency_liquidate_disconnect_minutes: parseInt(document.getElementById('emergency_liquidate_disconnect_minutes').value) || 0,
                    keep_previous_on_empty_selection: !!document.getElementById('keep_previous_on_empty_selection').checked,
                    auto_schedule_enabled: !!document.getElementById('auto_schedule_enabled').checked,
                    auto_start_hhmm: (document.getElementById('auto_start_hhmm').value || '09:30').trim().slice(0, 5),
                    auto_stop_hhmm: (document.getElementById('auto_stop_hhmm').value || '12:00').trim().slice(0, 5),
                    liquidate_on_auto_stop: !!document.getElementById('liquidate_on_auto_stop').checked,
                    auto_schedule_username: (document.getElementById('auto_schedule_username').value || '').trim()
                }};
                const response = await fetch('/api/config/operational', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
                    body: JSON.stringify(body)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog('운영 옵션 저장됨', 'info');
                }} else {{
                    addLog('운영 옵션 저장 실패: ' + (data.message || '알 수 없음'), 'error');
                }}
            }} catch (error) {{
                addLog('운영 옵션 저장 오류: ' + error, 'error');
            }}
        }}

        async function selectStocks(silent = false) {{
            try {{
                if (window._systemRunning) {{
                    const msg = '실행 중에는 종목을 재선정할 수 없습니다. 시스템을 중지 → 종목 재선정 → 시스템 시작 순서로 진행하세요.';
                    if (!silent) {{
                        addLog(msg, 'warning');
                        alert(msg);
                    }}
                    return {{ success: false, message: msg }};
                }}
                const ok = await updateStockSelection(true);
                if (!ok) {{
                    if (!silent) addLog('종목 재선정 중단: 선정 기준 저장 실패', 'warning');
                    return {{ success: false, message: '선정 기준 저장 실패' }};
                }}
                if (!silent) addLog('종목 재선정 중...', 'info');
                const response = await fetch('/api/stocks/select', {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    if (!silent) {{
                        if (data.kept_previous) {{
                            addLog(`선정 결과 없음 → 이전 목록 유지: ${{(data.stocks || []).join(', ') || '-'}}`, 'warning');
                        }} else {{
                            addLog(`종목 선정 완료: ${{(data.stocks || []).join(', ')}}`, 'info');
                        }}
                    }}
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

        function _setPreflightBadge(kind, text) {{
            const el = document.getElementById('preflightBadge');
            if (!el) return;
            el.className = 'pill ' + (kind || '');
            el.textContent = text || '-';
        }}

        function _escapeHtml(s) {{
            return String(s == null ? '' : s)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#039;');
        }}

        function renderPreflight(pf) {{
            const box = document.getElementById('preflightResult');
            if (!box) return;
            if (!pf) {{
                box.style.display = 'none';
                return;
            }}
            box.style.display = 'block';
            const ok = !!pf.ok;
            const issues = Array.isArray(pf.issues) ? pf.issues : [];
            const warnings = Array.isArray(pf.warnings) ? pf.warnings : [];
            const snap = pf.snapshot || {{}};
            const risk = (snap.risk || {{}}) || {{}};
            const strat = (snap.strategy || {{}}) || {{}};
            const sel = Array.isArray(snap.selected_stocks) ? snap.selected_stocks : [];

            const head = `
                <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px;">
                    <span class="pill ${{ok ? 'ok' : 'err'}}">${{ok ? 'OK' : 'BLOCKED'}}</span>
                    <span class="pill ${{issues.length ? 'err' : 'ok'}}">issues: ${{issues.length}}</span>
                    <span class="pill ${{warnings.length ? 'warn' : 'ok'}}">warnings: ${{warnings.length}}</span>
                </div>
            `;
            const kv = `
                <div class="preflight-kv">
                    <div class="k">환경</div><div><code>${{_escapeHtml(snap.is_paper_trading ? '모의' : '실전')}}</code> / <code>${{_escapeHtml(snap.manual_approval ? '수동' : '자동')}}</code></div>
                    <div class="k">감시 종목</div><div><code>${{_escapeHtml(sel.join(', ') || '-')}}</code></div>
                    <div class="k">max_single</div><div><code>${{_escapeHtml(risk.max_single_trade_amount ?? '-')}}</code></div>
                    <div class="k">daily_loss</div><div><code>${{_escapeHtml(risk.daily_loss_limit ?? '-')}}</code></div>
                    <div class="k">max_pos_ratio</div><div><code>${{_escapeHtml(risk.max_position_size_ratio ?? '-')}}</code></div>
                    <div class="k">MA</div><div><code>${{_escapeHtml(strat.short_ma_period ?? '-')}}</code> / <code>${{_escapeHtml(strat.long_ma_period ?? '-')}}</code></div>
                </div>
            `;
            const rows = (title, items) => {{
                const arr = Array.isArray(items) ? items : [];
                if (!arr.length) {{
                    return `<div class="hint">${{_escapeHtml(title)}}: 없음</div>`;
                }}
                const lis = arr.map(x => `<li style="margin:4px 0;">${{_escapeHtml(x)}}</li>`).join('');
                return `
                    <div style="margin:10px 0 6px; font-weight:600; font-size:12px; color:var(--muted);">${{_escapeHtml(title)}}</div>
                    <ul style="margin:0; padding-left:18px; color: var(--text);">${{lis}}</ul>
                `;
            }};
            box.innerHTML = `
                ${{head}}
                ${{kv}}
                <div style="margin-top:8px;">
                    ${{rows('issues (시작 차단 사유)', issues)}}
                    ${{rows('warnings (경고)', warnings)}}
                </div>
            `;
        }}

        async function runPreflight(silent = false) {{
            try {{
                _setPreflightBadge('', '점검 중...');
                const r = await fetch('/api/system/preflight', {{
                    credentials: 'include',
                    headers: {{ 'Authorization': 'Bearer ' + (localStorage.getItem('token') || '') }},
                }});
                const data = await r.json().catch(() => ({{}}));
                if (!r.ok || data.success === false) {{
                    const msg = (data && data.message) ? data.message : ('Preflight 실패: ' + r.status);
                    _setPreflightBadge('err', '오류');
                    if (!silent) addLog(msg, 'error');
                    renderPreflight(null);
                    return {{ success: false, message: msg }};
                }}
                const pf = (data.preflight || null);
                window.__lastPreflight = pf;
                if (pf && pf.ok) {{
                    _setPreflightBadge('ok', 'OK');
                    if (!silent) addLog('Preflight OK (시작 가능)', 'info');
                }} else {{
                    _setPreflightBadge('err', 'BLOCKED');
                    const issues = (pf && Array.isArray(pf.issues)) ? pf.issues : [];
                    if (!silent) addLog('Preflight 차단: ' + (issues.join('; ') || 'unknown'), 'error');
                }}
                if (!silent) renderPreflight(pf);
                return {{ success: true, preflight: pf }};
            }} catch (e) {{
                _setPreflightBadge('err', '오류');
                if (!silent) addLog('Preflight 오류: ' + (e.message || e), 'error');
                return {{ success: false, message: String(e) }};
            }}
        }}

        async function logout() {{
            if (window._systemRunning) {{
                alert('거래가 실행 중입니다. 먼저 시스템을 중지한 뒤 Sign out 해 주세요.');
                return;
            }}
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
        const _perfSub = document.getElementById('performanceSubbar');
        if (_perfSub) _perfSub.style.display = 'none';
        (async () => {{
            await loadUserSettings();
            updateSettingsSummaries();
            await refreshData();
            await loadPendingSignals();
        setInterval(refreshData, 5000);
        }})();
    </script>
</body>
</html>
    """
