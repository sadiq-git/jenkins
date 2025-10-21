
from __future__ import annotations
import os, re
from typing import List, Dict

# Named allowlist sets. Keep them tight.
ALLOWLIST_SETS: Dict[str, List[str]] = {
    "base": [
        r"^echo\b.*$",
        r"^true$",
        r"^false$",
        r"^pwd$",
        r"^printenv$",
        r"^env$",
        r"^ls(\s+-[a-zA-Z]+)*(\s+[\w\./\-\*]+)*$",
        r"^cat\s+[\w\./\-\*]+$",
        r"^tee\s+[\w\./\-\*]+$",
    ],
    "git": [
        r"^git\s+status\b.*$",
        r"^git\s+fetch\b.*$",
        r"^git\s+pull\b.*$",
        r"^git\s+submodule\b.*$",
        r"^git\s+rev-parse\b.*$",
        r"^git\s+log\b.*$",
    ],
    "linux": [
        r"^chmod\s+[-+rwxs0-7]+\s+[\w\./\-\*]+$",
        r"^chown\s+[\w:\-]+\s+[\w\./\-\*]+$",
        r"^mv\s+[\w\./\-\*]+\s+[\w\./\-\*]+$",
        r"^cp\s+(-r\s+)?[\w\./\-\*]+\s+[\w\./\-\*]+$",
        r"^rm\s+(-rf|\-f|\-r)\s+[\w\./\-\*]+$",
        r"^mkdir\s+(-p\s+)?[\w\./\-\*]+$",
        r"^du\s+.*$",
        r"^df\s+.*$",
    ],
    "build": [
        r"^make(\s+[\w\-\=]+)*$",
        r"^cmake\s+.*$",
        r"^mvn\s+.*$",
        r"^gradle\s+.*$",
        r"^gradlew\s+.*$",
    ],
    "test": [
        r"^pytest(\s+.*)?$",
        r"^nose(\s+.*)?$",
        r"^pytest-xdist(\s+.*)?$",
        r"^go\s+test(\s+.*)?$",
        r"^npm\s+test(\s+.*)?$",
        r"^yarn\s+test(\s+.*)?$",
    ],
    "python": [
        r"^python(\d+(\.\d+)?)?\s+[-\w\./]+(\s+.*)?$",
        r"^pip(\d+)?\s+install\s+.*$",
        r"^ruff\s+.*$",
        r"^flake8\s+.*$",
        r"^black\s+.*$",
        r"^pytest(\s+.*)?$",
    ],
    "node": [
        r"^npm\s+(ci|i|install)\b.*$",
        r"^npm\s+run\s+[\w\-\:]+(\s+.*)?$",
        r"^yarn(\s+.*)?$",
        r"^pnpm(\s+.*)?$",
    ],
    "java": [
        r"^mvn\s+.*$",
        r"^gradle\s+.*$",
        r"^gradlew\s+.*$",
        r"^java\s+.*$",
        r"^javac\s+.*$",
    ],
    "k8s": [
        r"^kubectl\s+apply\s+-f\s+[\w\./\-\*]+$",
        r"^kubectl\s+rollout\s+status\s+.*$",
        r"^kubectl\s+get\s+.*$",
    ],
}

def compile_allowlist(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p) for p in patterns]

def load_active_allowlist() -> List[re.Pattern]:
    mode = os.getenv("ALLOWLIST_MODE", "strict").strip().lower()
    if mode == "off":
        return []
    selected = [s.strip() for s in os.getenv("ALLOWLIST", "base").split(",") if s.strip()]
    patterns: List[str] = []
    for key in selected:
        patterns += ALLOWLIST_SETS.get(key, [])
    # Always include harmless echo as a baseline
    if r"^echo\b.*$" not in patterns:
        patterns.append(r"^echo\b.*$")
    return compile_allowlist(patterns)

ACTIVE_ALLOWLIST = load_active_allowlist()

def is_allowed(command: str) -> bool:
    if not ACTIVE_ALLOWLIST:  # 'off' mode
        return True
    cmd = command.strip()
    if len(cmd) > int(os.getenv("MAX_CMD_LENGTH", "500")):
        return False
    return any(p.match(cmd) for p in ACTIVE_ALLOWLIST)
