"""Optional Jev model routing with deterministic fallback.

Default mode makes no network request. Set `YIELDPOINT_ENABLE_JEV=1`,
`JEV_API_KEY`, and a calibrated `JEV_MIN_CONFIDENCE` to opt into the documented
Jev model-route endpoint. Never send source, secrets, or a full transcript.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

# Examples are executed directly from a source checkout in CI, where the bare
# interpreter deliberately has no installed Yieldpoint package.  Resolve the
# checkout root only for that direct-script form; installed users import the
# package normally and do not need this branch.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yieldpoint.harness import Change, admit, build_profile

CANDIDATES = (
    {"id": "small", "description": "low-cost local coding model", "capabilities": {"code_generation"}},
    {"id": "capable", "description": "tool-using reasoning coding model", "capabilities": {"code_generation", "tool_use", "strong_reasoning", "large_context", "multilingual_sdk"}},
)


def choose(profile: dict) -> tuple[str, str]:
    """Return model ID and source, preferring deterministic selection safely."""
    eligible = [item for item in CANDIDATES if set(profile["requirements"]["capabilities"]) <= item["capabilities"]]
    if not eligible:
        return "", "human"
    fallback = eligible[0]
    live = _jev(profile, eligible)
    return (live, "jev") if live else (fallback["id"], "deterministic")


def _jev(profile: dict, eligible: list[dict]) -> str:
    """Ask Jev only after explicit consent and locally calibrated confidence setup."""
    if os.getenv("YIELDPOINT_ENABLE_JEV") != "1":
        return ""
    key, threshold = os.getenv("JEV_API_KEY"), os.getenv("JEV_MIN_CONFIDENCE")
    if not key or threshold is None:
        return ""
    payload = {
        "task": "Choose a coding model for a bounded task profile.",
        "candidates": [{key: value for key, value in item.items() if key != "capabilities"} for item in eligible],
        "priorities": ["quality", "context", "tool_use", "cost"],
        "constraints": ["Use only approved host models", "No source or secrets supplied"],
        "stakes": profile["risk"]["value"],
    }
    try:
        request = Request("https://www.jevai.org/api/v1/decisions/model-route", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            answer = json.load(response).get("data", {})
        choice, confidence = answer.get("choice", ""), float(answer.get("confidence", 0))
        return choice if confidence >= float(threshold) and choice in {item["id"] for item in eligible} else ""
    except (URLError, ValueError, OSError):
        return ""


def main() -> int:
    profile = build_profile(Change("sdk/node/src/router.js", "export {}", "export const route = () => 'pass'\n")).to_dict()
    model, source = choose(profile)
    session = admit(profile, task_id="example-release", selected_model=model, selection_source=source)
    print(json.dumps({"model": model, "source": source, "session": session.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
