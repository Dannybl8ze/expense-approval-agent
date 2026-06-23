import os
import re
import sys
import json
import logging
import subprocess
import requests
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manager_dashboard")

app = FastAPI(title="Gemini Enterprise Manager Dashboard")

# Read GCP config from environment variables
AGENT_RUNTIME_ID = os.environ.get(
    "AGENT_RUNTIME_ID",
    "projects/626689579306/locations/us-east1/reasoningEngines/1811115553272627200"
)
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-3ba8b553-324f-445f-b23")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-east1")

# Extract project, location, and engine ID from full runtime ID if possible
match = re.search(r"projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/]+)", AGENT_RUNTIME_ID)
if match:
    project_num = match.group(1)
    location_val = match.group(2)
    reasoning_engine_id = match.group(3)
else:
    project_num = PROJECT_ID
    location_val = LOCATION
    reasoning_engine_id = AGENT_RUNTIME_ID

def get_access_token() -> str:
    """Retrieves GCP OAuth 2.0 access token via gcloud with fallback to google.auth."""
    # 1. Try gcloud CLI using the current python executable
    try:
        env = dict(os.environ)
        env["CLOUDSDK_PYTHON"] = sys.executable
        token_proc = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            shell=True,
            env=env,
            timeout=60
        )
        token = token_proc.stdout.strip()
        if token:
            return token
    except Exception as e:
        logger.warning(f"gcloud token retrieval failed: {e}")

    # 2. Fallback to google.auth
    try:
        import google.auth
        import google.auth.transport.requests
        credentials, project = google.auth.default()
        request_obj = google.auth.transport.requests.Request()
        credentials.refresh(request_obj)
        if credentials.token:
            return credentials.token
    except Exception as e:
        logger.error(f"google.auth token retrieval failed: {e}")

    raise RuntimeError("Failed to retrieve a valid Google Cloud access token.")

class ActionRequest(BaseModel):
    approved: bool
    interrupt_id: str

@app.get("/api/pending")
async def get_pending_approvals():
    """Queries Reasoning Engine sessions and filters for unresolved human_approval interrupts."""
    try:
        token = get_access_token()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Vertex AI REST API URL to list sessions
    # We use project_num (number or ID) to query the service
    list_url = f"https://{location_val}-aiplatform.googleapis.com/v1beta1/projects/{project_num}/locations/{location_val}/reasoningEngines/{reasoning_engine_id}/sessions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.get(list_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.error(f"List sessions failed: {resp.status_code} - {resp.text}")
            return []
        
        sessions_data = resp.json()
        sessions = sessions_data.get("sessions", [])
    except Exception as e:
        logger.error(f"Error querying sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to connect to Vertex AI sessions service")

    pending_approvals = []

    # Iterate over each session and check events to identify unresolved interrupts
    for session in sessions:
        session_name = session.get("name")
        session_id = session_name.split("/")[-1]
        
        # Get events for this specific session
        events_url = f"https://{location_val}-aiplatform.googleapis.com/v1beta1/{session_name}/events"
        try:
            events_resp = requests.get(events_url, headers=headers, timeout=10)
            if events_resp.status_code != 200:
                logger.warning(f"Failed to get events for session {session_id}: {events_resp.status_code}")
                continue
            
            events_data = events_resp.json()
            events = events_data.get("sessionEvents", []) or events_data.get("events", [])
        except Exception as e:
            logger.warning(f"Error fetching events for session {session_id}: {e}")
            continue

        # Check for unresolved adk_request_input calls
        unresolved_calls = {}
        for event in events:
            content = event.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                fc = part.get("functionCall")
                if fc and fc.get("name") == "adk_request_input":
                    args = fc.get("args") or {}
                    iid = fc.get("id") or args.get("interruptId") or "human_approval"
                    unresolved_calls[iid] = event

                fr = part.get("functionResponse")
                if fr and fr.get("name") == "adk_request_input":
                    iid = fr.get("id") or "human_approval"
                    unresolved_calls.pop(iid, None)

        if unresolved_calls:
            # Found a pending approval event
            interrupt_id = list(unresolved_calls.keys())[0]
            state = session.get("sessionState", {})
            
            pending_approvals.append({
                "session_id": session_id,
                "interrupt_id": interrupt_id,
                "expense": state.get("expense", {}),
                "risk_assessment": state.get("risk_assessment", {})
            })

    return pending_approvals

