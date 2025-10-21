from __future__ import annotations
import os, json, re, time, traceback, logging
from typing import Any, Dict, List

from flask import Flask, request, jsonify, current_app
from google import genai  # pip install google-genai>=0.1.0

from policy import is_allowed  # your allowlist helper

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_STAGES = int(os.getenv("MAX_STAGES", "12"))
PLANNER_VERSION = os.getenv("PLANNER_VERSION", "planner-1.1.0")  # bump to verify new image

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
- At most %d stages.
- Each 'name' is <= 40 chars, alnum/space/.- only.
- Each 'command' is a SINGLE shell line (no multiline, no heredocs).
- Prefer commonly available tools; avoid destructive ops and secrets.
""" % MAX_STAGES


def _extract_json(maybe_json: str) -> str:
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

    # Plug into gunicorn logs if present
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
        return jsonify({
            "ok": True,
            "endpoints": ["/healthz", "/plan", "/echo"],
            "model": GEMINI_MODEL,
            "version": PLANNER_VERSION
        })

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "model": GEMINI_MODEL, "version": PLANNER_VERSION})

    @app.post("/echo")
    def echo():
        data = request.get_json(silent=True)
        return jsonify({"received": data, "version": PLANNER_VERSION}), 200

    # Absolute last-resort error handler: ensure HTTP 200 with fallback
    @app.errorhandler(Exception)
    def _catch_all(e: Exception):
        current_app.logger.exception("Global errorhandler caught: %s", e)
        return jsonify({
            "stages": SAFE_FALLBACK_PLAN["stages"],
            "meta": {"fallback": True, "reason": f"global_handler: {e}", "version": PLANNER_VERSION}
        }), 200

    @app.post("/plan")
    def plan():
        """
        Always returns HTTP 200 with JSON (plan or safe fallback).
        """
        try:
            ctx = request.get_json(silent=True) or {}

            prompt = f"""
You are a CI/CD planner that outputs STRICT JSON only.
Given this Jenkins context:
{json.dumps(ctx, indent=2)}

{JSON_SCHEMA_HINT}

Focus:
- If commit message mentions tests/docs only, skip heavy builds.
- If branch is 'main' or 'release/*', include deploy (safe, idempotent commands).
- Prefer commands commonly used by: Python, Node, Java, Go projects.
- Keep commands one-liners compatible with 'sh'.
- Avoid secrets/inline tokens.
""".strip()

            client: genai.Client = current_app.config["GENAI_CLIENT"]

            # Small retry for transient 503/overload
            last_err = None
            for delay in (0.0, 1.5, 3.0):
                if delay:
                    time.sleep(delay)
                try:
                    # IMPORTANT: do NOT pass timeout=
                    resp = client.models.generate_content(
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

                    raw_json = _extract_json(text).strip()
                    plan_dict = json.loads(raw_json)
                    filtered = _postprocess_and_filter(plan_dict)
                    return jsonify(filtered), 200

                except Exception as e:
                    last_err = e
                    msg = str(e)
                    current_app.logger.warning("Gemini attempt failed: %s", msg)
                    if "UNAVAILABLE" not in msg and "503" not in msg:
                        break

            # If all attempts fail, return safe fallback (still 200)
            current_app.logger.exception("Gemini call failed after retries: %s", last_err)
            return jsonify({
                "stages": SAFE_FALLBACK_PLAN["stages"],
                "meta": {"fallback": True, "reason": f"gemini_error: {last_err}", "version": PLANNER_VERSION}
            }), 200

        except Exception as e:
            current_app.logger.exception("Unhandled /plan error")
            return jsonify({
                "stages": SAFE_FALLBACK_PLAN["stages"],
                "meta": {"fallback": True, "reason": f"unhandled: {e}", "version": PLANNER_VERSION,
                         "trace": traceback.format_exc()[:1200]}
            }), 200

    return app


app = make_app()

if __name__ == "__main__":
    print(f"Starting planner {PLANNER_VERSION} on {APP_HOST}:{APP_PORT} with model={GEMINI_MODEL}")
    app.run(host=APP_HOST, port=APP_PORT)
