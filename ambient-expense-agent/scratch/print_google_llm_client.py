file_path = r"c:\Users\User\OneDrive\Dokumenti\Google Antigravity\Projects\Kaggle-google-5days-my-first-project\ambient-expense-agent\.venv\Lib\site-packages\google\adk\models\google_llm.py"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# find all occurrences of def api_client
occurrences = []
for i, line in enumerate(lines):
    if "def api_client" in line:
        occurrences.append(i)

print("Found occurrences of def api_client:", occurrences)
for start_idx in occurrences:
    print(f"--- Occurrence at line {start_idx+1} ---")
    for idx in range(start_idx - 2, start_idx + 25):
        if idx < len(lines):
            print(f"{idx+1}: {lines[idx].strip()}")
