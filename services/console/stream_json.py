"""
Pure parser for `claude -p --output-format stream-json` output.

One raw line in, zero or more UI-shaped activity events out. No I/O, no
clock, no state beyond what attribution needs (which tool_use id belongs to
which subagent, which phase of the run has been reached). The runner and the
replayer both feed it, so live and recorded runs render identically.

Two beats run through this parser: the SRE's incident triage and the data
scientist's model investigation. They differ only in which tool calls count as
progress, so each gets a phase tuple and a classifier and everything else is
shared. `services/console/tracks.py` picks the pair; nothing here knows which
one it is serving.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

INCIDENT_PHASES = ("evidence", "correlate", "prove", "fix", "test", "runbook", "pr")
MODEL_PHASES = ("shadow", "reproduce", "leakage", "aggregates", "gates", "card", "pr")

_GIT_HISTORY = re.compile(r"\bgit\s+(log|show|diff|blame)\b")
_GIT_BRANCH = re.compile(r"\bgit\s+(checkout\s+-b|switch\s+-c|commit)\b|\bgh\s+pr\s+create\b")
_SIMULATION = re.compile(r"risk_gateway[./]simulation")
_PYTEST = re.compile(r"\buv\s+run\s+pytest\b|\bpytest\b")
_TEST_FILE = re.compile(r"(^|/)tests?/test_[^/]*\.py$")
_NBCONVERT = re.compile(r"\bnbconvert\b")
_VALIDATION_CLI = re.compile(r"\bml\.validation\.\w+")
_PYTEST_ML = re.compile(r"(?:\buv\s+run\s+)?\bpytest\b[^\n]*\bml\b")


def classify_incident(tool: str, tool_input: dict) -> str | None:
    """Which step of /triage-incident does this tool call belong to, if any."""
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    command = str(tool_input.get("command") or "")
    if tool == "Read" and "ops/incidents/" in path:
        return "evidence"
    if tool == "Bash":
        if _SIMULATION.search(command):
            return "prove"
        if _GIT_BRANCH.search(command):
            return "pr"
        if _GIT_HISTORY.search(command):
            return "correlate"
        if _PYTEST.search(command):
            return "test"
    if tool in ("Edit", "Write", "MultiEdit"):
        if path.endswith(("services/risk_gateway/config.py", "services/risk_gateway/client.py")):
            return "fix"
        if _TEST_FILE.search(path):
            return "test"
        if "ops/runbooks/" in path:
            return "runbook"
        if ".tessera/prs/" in path:
            return "pr"
    return None


def classify_model(tool: str, tool_input: dict) -> str | None:
    """Which step of the TESS-2310 shadow investigation does this belong to, if any?

    `leakage` keys off notebook 01 because that is where the leaky cell lives --
    reading it is the moment the finding lands, and it is the one signal in the
    stream that does not depend on how the analysis happens to be phrased.
    """
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    command = str(tool_input.get("command") or "")
    if tool == "Read" and "ml/registry/" in path:
        return "shadow"
    if tool == "Bash":
        if _NBCONVERT.search(command):
            return "reproduce"
        if _VALIDATION_CLI.search(command) or _PYTEST_ML.search(command):
            return "gates"
        if _GIT_BRANCH.search(command):
            return "pr"
    if tool == "Skill" and "model-card" in str(tool_input.get("skill") or ""):
        return "card"
    if tool in ("Read", "NotebookEdit") and "ml/notebooks/" in path:
        return "leakage" if "01_fraud_exploration" in path else "reproduce"
    if tool in ("Edit", "Write", "MultiEdit"):
        if path.endswith("ml/features/aggregates.py"):
            return "aggregates"
        if "ml/validation/" in path:
            return "gates"
        if path.endswith("ml/fraud/MODEL_CARD.md"):
            return "card"
        if "ml/notebooks/" in path:
            return "reproduce"
        if ".tessera/prs/" in path:
            return "pr"
    return None


# The incident beat was here first and other modules import these names.
PHASES = INCIDENT_PHASES
classify = classify_incident


def summarize(tool: str, tool_input: dict) -> str:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if tool == "Read":
        extra = ""
        if tool_input.get("offset") or tool_input.get("limit"):
            extra = f" [{tool_input.get('offset', 0)}+{tool_input.get('limit', '')}]"
        return f"{path}{extra}"
    if tool == "Write":
        return f"{path} ({len(str(tool_input.get('content', '')))} chars)"
    if tool == "Edit":
        return (f"{path} (−{len(str(tool_input.get('old_string', '')))}"
                f" +{len(str(tool_input.get('new_string', '')))} chars)")
    if tool == "MultiEdit":
        return f"{path} ({len(tool_input.get('edits') or [])} edits)"
    if tool == "NotebookEdit":
        return f"{path} {tool_input.get('edit_mode', 'replace')} cell {tool_input.get('cell_id', '')}".strip()
    if tool == "Bash":
        command = str(tool_input.get("command", "")).strip().replace("\n", " ⏎ ")
        return command[:160] + ("…" if len(command) > 160 else "")
    if tool in ("Grep", "Glob"):
        where = tool_input.get("path") or tool_input.get("glob") or ""
        return f"{tool_input.get('pattern', '')}" + (f" in {where}" if where else "")
    if tool in ("Task", "Agent"):
        return f"{tool_input.get('subagent_type', 'subagent')}: {tool_input.get('description', '')}".strip()
    if tool == "Skill":
        return f"/{tool_input.get('skill', '')} {tool_input.get('args', '')}".strip()
    text = json.dumps(tool_input, sort_keys=True)
    return text[:160] + ("…" if len(text) > 160 else "")


def _truncate_input(tool_input: dict, limit: int = 2000) -> dict:
    out = {}
    for key, value in tool_input.items():
        if isinstance(value, str) and len(value) > limit:
            out[key] = value[:limit] + f"… [{len(value)} chars]"
        else:
            out[key] = value
    return out


def _preview(content: object, limit: int = 300) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(str(block.get("text", "")) for block in content
                         if isinstance(block, dict) and block.get("type") == "text")
    else:
        text = "" if content is None else str(content)
    text = text.strip()
    return text[:limit] + ("…" if len(text) > limit else "")


@dataclass
class StreamParser:
    run_id: str
    session_id: str | None = None
    phases: tuple[str, ...] = INCIDENT_PHASES
    classifier: Callable[[str, dict], str | None] = classify_incident
    phases_seen: list[str] = field(default_factory=list)
    _agents: dict[str, str] = field(default_factory=dict)
    _tools: dict[str, str] = field(default_factory=dict)

    # --- public --------------------------------------------------------------
    def parse(self, raw: str) -> list[dict]:
        raw = raw.strip()
        if not raw:
            return []
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return [self._event("raw", None, raw=raw[:500], note="not json")]
        if not isinstance(message, dict):
            return [self._event("raw", None, raw=raw[:500])]

        kind = message.get("type")
        parent = message.get("parent_tool_use_id")
        if kind == "system":
            return self._system(message, raw)
        if kind == "assistant":
            return self._assistant(message, parent)
        if kind == "user":
            return self._user(message, parent)
        if kind == "result":
            return [self._event(
                "result", parent,
                subtype=message.get("subtype"), is_error=bool(message.get("is_error")),
                num_turns=message.get("num_turns"), duration_ms=message.get("duration_ms"),
                cost_usd=message.get("total_cost_usd"), result_text=str(message.get("result") or "")[:2000],
            )]
        if kind == "tool_use":       # flat variants some builds emit
            return self._tool_use(message, parent)
        if kind == "tool_result":
            return [self._tool_result(message, parent)]
        return [self._event("raw", parent, raw=raw[:500], message_type=kind)]

    # --- per message type --------------------------------------------------
    def _system(self, message: dict, raw: str) -> list[dict]:
        subtype = str(message.get("subtype") or "")
        if subtype == "init":
            self.session_id = message.get("session_id") or self.session_id
            return [self._event(
                "session", None, session_id=self.session_id, model=message.get("model"),
                tools=message.get("tools") or [], permission_mode=message.get("permissionMode"),
                cwd=message.get("cwd"),
            )]
        if subtype == "thinking_tokens":
            # Emitted every few hundred ms while the model reasons; a heartbeat, not content.
            return [self._event("thinking", None,
                                tokens=message.get("estimated_tokens_delta") or message.get("estimated_tokens") or 0)]
        if subtype == "permission_denied":
            # The headless allowlist at work: a tool outside --allowedTools was refused.
            return [self._event(
                "permission_denied", message.get("parent_tool_use_id"),
                tool_name=message.get("tool_name"), tool_use_id=message.get("tool_use_id"),
                reason=message.get("decision_reason"), message=str(message.get("message") or "")[:300],
            )]
        if "hook" in subtype:
            return [self._hook(message, subtype)]
        return [self._event("system", None, subtype=subtype, raw=raw[:300])]

    def _hook(self, message: dict, subtype: str) -> dict:
        exit_code = message.get("exit_code")
        if exit_code is None:
            exit_code = (message.get("response") or {}).get("exit_code") if isinstance(message.get("response"), dict) else None
        decision = None
        if exit_code == 2:
            decision = "deny"
        elif exit_code == 0:
            decision = "allow"
        output = message.get("stderr") or message.get("output") or message.get("stdout") or ""
        if isinstance(output, list):
            output = "\n".join(map(str, output))
        hook_name = str(message.get("hook_name") or message.get("command") or "")
        tool_name = message.get("tool_name") or (hook_name.split(":", 1)[1] if ":" in hook_name else None)
        return self._event(
            "hook", message.get("parent_tool_use_id"),
            subtype=subtype, hook_id=message.get("hook_id"),
            hook_event_name=message.get("hook_event") or message.get("hook_event_name") or message.get("event"),
            hook_name=hook_name or None, tool_name=tool_name, outcome=message.get("outcome"),
            exit_code=exit_code, decision=decision, stderr_head=str(output)[:300],
        )

    def _assistant(self, message: dict, parent: str | None) -> list[dict]:
        events: list[dict] = []
        content = (message.get("message") or {}).get("content") or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                events.append(self._event("text", parent, text=str(block["text"])[:4000]))
            elif block.get("type") == "tool_use":
                events.extend(self._tool_use(block, parent))
        return events

    def _tool_use(self, block: dict, parent: str | None) -> list[dict]:
        tool = str(block.get("name") or "")
        tool_input = block.get("input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {"value": tool_input}
        tool_use_id = str(block.get("id") or "")
        self._tools[tool_use_id] = tool
        if tool in ("Task", "Agent"):
            self._agents[tool_use_id] = str(tool_input.get("subagent_type") or "subagent")
        events = [self._event(
            "tool_call", parent, tool_use_id=tool_use_id, tool=tool,
            summary=summarize(tool, tool_input), input=_truncate_input(tool_input),
        )]
        phase = self.classifier(tool, tool_input)
        if phase and phase not in self.phases_seen:
            self.phases_seen.append(phase)
            events.append(self._event("phase", parent, phase=phase, index=self.phases.index(phase)))
        return events

    def _user(self, message: dict, parent: str | None) -> list[dict]:
        content = (message.get("message") or {}).get("content") or []
        if isinstance(content, str):
            return []
        return [self._tool_result(block, parent) for block in content
                if isinstance(block, dict) and block.get("type") == "tool_result"]

    def _tool_result(self, block: dict, parent: str | None) -> dict:
        tool_use_id = str(block.get("tool_use_id") or "")
        return self._event(
            "tool_result", parent, tool_use_id=tool_use_id, tool=self._tools.get(tool_use_id),
            is_error=bool(block.get("is_error")), preview=_preview(block.get("content")),
        )

    # --- helpers -----------------------------------------------------------
    def _event(self, kind: str, parent: str | None, **fields: object) -> dict:
        agent = "main" if not parent else self._agents.get(parent, "subagent")
        event = {"type": kind, "run_id": self.run_id, "agent": agent}
        if parent:
            event["parent_tool_use_id"] = parent
        event.update(fields)
        return event
