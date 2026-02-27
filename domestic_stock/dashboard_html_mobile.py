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
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            color: #333;
            padding: 0;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
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
            opacity: 0.9;
        }}
        .status {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 8px;
        }}
        .status.running {{ background: rgba(76, 175, 80, 0.3); border: 1px solid #4caf50; }}
        .status.stopped {{ background: rgba(244, 67, 54, 0.3); border: 1px solid #f44336; }}
        .container {{
            padding: 15px;
            max-width: 100%;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .card h2 {{
            color: #667eea;
            font-size: 16px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid #f0f0f0;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }}
        .metric:last-child {{ border-bottom: none; }}
        .metric-label {{
            color: #666;
            font-size: 14px;
        }}
        .metric-value {{
            font-weight: 600;
            font-size: 14px;
            color: #333;
        }}
        .metric-value.positive {{ color: #4caf50; }}
        .metric-value.negative {{ color: #f44336; }}
        .btn {{
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
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
            background: #5568d3;
        }}
        .btn-danger {{
            background: #f44336;
        }}
        .btn-danger:active {{
            background: #d32f2f;
        }}
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.45);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 999;
            padding: 20px;
        }}
        .modal {{
            background: white;
            border-radius: 14px;
            width: 100%;
            max-width: 420px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.25);
            overflow: hidden;
        }}
        .modal-header {{
            padding: 14px 16px;
            border-bottom: 1px solid #f0f0f0;
            font-weight: 700;
            color: #111827;
        }}
        .modal-body {{
            padding: 16px;
            color: #374151;
            font-size: 14px;
            line-height: 1.5;
        }}
        .modal-footer {{
            padding: 12px 16px;
            border-top: 1px solid #f0f0f0;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }}
        .checkbox-row {{
            display: flex;
            gap: 10px;
            align-items: center;
            padding: 10px 12px;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            background: #fafafa;
            margin-top: 12px;
        }}
        .checkbox-row input {{
            width: auto;
            margin: 0;
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
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            -webkit-appearance: none;
            appearance: none;
        }}
        input:focus, select:focus {{
            outline: none;
            border-color: #667eea;
        }}
        .form-group {{
            margin: 12px 0;
        }}
        .form-group label {{
            display: block;
            margin-bottom: 6px;
            color: #666;
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
            border-bottom: 1px solid #f0f0f0;
        }}
        th {{
            background: #f8f8f8;
            color: #667eea;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
        }}
        .log {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 12px;
            border-radius: 8px;
            max-height: 200px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            -webkit-overflow-scrolling: touch;
        }}
        .log-entry {{
            margin: 4px 0;
            padding: 4px;
            word-break: break-word;
        }}
        .log-entry.info {{ color: #4ec9b0; }}
        .log-entry.warning {{ color: #dcdcaa; }}
        .log-entry.error {{ color: #f48771; }}
        .logout-btn {{
            background: transparent;
            border: 1px solid rgba(255,255,255,0.3);
            color: white;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
        }}
        .tabs {{
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}
        .tab {{
            padding: 8px 16px;
            background: white;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            color: #666;
            cursor: pointer;
            white-space: nowrap;
        }}
        .tab.active {{
            background: #667eea;
            color: white;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        @media (min-width: 768px) {{
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
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
    <div class="header">
        <div class="header-top">
            <h1>퀀트 매매 시스템 <span id="status" class="status stopped">중지됨</span></h1>
            <button class="logout-btn" onclick="logout()">로그아웃</button>
        </div>
        <div class="header-user">사용자: {username}</div>
    </div>

    <div class="container">
        <!-- 탭 네비게이션 -->
        <div class="tabs">
            <button class="tab active" onclick="showTab('status')">상태</button>
            <button class="tab" onclick="showTab('positions')">포지션</button>
            <button class="tab" onclick="showTab('settings')">설정</button>
            <button class="tab" onclick="showTab('signals')">승인대기</button>
            <button class="tab" onclick="showTab('trades')">거래내역</button>
        </div>

        <!-- 상태 탭 -->
        <div id="tab-status" class="tab-content active">
            <div class="card">
                <h2>시스템 상태</h2>
                <div class="metric">
                    <span class="metric-label">환경:</span>
                    <span class="metric-value" id="env">-</span>
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
                    <button onclick="startSystem()">시작</button>
                    <button onclick="openStopModal()" class="btn-danger">중지</button>
                </div>
                <button onclick="refreshData()" style="margin-top: 10px;">새로고침</button>
            </div>
            <div class="card">
                <h2>선정 종목 리스트</h2>
                <div id="selected_stocks">
                    <p style="color: #999; text-align: center; padding: 20px;">선정된 종목이 없습니다.</p>
                </div>
            </div>
        </div>

        <!-- 포지션 탭 -->
        <div id="tab-positions" class="tab-content">
            <div class="card">
                <h2>현재 포지션</h2>
                <div id="positions">
                    <p style="color: #999; text-align: center; padding: 20px;">보유 종목이 없습니다.</p>
                </div>
            </div>
        </div>

        <!-- 설정 탭 -->
        <div id="tab-settings" class="tab-content">
            <div class="card">
                <h2>리스크 관리</h2>
                <div class="form-group">
                    <label>최대 거래 금액 (원):</label>
                    <input type="number" id="max_trade_amount" value="1000000">
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
                <button onclick="updateRiskConfig()">저장</button>
            </div>

            <div class="card">
                <h2>전략 설정 (이동평균)</h2>
                <div class="form-group">
                    <label>MA 프리셋:</label>
                    <div class="btn-group">
                        <button type="button" onclick="applyMaPreset(3, 10)">빠름 3/10</button>
                        <button type="button" onclick="applyMaPreset(5, 20)">보수 5/20</button>
                    </div>
                    <button type="button" onclick="applyMaPreset(8, 21)" style="margin-top: 8px;">중기 8/21</button>
                </div>
                <div class="form-group">
                    <label>단기 이동평균 (틱):</label>
                    <input type="number" id="short_ma_period" value="3" min="2" max="60">
                </div>
                <div class="form-group">
                    <label>장기 이동평균 (틱):</label>
                    <input type="number" id="long_ma_period" value="10" min="3" max="200">
                </div>
                <button onclick="updateStrategyConfig()">저장</button>
            </div>

            <div class="card">
                <h2>종목 선정 기준</h2>
                <div class="form-group">
                    <label>프리셋:</label>
                    <select id="preset_select" onchange="loadPreset()">
                        <option value="">직접 설정</option>
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
                <button onclick="updateStockSelection()">저장</button>
                <button onclick="selectStocks()" style="margin-top: 10px;">종목 재선정</button>
            </div>
        </div>

        <!-- 승인대기 탭 -->
        <div id="tab-signals" class="tab-content">
            <div class="card">
                <h2>승인 대기 신호</h2>
                <div id="pending_signals">
                    <p style="color: #999; text-align: center; padding: 20px;">대기 중인 신호가 없습니다.</p>
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
                <div style="margin-top:10px; font-size:12px; color:#6b7280;">
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
                container.innerHTML = '<p style="color: #999; text-align: center; padding: 20px;">대기 중인 신호가 없습니다.</p>';
                return;
            }}

            list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            let html = '';
            list.forEach(signal => {{
                html += `
                    <div style="border: 1px solid #e0e0e0; border-radius: 10px; padding: 12px; margin-bottom: 10px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <strong>${{signal.stock_code}}</strong>
                            <span style="font-size:12px; padding:4px 8px; border-radius:10px; background:${{signal.signal === 'buy' ? '#e8f5e9' : '#ffebee'}}; color:${{signal.signal === 'buy' ? '#2e7d32' : '#c62828'}};">
                                ${{signal.signal === 'buy' ? '매수' : '매도'}}
                            </span>
                        </div>
                        <div style="font-size:13px; color:#666; margin-bottom:4px;">가격: ${{formatNumber(signal.price)}}원</div>
                        <div style="font-size:13px; color:#666; margin-bottom:4px;">수량(제안): ${{signal.suggested_qty}}주</div>
                        <div style="font-size:12px; color:#888; margin-bottom:10px;">사유: ${{signal.reason}}</div>
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
            renderSelectedStocks(data.selected_stock_info || data.selected_stocks || []);
        }}

        function renderSelectedStocks(stocks) {{
            const container = document.getElementById('selected_stocks');
            if (!stocks || stocks.length === 0) {{
                container.innerHTML = '<p style="color: #999; text-align: center; padding: 20px;">선정된 종목이 없습니다.</p>';
                return;
            }}

            const chips = stocks.map(item => {{
                const code = (typeof item === 'string') ? item : (item.code || '-');
                const name = (typeof item === 'string') ? '' : (item.name || '');
                const label = name ? `${{code}} · ${{name}}` : code;
                return `<span style="display:inline-block; padding:6px 10px; margin:4px; border-radius:999px; background:#eef2ff; color:#374151; font-weight:600; font-size:13px;">${{label}}</span>`;
            }}).join('');
            container.innerHTML = `<div>${{chips}}</div>`;
        }}

        function updatePositions(positions) {{
            const container = document.getElementById('positions');
            if (!positions || Object.keys(positions).length === 0) {{
                container.innerHTML = '<p style="color: #999; text-align: center; padding: 20px;">보유 종목이 없습니다.</p>';
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

        async function updateRiskConfig() {{
            try {{
                const config = {{
                    max_single_trade_amount: parseInt(document.getElementById('max_trade_amount').value),
                    stop_loss_ratio: parseFloat(document.getElementById('stop_loss').value) / 100,
                    take_profit_ratio: parseFloat(document.getElementById('take_profit').value) / 100,
                    daily_loss_limit: parseInt(document.getElementById('daily_loss_limit').value),
                    max_trades_per_day: 5,
                    max_position_size_ratio: 0.1
                }};
                const response = await fetch('/api/config/risk', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog('리스크 설정 저장됨', 'info');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
            }}
        }}

        async function updateStrategyConfig() {{
            try {{
                const config = {{
                    short_ma_period: parseInt(document.getElementById('short_ma_period').value),
                    long_ma_period: parseInt(document.getElementById('long_ma_period').value)
                }};
                const response = await fetch('/api/config/strategy', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog(`전략 설정 저장됨 (short=${{config.short_ma_period}}, long=${{config.long_ma_period}})`, 'info');
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

        async function updateStockSelection() {{
            try {{
                const config = {{
                    min_price_change_ratio: parseFloat(document.getElementById('min_change').value) / 100,
                    max_price_change_ratio: parseFloat(document.getElementById('max_change').value) / 100,
                    min_price: parseInt(document.getElementById('min_price').value),
                    max_price: parseInt(document.getElementById('max_price').value),
                    min_volume: parseInt(document.getElementById('min_volume').value),
                    min_trade_amount: parseInt(document.getElementById('min_trade_amount').value) || 0,
                    max_stocks: parseInt(document.getElementById('max_stocks').value),
                    exclude_risk_stocks: true
                }};
                const response = await fetch('/api/config/stock-selection', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await response.json();
                if (data.success) {{
                    addLog('종목 선정 기준 저장됨', 'info');
                }} else {{
                    addLog('종목 선정 기준 저장 실패: ' + (data.message || '알 수 없는 오류'), 'error');
                }}
            }} catch (error) {{
                addLog('오류: ' + error, 'error');
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
                    addLog(`프리셋 로드: ${{preset.name}}`, 'info');
                }}
            }} catch (error) {{
                addLog('프리셋 로드 오류: ' + error, 'error');
            }}
        }}

        async function selectStocks() {{
            try {{
                addLog('종목 재선정 중...', 'info');
                const response = await fetch('/api/stocks/select', {{ method: 'POST' }});
                const data = await response.json();
                if (data.success) {{
                    addLog(`종목 선정 완료: ${{data.stocks.join(', ')}}`, 'info');
                    await refreshData();
                }} else {{
                    addLog('종목 재선정 실패: ' + (data.message || '조건에 맞는 종목 없음'), 'warning');
                    renderSelectedStocks([]);
                }}
            }} catch (error) {{
                addLog('종목 선정 실패: ' + error, 'error');
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
        refreshData();
        loadPendingSignals();
        setInterval(refreshData, 5000);
    </script>
</body>
</html>
    """
