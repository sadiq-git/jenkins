from __future__ import annotations
import os, json, re, traceback, logging
from typing import Any, Dict, List

from flask import Flask, request, jsonify
from google import genai  # requires: google-genai>=0.1.0

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

# NOTE: all JSON braces are escaped with double braces so .format() only fills {max_stages}
JSON_SCHEMA_HINT = """
Respond with STRICT JSON only (no markdown/code fences). The JSON must follow:
{{
  "stages": [
    {{ "name": "Build", "command": "bash command here" }},
    {{ "name": "Test",  "command": "bash command here" }}
  ]
}}
Rules:
- At most {max_stages} stages.
- Each 'name' is <= 40 chars, alnum/space/.- only.
- Each 'command' is a SINGLE shell line (no multiline, no heredocs).
- Prefer commonly available tools; avoid destructive ops and secrets.
"""

def _extract_json(maybe_json: str) -> str:
    """
    Extract the first JSON object from a Gemini response.
    Strips markdown code fences and any stray text.
    """
    if not isinstance(maybe_json, str):
        return "{}"
    cleaned = re.sub(r"```(json)?", "", maybe_json, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()
    m = re.search(r"\{[\s\S]*\}", cleaned)
    return m.group(0) if m else cleaned

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

    # Tie Flask logs to gunicorn if available
    gunicorn_error_logger = logging.getLogger("gunicorn.error")
    if gunicorn_error_logger.handlers:
        app.logger.handlers = gunicorn_error_logger.handlers
        app.logger.setLevel(gunicorn_error_logger.level)
    else:
        logging.basicConfig(level=logging.INFO)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set")

    client = genai.Client(api_key=api_key)
    app.config["GENAI_CLIENT"] = client

    @app.get("/")
    def root():
        return jsonify({"ok": True, "endpoints": ["/healthz", "/plan", "/echo"], "model": GEMINI_MODEL})

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "model": GEMINI_MODEL})

    @app.post("/echo")
    def echo():
        data = request.get_json(silent=True)
        return jsonify({"received": data}), 200

    @app.post("/plan")
    def plan():
        """
        Always returns HTTP 200 with JSON.
        On any error, returns SAFE_FALLBACK_PLAN and meta.reason.
        """
        try:   
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

            # Call Gemini
            try:
                resp = app.config["GENAI_CLIENT"].models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                text = getattr(resp, "text", None)
                if not text:
                    try:
                        cand0 = (resp.candidates or [])[0]
                        part0 = getattr(cand0, "content", None)
                        if part0 and getattr(part0, "parts", None):
                            text = part0.parts[0].text
                    except Exception:
                        text = ""
            except Exception as e:
                app.logger.exception("Gemini call failed")
                return jsonify({
                    "stages": SAFE_FALLBACK_PLAN["stages"],
                    "meta": {"fallback": True, "reason": f"gemini_error: {str(e)}"}
                }), 200

            # Parse JSON
            try:
                raw_json = _extract_json(text).strip()
                plan_dict = json.loads(raw_json)
            except Exception as e:
                app.logger.warning("JSON parse failed; returning fallback: %s", e)
                return jsonify({
                    "stages": SAFE_FALLBACK_PLAN["stages"],
                    "meta": {"fallback": True, "reason": f"json_error: {str(e)}", "raw": (text or "")[:800]}
                }), 200

            # Filter & return
            filtered = _postprocess_and_filter(plan_dict)
            return jsonify(filtered), 200

        except Exception as e:
            app.logger.exception("Unhandled /plan error")
            return jsonify({
                "stages": SAFE_FALLBACK_PLAN["stages"],
                "meta": {
                    "fallback": True,
                    "reason": f"unhandled: {str(e)}",
                    "trace": traceback.format_exc()[:1200]
                }
            }), 200

    return app

app = make_app()

if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT)
