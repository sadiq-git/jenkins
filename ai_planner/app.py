from __future__ import annotations
import os, json, re
from typing import Any, Dict, List

from flask import Flask, request, jsonify
from google import genai  # modern client: pip install google-genai

from policy import is_allowed

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_STAGES = int(os.getenv("MAX_STAGES", "12"))

SAFE_FALLBACK_PLAN = {
    "stages": [
        {"name": "Build",   "command": "make -v"},
        {"name": "Test",    "command": "pytest -q"},
        {"name": "Package", "command": "ls -la"},
    ]
}

JSON_SCHEMA_HINT = """
Respond with STRICT JSON only (no markdown/code fences). The JSON must follow:
{
  "stages": [
    { "name": "Build", "command": "bash command here" },
    { "name": "Test",  "command": "bash command here" }
  ]
}
Rules:
- At most {max_stages} stages.
- Each 'name' is <= 40 chars, alnum/space/.- only.
- Each 'command' is a SINGLE shell line (no multiline, no heredocs).
- Prefer commonly available tools; avoid destructive ops and secrets.
"""

def _extract_json(maybe_json: str) -> str:
    """
    Try to pull a JSON object from a freeform LLM response.
    """
    m = re.search(r"\{.*\}\s*$", maybe_json, flags=re.S)
    return m.group(0) if m else maybe_json

def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9 ._-]", "", name)[:40]

def _postprocess_and_filter(plan: Dict[str, Any]) -> Dict[str, Any]:
    stages: List[Dict[str, str]] = []
    for raw in plan.get("stages", [])[:MAX_STAGES]:
        n = _sanitize_name(str(raw.get("name", "Stage")))
        c = str(raw.get("command", "echo noop")).splitlines()[0].strip()
        if not c:
            continue
        if is_allowed(c):
            stages.append({"name": n, "command": c})
    if not stages:
        stages = SAFE_FALLBACK_PLAN["stages"]
    return {"stages": stages}

def make_app() -> Flask:
    app = Flask(__name__)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set")

    client = genai.Client(api_key=api_key)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "model": GEMINI_MODEL}, 200

    @app.post("/plan")
    def plan():
        ctx = request.get_json(silent=True) or {}

        prompt = f"""
You are a CI/CD planner that outputs STRICT JSON only.
Given this Jenkins context:
{json.dumps(ctx, indent=2)}

{JSON_SCHEMA_HINT.format(max_stages=MAX_STAGES)}

Focus:
- If commit message mentions tests/docs only, skip heavy builds.
- If branch is 'main' or 'release/*', include deploy (safe, idempotent commands).
- Prefer commands commonly used by: Python, Node, Java, Go projects.
- Keep commands one-liners compatible with 'sh'.
- Avoid secrets/inline tokens.
"""

        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            text = (resp.text or "").strip()
            raw_json = _extract_json(text).strip()
            plan_dict = json.loads(raw_json)
        except Exception as e:
            return jsonify({
                "stages": SAFE_FALLBACK_PLAN["stages"],
                "meta": {"fallback": True, "reason": str(e)}
            }), 200

        filtered = _postprocess_and_filter(plan_dict)
        return jsonify(filtered), 200

    return app

app = make_app()

if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT)