@app.post("/api/action/{session_id}")
async def post_action(session_id: str, req: ActionRequest):
    """Resumes the paused session on Agent Runtime with the approved outcome."""
    try:
        token = get_access_token()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # streamQuery endpoint for resuming reasoning engine execution
    url = f"https://{location_val}-aiplatform.googleapis.com/v1beta1/projects/{project_num}/locations/{location_val}/reasoningEngines/{reasoning_engine_id}:streamQuery"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Format resume payload as required by Vertex ADK
    payload = {
        "class_method": "stream_query",
        "input": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "id": req.interrupt_id,
                            "name": "adk_request_input",
                            "response": {
                                "response": "approve" if req.approved else "reject"
                            }
                        }
                    }
                ]
            },
            "user_id": "default-user",
            "session_id": session_id
        }
    }

    try:
        # Call streamQuery and parse the SSE stream response
        logger.info(f"Resuming session {session_id} via streamQuery (approved: {req.approved})")
        response = requests.post(url, headers=headers, json=payload, stream=True, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Stream query call failed: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Agent Runtime error: {response.text}")

        final_text = ""
        status_outcome = "unknown"

        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data:"):
                    decoded = decoded[5:].strip()
                try:
                    event = json.loads(decoded)
                    # Accumulate model response text
                    content = event.get("content", {})
                    parts = content.get("parts", [])
                    for part in parts:
                        text = part.get("text")
                        if text:
                            final_text += text + "\n"
                    
                    # Track outcome status
                    output = event.get("output")
                    if output and isinstance(output, dict):
                        status = output.get("status")
                        if status:
                            status_outcome = status
                except Exception:
                    pass

        return {
            "status": "success",
            "outcome": status_outcome,
            "review": final_text.strip()
        }

    except Exception as e:
        logger.exception(f"Error resuming session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serves a beautiful, glassmorphic manager dashboard interface."""
    html_content = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Expense Manager Dashboard</title>
    <!-- Outfit Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #080710;
            --font-family: 'Outfit', sans-serif;
            --purple-glow: rgba(127, 0, 255, 0.4);
            --cyan-glow: rgba(0, 242, 254, 0.4);
            --card-bg: rgba(255, 255, 255, 0.06);
            --card-border: rgba(255, 255, 255, 0.1);
            --text-primary: #ffffff;
            --text-secondary: rgba(255, 255, 255, 0.6);
            
            --success-color: #00e676;
            --danger-color: #ff1744;
            --warning-color: #ff9100;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            font-family: var(--font-family);
            color: var(--text-primary);
            overflow-x: hidden;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            position: relative;
        }

        /* Ambient Background Glows */
        .background-glow {
            position: fixed;
            width: 50vw;
            height: 50vw;
            border-radius: 50%;
            filter: blur(150px);
            z-index: -1;
            pointer-events: none;
            opacity: 0.8;
        }

        .glow-top-left {
            top: -20vw;
            left: -10vw;
            background: radial-gradient(circle, var(--purple-glow) 0%, transparent 70%);
        }

        .glow-bottom-right {
            bottom: -20vw;
            right: -10vw;
            background: radial-gradient(circle, var(--cyan-glow) 0%, transparent 70%);
        }

        /* Container & Header */
        .container {
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
            padding: 40px 20px;
            flex-grow: 1;
            z-index: 1;
        }

        header {
            margin-bottom: 50px;
            text-align: center;
        }

        h1 {
            font-size: 2.8rem;
            font-weight: 700;
            letter-spacing: -1px;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #ffffff 0%, #a6c0fe 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .subtitle {
            color: var(--text-secondary);
            font-size: 1.1rem;
            font-weight: 300;
        }

        /* Cards Grid */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 30px;
        }

        /* Glassmorphic Card */
        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 20px;
            padding: 30px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), border-color 0.3s ease, box-shadow 0.3s ease;
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
        }

        .card:hover {
            transform: translateY(-8px);
            border-color: rgba(255, 255, 255, 0.2);
            box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.5);
        }

        /* Card Header */
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 20px;
        }

        .submitter {
            font-weight: 600;
            font-size: 1.1rem;
            color: var(--text-primary);
            word-break: break-all;
            padding-right: 10px;
        }

        /* Badges */
        .badge {
            font-size: 0.75rem;
            font-weight: 600;
            padding: 5px 12px;
            border-radius: 50px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .badge-high {
            background-color: rgba(255, 23, 68, 0.2);
            color: var(--danger-color);
            border: 1px solid rgba(255, 23, 68, 0.4);
        }

        .badge-medium {
            background-color: rgba(255, 145, 0, 0.2);
            color: var(--warning-color);
            border: 1px solid rgba(255, 145, 0, 0.4);
        }

        .badge-low {
            background-color: rgba(0, 230, 118, 0.2);
            color: var(--success-color);
            border: 1px solid rgba(0, 230, 118, 0.4);
        }

        /* Expense Amount */
        .amount {
            font-size: 2.2rem;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 15px;
            text-shadow: 0 0 10px rgba(255,255,255,0.2);
        }

        /* Details */
        .detail-row {
            margin-bottom: 10px;
            font-size: 0.9rem;
        }

        .label {
            color: var(--text-secondary);
            font-weight: 400;
            margin-right: 5px;
        }

        .val {
            color: var(--text-primary);
            font-weight: 500;
        }

        .description {
            background: rgba(255, 255, 255, 0.03);
            border-radius: 10px;
            padding: 12px;
            font-size: 0.9rem;
            color: var(--text-secondary);
            margin: 15px 0;
            line-height: 1.4;
            border: 1px solid rgba(255, 255, 255, 0.02);
        }

        /* Warnings Section */
        .warnings {
            margin-bottom: 25px;
            font-size: 0.85rem;
            background: rgba(255, 145, 0, 0.08);
            border-left: 3px solid var(--warning-color);
            padding: 10px 15px;
            border-radius: 4px;
        }

        .warnings-title {
            color: var(--warning-color);
            font-weight: 600;
            margin-bottom: 5px;
        }

        .warnings-list {
            list-style: none;
            color: var(--text-primary);
        }

        .warnings-list li {
            position: relative;
            padding-left: 12px;
            margin-bottom: 4px;
        }

        .warnings-list li::before {
            content: "•";
            position: absolute;
            left: 0;
            color: var(--warning-color);
        }

        /* Buttons Action Layout */
        .actions {
            margin-top: auto;
            display: flex;
            gap: 15px;
        }

        .btn {
            flex: 1;
            padding: 14px 20px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            justify-content: center;
            align-items: center;
            outline: none;
        }

        .btn-approve {
            background: rgba(0, 230, 118, 0.15);
            border: 1px solid rgba(0, 230, 118, 0.4);
            color: var(--success-color);
        }

        .btn-approve:hover:not(:disabled) {
            background: var(--success-color);
            color: #000;
            box-shadow: 0 0 15px rgba(0, 230, 118, 0.4);
        }

        .btn-reject {
            background: rgba(255, 23, 68, 0.15);
            border: 1px solid rgba(255, 23, 68, 0.4);
            color: var(--danger-color);
        }

        .btn-reject:hover:not(:disabled) {
            background: var(--danger-color);
            color: #fff;
            box-shadow: 0 0 15px rgba(255, 23, 68, 0.4);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Loading Spinner */
        .spinner {
            width: 18px;
            height: 18px;
            border: 2px solid currentColor;
            border-bottom-color: transparent;
            border-radius: 50%;
            display: none;
            animation: rotation 1s linear infinite;
        }

        @keyframes rotation {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* Empty State */
        .empty-state {
            grid-column: 1 / -1;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 20px;
            padding: 60px 20px;
            text-align: center;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
        }

        .empty-icon {
            font-size: 4rem;
            margin-bottom: 20px;
            color: var(--success-color);
            animation: pulse 2s infinite alternate;
        }

        @keyframes pulse {
            0% { transform: scale(1); filter: drop-shadow(0 0 2px var(--success-color)); }
            100% { transform: scale(1.1); filter: drop-shadow(0 0 15px var(--success-color)); }
        }

        .empty-title {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 10px;
        }

        .empty-desc {
            color: var(--text-secondary);
            font-weight: 300;
        }

        /* Slide-out Drawer Modal */
        .drawer-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0, 0, 0, 0.6);
            backdrop-filter: blur(5px);
            z-index: 99;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .drawer-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }

        .drawer {
            position: fixed;
            top: 0;
            right: -450px;
            width: 100%;
            max-width: 450px;
            height: 100vh;
            background: #0c0b14;
            border-left: 1px solid rgba(255, 255, 255, 0.1);
            z-index: 100;
            padding: 40px;
            display: flex;
            flex-direction: column;
            transition: right 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: -10px 0 30px rgba(0, 0, 0, 0.5);
        }

        .drawer.active {
            right: 0;
        }

        .drawer-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
        }

        .drawer-title {
            font-size: 1.8rem;
            font-weight: 700;
        }

        .btn-close {
            background: transparent;
            border: none;
            color: var(--text-primary);
            font-size: 1.8rem;
            cursor: pointer;
            opacity: 0.6;
            transition: opacity 0.2s;
        }

        .btn-close:hover {
            opacity: 1;
        }

        .drawer-body {
            flex-grow: 1;
            overflow-y: auto;
        }

        .outcome-badge-container {
            margin-bottom: 25px;
            display: flex;
            justify-content: center;
        }

        .outcome-text {
            font-size: 1rem;
            line-height: 1.6;
            color: var(--text-secondary);
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 20px;
            border-radius: 12px;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <!-- Background elements -->
    <div class="background-glow glow-top-left"></div>
    <div class="background-glow glow-bottom-right"></div>

    <div class="container">
        <header>
            <h1>Expense Approvals</h1>
            <div class="subtitle">ADK 2.0 Agent Engine Manager Dashboard</div>
        </header>

        <main id="dashboard-grid" class="grid">
            <!-- Loaded dynamically -->
            <div style="grid-column: 1/-1; text-align: center; padding: 50px;">
                <div class="spinner" style="display: inline-block; width: 40px; height: 40px;"></div>
                <p style="margin-top: 15px; color: var(--text-secondary);">Querying session registry...</p>
            </div>
        </main>
    </div>

    <!-- Details/Compliance Modal Drawer -->
    <div id="overlay" class="drawer-overlay"></div>
    <div id="drawer" class="drawer">
        <div class="drawer-header">
            <div class="drawer-title">Review Output</div>
            <button class="btn-close" onclick="closeDrawer()">&times;</button>
        </div>
        <div class="drawer-body">
            <div class="outcome-badge-container">
                <span id="outcome-badge" class="badge"></span>
            </div>
            <div id="outcome-details" class="outcome-text"></div>
        </div>
    </div>

    <script>
        async function fetchPending() {
            const grid = document.getElementById('dashboard-grid');
            try {
                const response = await fetch('/api/pending');
                if (!response.ok) throw new Error('API request failed');
                const approvals = await response.json();
                
                if (approvals.length === 0) {
                    grid.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">✓</div>
                            <div class="empty-title">All Caught Up!</div>
                            <div class="empty-desc">No pending expense approvals found in the registry.</div>
                        </div>
                    `;
                    return;
                }

                grid.innerHTML = '';
                approvals.forEach(app => {
                    const card = document.createElement('div');
                    card.className = 'card';
                    card.id = `card-${app.session_id}`;
                    
                    const amountFormatted = new Intl.NumberFormat('en-US', {
                        style: 'currency',
                        currency: 'USD'
                    }).format(app.expense.amount || 0);

                    const riskLevel = app.risk_assessment.risk_level || 'Low';
                    const badgeClass = `badge-${riskLevel.toLowerCase()}`;
                    
                    let warningsHTML = '';
                    const warnings = app.risk_assessment.warnings || [];
                    if (warnings.length > 0) {
                        warningsHTML = `
                            <div class="warnings">
                                <div class="warnings-title">Compliance Alerts</div>
                                <ul class="warnings-list">
                                    ${warnings.map(w => '<li>' + w + '</li>').join('')}
                                </ul>
                            </div>
                        `;
                    }

                    card.innerHTML = `
                        <div class="card-header">
                            <span class="submitter">${app.expense.submitter || 'unknown'}</span>
                            <span class="badge ${badgeClass}">${riskLevel} Risk</span>
                        </div>
                        <div class="amount">${amountFormatted}</div>
                        <div class="detail-row"><span class="label">Category:</span><span class="val">${app.expense.category || 'unknown'}</span></div>
                        <div class="detail-row"><span class="label">Date:</span><span class="val">${app.expense.date || 'unknown'}</span></div>
                        <div class="description">"${app.expense.description || ''}"</div>
                        ${warningsHTML}
                        <div class="actions">
                            <button class="btn btn-reject" onclick="handleAction('${app.session_id}', '${app.interrupt_id}', false)">
                                <span class="btn-text">Reject</span>
                                <div class="spinner"></div>
                            </button>
                            <button class="btn btn-approve" onclick="handleAction('${app.session_id}', '${app.interrupt_id}', true)">
                                <span class="btn-text">Approve</span>
                                <div class="spinner"></div>
                            </button>
                        </div>
                    `;
                    grid.appendChild(card);
                });
            } catch (err) {
                console.error(err);
                grid.innerHTML = `
                    <div class="empty-state" style="border-color: var(--danger-color);">
                        <div class="empty-state" style="border-color: var(--danger-color);">
                            <div class="empty-icon" style="color: var(--danger-color);">!</div>
                            <div class="empty-title">Connection Error</div>
                            <div class="empty-desc">Failed to connect to the backend API. Please make sure the service is running.</div>
                        </div>
                    </div>
                `;
            }
        }

        async function handleAction(sessionId, interruptId, approved) {
            const card = document.getElementById(`card-${sessionId}`);
            const buttons = card.querySelectorAll('.btn');
            const clickedBtn = approved ? card.querySelector('.btn-approve') : card.querySelector('.btn-reject');
            
            // Show loading spinner
            buttons.forEach(btn => btn.disabled = true);
            clickedBtn.querySelector('.btn-text').style.display = 'none';
            clickedBtn.querySelector('.spinner').style.display = 'block';

            try {
                const response = await fetch(`/api/action/${sessionId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ approved, interrupt_id: interruptId })
                });

                if (!response.ok) throw new Error('Resumption failed');
                const result = await response.json();

                // Open Slide-out compliance drawer
                openDrawer(result.outcome, result.review);

                // Remove card from UI
                card.style.opacity = '0';
                card.style.transform = 'scale(0.8)';
                setTimeout(() => {
                    card.remove();
                    // If no cards left, refresh list
                    if (document.querySelectorAll('.card').length === 0) {
                        fetchPending();
                    }
                }, 300);

            } catch (err) {
                console.error(err);
                alert('Action failed. Please try again.');
                buttons.forEach(btn => btn.disabled = false);
                clickedBtn.querySelector('.btn-text').style.display = 'block';
                clickedBtn.querySelector('.spinner').style.display = 'none';
            }
        }

        function openDrawer(outcome, review) {
            const badge = document.getElementById('outcome-badge');
            const details = document.getElementById('outcome-details');
            
            badge.className = 'badge';
            if (outcome.toLowerCase() === 'approved') {
                badge.classList.add('badge-low');
                badge.innerText = 'Approved';
            } else {
                badge.classList.add('badge-high');
                badge.innerText = 'Rejected';
            }

            details.innerText = review || 'No review details returned.';

            document.getElementById('overlay').classList.add('active');
            document.getElementById('drawer').classList.add('active');
        }

        function closeDrawer() {
            document.getElementById('overlay').classList.remove('active');
            document.getElementById('drawer').classList.remove('active');
        }

        document.getElementById('overlay').addEventListener('click', closeDrawer);

        // Fetch on load
        window.addEventListener('DOMContentLoaded', fetchPending);
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
