file_path = r"c:\Users\User\OneDrive\Dokumenti\Google Antigravity\Projects\Kaggle-google-5days-my-first-project\ambient-expense-agent\.venv\Lib\site-packages\google\adk\models\__init__.py"

with open(file_path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "Gemini" in line:
            print(f"{i+1}: {line.strip()}")
