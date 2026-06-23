import google.auth
import google.auth.transport.requests
import requests
import json

def get_token():
    credentials, project = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token

def test_deployed():
    token = get_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    service_url = "https://us-east1-aiplatform.googleapis.com/v1/projects/626689579306/locations/us-east1/reasoningEngines/1811115553272627200"
    
    # -------------------------------------------------------------
    # Case 1: $50 Meal Expense (Verify Auto-approval)
    # -------------------------------------------------------------
    print("--- Testing Case 1: $50 Meal Expense ---")
    payload1 = {
        "amount": 50.0,
        "submitter": "alice@company.com",
        "category": "meals",
        "description": "Lunch meeting with product team",
        "date": "2026-06-20"
    }
    
    # 1. Create session
    resp = requests.post(
        f"{service_url}:query",
        headers=headers,
        json={
            "class_method": "async_create_session",
            "input": {"user_id": "test-user-1"},
        },
        timeout=30
    )
    session_id1 = resp.json().get("output", {}).get("id")
    print(f"Created Session 1: {session_id1}")
    
    # 2. Run query
    payload = {
        "class_method": "async_stream_query",
        "input": {
            "user_id": "test-user-1",
            "session_id": session_id1,
            "message": {
                "role": "user",
                "parts": [{"text": json.dumps(payload1)}]
            }
        }
    }
    
    resp = requests.post(f"{service_url}:streamQuery", headers=headers, json=payload, stream=True)
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            event = json.loads(line)
            author = event.get("author")
            content = event.get("content")
            if content and "parts" in content:
                for part in content["parts"]:
                    if "text" in part:
                        print(f"[{author}]: {part['text']}")
                        
    # -------------------------------------------------------------
    # Case 2: $150 Client Dinner (Verify HITL Pause)
    # -------------------------------------------------------------
    print("\n--- Testing Case 2: $150 Client Dinner ---")
    payload2 = {
        "amount": 150.0,
        "submitter": "bob@company.com",
        "category": "meals",
        "description": "Client appreciation dinner",
        "date": "2026-06-20"
    }
    
    # 1. Create session
    resp = requests.post(
        f"{service_url}:query",
        headers=headers,
        json={
            "class_method": "async_create_session",
            "input": {"user_id": "test-user-2"},
        },
        timeout=30
    )
    session_id2 = resp.json().get("output", {}).get("id")
    print(f"Created Session 2: {session_id2}")
    
    # 2. Run query
    payload = {
        "class_method": "async_stream_query",
        "input": {
            "user_id": "test-user-2",
            "session_id": session_id2,
            "message": {
                "role": "user",
                "parts": [{"text": json.dumps(payload2)}]
            }
        }
    }
    
    resp = requests.post(f"{service_url}:streamQuery", headers=headers, json=payload, stream=True)
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            event = json.loads(line)
            author = event.get("author")
            content = event.get("content")
            if content and "parts" in content:
                for part in content["parts"]:
                    if "text" in part:
                        print(f"[{author}]: {part['text']}")
                    if "function_call" in part:
                        fc = part["function_call"]
                        print(f"[{author}] PAUSE triggered: function_call name={fc.get('name')}, args={fc.get('args')}")

if __name__ == "__main__":
    test_deployed()
