from __future__ import annotations
import os, json, re, traceback, logging, time, hashlib
from typing import Any, Dict, List, Tuple, Optional

from flask import Flask, request, jsonify
from google import genai  # pip install google-genai>=0.1.0

try:
    from policy import is_allowed
except Exception:
    def is_allowed(cmd: str) -> bool:
        # fallback: allow everything (you can tighten later)
        return True

APP_HOST      = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT      = int(os.getenv("APP_PORT", "8000"))
GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_STAGES    = int(os.getenv("MAX_STAGES", "12"))
CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "600"))     # 10 minutes
GENAI_TIMEOUT = float(os.getenv("GENAI_TIMEOUT", "45"))    # seconds
GENAI_RETRIES = int(os.getenv("GENAI_RETRIES", "4"))       # attempts (incl. first)
GENAI_BACKOFF = float(os.getenv("GENAI_BACKOFF", "0.75"))  # base backoff seconds

# In-memory cache: key -> (expires_at_epoch, plan_dict)
_plan_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

JSON_SCHEMA_HINT = """
Respond with STRICT JSON only (no markdown/code fences). The JSON must follow:
{
  "stages": [
    { "name": "Build", "command": "bash command here" },
    { "name": "Test",  "command": "bash command here" }
  ]
}
Rules:
- At most %(max_stages)d stages.
- Each 'name' is <= 40 chars, alnum/space/.- only.
- Each 'command' is a SINGLE shell line (no multiline, no heredocs).
- Prefer commonly available tools; avoid destructive ops and secrets.
"""

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
    return {"stages": stages}

def _ctx_key(ctx: Dict[str, Any]) -> str:
    b = json.dumps(ctx, sort_keys=True, separators=(",",":")).encode("utf-8")
    return hashlib.sha1(b).hexdigest()

def _get_cached(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    ent = _plan_cache.get(key)
    if ent and ent[0] > now:
        return ent[1]
    if ent:
        _plan_cache.pop(key, None)
    return None

def _put_cache(key: str, plan: Dict[str, Any]) -> None:
    _plan_cache[key] = (time.time() + CACHE_TTL_SEC, plan)

def make_app() -> Flask:
    app = Flask(__name__)

    # Tie Flask logs to gunicorn if present
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
        Returns 200 + plan JSON on success.
        If Gemini fails AND no cached plan is available, returns 503 with error JSON.
        No fallback stages are returned.
        """
        try:
            ctx: Dict[str, Any] = request.get_json(silent=True) or {}
            key = _ctx_key(ctx)

            # Use cache first if still valid
            cached = _get_cached(key)
            if cached:
                return jsonify({"stages": cached["stages"], "meta": {"cached": True}}), 200

            prompt = (
                "You are a CI/CD planner that outputs STRICT JSON only.\n"
                f"Jenkins context (JSON):\n{json.dumps(ctx, separators=(',',':'))}\n\n"
                + JSON_SCHEMA_HINT % {"max_stages": MAX_STAGES}
                + "\nFocus:\n"
                  "- If commit message mentions tests/docs only, skip heavy builds.\n"
                  "- If branch is 'main' or 'release/*', include deploy (safe, idempotent commands).\n"
                  "- Prefer commands commonly used by: Python, Node, Java, Go projects.\n"
                  "- Keep commands one-liners compatible with 'sh'.\n"
                  "- Avoid secrets/inline tokens.\n"
            )

            # Call Gemini with backoff
            text = ""
            last_err = None
            for attempt in range(GENAI_RETRIES):
                try:
                    resp = app.config["GENAI_CLIENT"].models.generate_content(
                        model=GEMINI_MODEL,
                        contents=prompt,
                        timeout=GENAI_TIMEOUT,
                    )
                    text = getattr(resp, "text", "") or ""
                    if not text:
                        # try to extract first candidate text if SDK shape changes
                        try:
                            cand0 = (resp.candidates or [])[0]
                            part0 = getattr(cand0, "content", None)
                            if part0 and getattr(part0, "parts", None):
                                text = part0.parts[0].text or ""
                        except Exception:
                            pass
                    if text:
                        break
                except Exception as e:
                    last_err = e
                # backoff
                time.sleep((GENAI_BACKOFF ** attempt) + 0.25)

            if not text:
                # No text from Gemini
                msg = f"gemini_no_text: {last_err!r}" if last_err else "gemini_no_text"
                return jsonify({"error": msg}), 503

            # Parse & filter
            try:
                raw_json = _extract_json(text).strip()
                plan_dict = json.loads(raw_json)
            except Exception as e:
                return jsonify({"error": f"json_parse_error: {e}", "raw": (text or "")[:500]}), 503

            filtered = _postprocess_and_filter(plan_dict)
            if not filtered.get("stages"):
                return jsonify({"error": "empty_or_disallowed_plan"}), 503

            # Cache successful plan
            _put_cache(key, filtered)
            return jsonify(filtered), 200

        except Exception as e:
            app.logger.exception("Unhandled /plan error")
            return jsonify({
                "error": "unhandled",
                "reason": str(e),
                "trace": traceback.format_exc()[:1200]
            }), 503

    return app

app = make_app()

if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT)
