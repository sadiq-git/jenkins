# ai_planner.py
from flask import Flask, request, jsonify
import json, os
from google import genai  # or boto3 for Bedrock

app = Flask(__name__)

@app.route("/plan", methods=["POST"])
def plan_pipeline():
    context = request.json

    prompt = f"""
    Given this Jenkins context: {json.dumps(context, indent=2)}
    Suggest a Jenkins pipeline plan as JSON.
    Include build, test, deploy stages with shell commands.
    """

    # Example: Gemini / Bedrock call (mocked)
    plan = {
        "stages": [
            {"name": "Build", "command": "make build"},
            {"name": "Test", "command": "pytest --maxfail=1"},
            {"name": "Deploy", "command": "kubectl apply -f k8s/"}
        ]
    }

    return jsonify(plan)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
