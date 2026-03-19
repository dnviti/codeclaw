#!/usr/bin/env python3
"""LLM-as-judge conflict resolution engine for CTDF vector memory.

Provides automated resolution for "opinion" category conflicts that would
otherwise accumulate in ``.claude/memory/conflicts/`` waiting for manual
triage.  Supports three strategies:

    - **single-judge**: One LLM evaluation producing a reasoned verdict.
    - **majority-vote**: Multiple evaluations (default 3) with majority
      selection.
    - **confidence-merge**: Auto-merge when the judge's self-reported
      confidence exceeds a configurable threshold.

Providers:
    - ``ollama`` — local Ollama model (via ``ollama_manager.query_ollama``).
    - ``claude`` — Anthropic Claude API (requires ``ANTHROPIC_API_KEY``).

Zero required dependencies — stdlib only. Optional: ``ollama_manager``
(for local provider), ``anthropic`` SDK (for Claude provider).
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# Add scripts/ to path for sibling imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── Constants ────────────────────────────────────────────────────────────────

VALID_STRATEGIES = ("single-judge", "majority-vote", "confidence-merge")
VALID_PROVIDERS = ("ollama", "claude")

# Maximum allowed length for a conflict ID used in file paths
_MAX_CONFLICT_ID_LEN = 64

DEFAULT_STRATEGY = "single-judge"
DEFAULT_PROVIDER = "ollama"
DEFAULT_CONFIDENCE_THRESHOLD = 0.8
DEFAULT_NUM_VOTES = 3
DEFAULT_MAX_PER_RUN = 10

def _sanitize_conflict_id(conflict_id: str) -> str:
    """Sanitize a conflict ID for safe use in file paths.

    Strips path separators and special characters to prevent path
    traversal attacks. Returns only alphanumeric chars, hyphens, and
    underscores, truncated to _MAX_CONFLICT_ID_LEN.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", str(conflict_id))
    return sanitized[:_MAX_CONFLICT_ID_LEN]


# ── Prompt Template ──────────────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """\
You are an impartial technical judge resolving a conflict between two \
memory entries written by different AI agents working on the same codebase.

Your task is to evaluate both positions and produce a reasoned verdict. \
Consider correctness, completeness, recency, and alignment with best \
practices.

Respond ONLY with valid JSON in the following format:
{
  "winner": "A" or "B" or "merged",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation of your decision>",
  "merged_content": "<if winner is 'merged', provide synthesized content>"
}
"""

JUDGE_USER_PROMPT_TEMPLATE = """\
## Conflict Details

**Field in conflict:** {field}
**Detected at:** {detected_iso}

### Entry A (by agent: {agent_a})
Session: {session_a}
Content:
```
{value_a}
```

### Entry B (by agent: {agent_b})
Session: {session_b}
Content:
```
{value_b}
```

Please evaluate both entries and provide your verdict as JSON.
"""


# ── Configuration Loader ─────────────────────────────────────────────────────

def load_auto_resolve_config(root: Path) -> dict:
    """Load auto_resolve config from memory_consistency section.

    Returns config dict with defaults applied.
    """
    config_paths = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]
    user_cfg = {}
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                user_cfg = data.get("memory_consistency", {}).get(
                    "auto_resolve", {}
                )
                break
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "enabled": user_cfg.get("enabled", False),
        "strategy": user_cfg.get("strategy", DEFAULT_STRATEGY),
        "provider": user_cfg.get("provider", DEFAULT_PROVIDER),
        "confidence_threshold": user_cfg.get(
            "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD
        ),
        "num_votes": user_cfg.get("num_votes", DEFAULT_NUM_VOTES),
        "max_auto_resolve_per_run": user_cfg.get(
            "max_auto_resolve_per_run", DEFAULT_MAX_PER_RUN
        ),
        "model": user_cfg.get("model", ""),
    }


# ── Judge Response Parser ────────────────────────────────────────────────────

def _parse_judge_response(text: str) -> Optional[dict]:
    """Parse a JSON verdict from the LLM judge response.

    Handles cases where the LLM wraps JSON in markdown code fences
    or adds preamble text.

    Returns None if parsing fails.
    """
    # Try direct JSON parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding a JSON object block (supports nested braces)
    brace_match = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _validate_verdict(verdict: dict) -> bool:
    """Check that a parsed verdict has the required fields."""
    if not isinstance(verdict, dict):
        return False
    winner = verdict.get("winner")
    if winner not in ("A", "B", "merged"):
        return False
    confidence = verdict.get("confidence")
    if not isinstance(confidence, (int, float)):
        return False
    if not (0.0 <= float(confidence) <= 1.0):
        return False
    if not verdict.get("reasoning"):
        return False
    if winner == "merged" and not verdict.get("merged_content"):
        return False
    return True


# ── LLM Providers ────────────────────────────────────────────────────────────

def _query_ollama(prompt: str, model: str = "") -> Optional[str]:
    """Query Ollama for a judge verdict.

    Returns the response text or None on failure.
    """
    try:
        from ollama_manager import query_ollama, is_available

        if not is_available():
            return None

        if not model:
            # Try to load configured model
            from ollama_manager import load_ollama_config
            config = load_ollama_config()
            model = config.get("model", "") if config else ""
        if not model:
            model = "qwen2.5-coder:7b"  # Sensible fallback

        result = query_ollama(
            model=model,
            prompt=prompt,
            system_prompt=JUDGE_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=1024,
        )
        if result.get("success"):
            return result.get("response", "")
    except ImportError:
        pass
    return None


def _query_claude(prompt: str, model: str = "") -> Optional[str]:
    """Query Claude API for a judge verdict.

    Requires ANTHROPIC_API_KEY environment variable.
    Returns the response text or None on failure.
    """
    import urllib.request
    import urllib.error

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    if not model:
        model = "claude-sonnet-4-20250514"

    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": JUDGE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content_blocks = result.get("content", [])
            if content_blocks:
                return content_blocks[0].get("text", "")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            json.JSONDecodeError):
        pass
    return None


# ── Conflict Judge ────────────────────────────────────────────────────────────

class ConflictJudge:
    """LLM-based conflict resolution engine.

    Evaluates contradictory memory entries using an LLM judge and
    selects or synthesizes a resolution.

    Args:
        root: Project root directory.
        provider: LLM provider ('ollama' or 'claude').
        model: Optional model override.
        confidence_threshold: For confidence-merge strategy.
        num_votes: Number of evaluations for majority-vote strategy.
    """

    def __init__(
        self,
        root: Path,
        provider: str = DEFAULT_PROVIDER,
        model: str = "",
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        num_votes: int = DEFAULT_NUM_VOTES,
    ):
        self.root = root
        self.provider = provider if provider in VALID_PROVIDERS else DEFAULT_PROVIDER
        self.model = model
        self.confidence_threshold = confidence_threshold
        self.num_votes = max(1, num_votes)

    @staticmethod
    def _sanitize_prompt_value(value: str, max_length: int = 2000) -> str:
        """Sanitize a value for safe inclusion in a judge prompt.

        Truncates to max_length and escapes backtick sequences that could
        break out of the code-fence delimiter in the prompt template.
        """
        value = str(value)[:max_length]
        # Escape triple backticks to prevent code-fence breakout
        value = value.replace("```", "` ` `")
        return value

    def _build_prompt(self, conflict: dict) -> str:
        """Build the user prompt for the judge from a conflict record dict."""
        return JUDGE_USER_PROMPT_TEMPLATE.format(
            field=self._sanitize_prompt_value(
                conflict.get("field", "unknown"), max_length=200
            ),
            detected_iso=conflict.get("detected_iso", "unknown"),
            agent_a=self._sanitize_prompt_value(
                conflict.get("entry_a_agent", "unknown"), max_length=200
            ),
            session_a=self._sanitize_prompt_value(
                conflict.get("entry_a_session", "unknown"), max_length=200
            ),
            value_a=self._sanitize_prompt_value(
                conflict.get("entry_a_value", "(empty)")
            ),
            agent_b=self._sanitize_prompt_value(
                conflict.get("entry_b_agent", "unknown"), max_length=200
            ),
            session_b=self._sanitize_prompt_value(
                conflict.get("entry_b_session", "unknown"), max_length=200
            ),
            value_b=self._sanitize_prompt_value(
                conflict.get("entry_b_value", "(empty)")
            ),
        )

    def _query(self, prompt: str) -> Optional[dict]:
        """Send a prompt to the configured LLM provider and parse the verdict."""
        if self.provider == "ollama":
            response = _query_ollama(prompt, self.model)
        elif self.provider == "claude":
            response = _query_claude(prompt, self.model)
        else:
            return None

        if not response:
            return None

        verdict = _parse_judge_response(response)
        if verdict and _validate_verdict(verdict):
            return verdict
        return None

    def single_judge(self, conflict: dict) -> dict:
        """Single LLM evaluation of a conflict.

        Args:
            conflict: Conflict record dict (from ConflictRecord.to_dict()).

        Returns:
            Resolution dict with keys: resolved, verdict, strategy, error.
        """
        prompt = self._build_prompt(conflict)
        verdict = self._query(prompt)

        if not verdict:
            return {
                "resolved": False,
                "verdict": None,
                "strategy": "single-judge",
                "error": "LLM judge failed to produce a valid verdict",
            }

        return {
            "resolved": True,
            "verdict": verdict,
            "strategy": "single-judge",
            "error": None,
        }

    def majority_vote(self, conflict: dict, num_votes: int = 0) -> dict:
        """Multiple LLM evaluations with majority selection.

        Args:
            conflict: Conflict record dict.
            num_votes: Number of votes (0 uses instance default).

        Returns:
            Resolution dict with verdict reflecting the majority winner.
        """
        votes = num_votes if num_votes > 0 else self.num_votes
        prompt = self._build_prompt(conflict)

        verdicts = []
        for _ in range(votes):
            verdict = self._query(prompt)
            if verdict:
                verdicts.append(verdict)

        if not verdicts:
            return {
                "resolved": False,
                "verdict": None,
                "strategy": "majority-vote",
                "votes_cast": 0,
                "votes_requested": votes,
                "error": "No valid verdicts from LLM judge",
            }

        # Count votes by winner
        winner_counts: dict[str, int] = {}
        for v in verdicts:
            w = v.get("winner", "")
            winner_counts[w] = winner_counts.get(w, 0) + 1

        # Find majority winner
        majority_winner = max(winner_counts, key=winner_counts.get)  # type: ignore[arg-type]
        majority_count = winner_counts[majority_winner]

        # Pick the verdict matching majority winner with highest confidence
        matching = [v for v in verdicts if v.get("winner") == majority_winner]
        best = dict(max(matching, key=lambda v: v.get("confidence", 0)))

        # Average confidence across matching verdicts
        avg_confidence = sum(
            v.get("confidence", 0) for v in matching
        ) / len(matching)
        best["confidence"] = round(avg_confidence, 3)

        return {
            "resolved": True,
            "verdict": best,
            "strategy": "majority-vote",
            "votes_cast": len(verdicts),
            "votes_requested": votes,
            "majority_count": majority_count,
            "vote_distribution": winner_counts,
            "error": None,
        }

    def confidence_merge(
        self, conflict: dict, threshold: float = 0.0
    ) -> dict:
        """Auto-merge if confidence exceeds threshold.

        First obtains a single-judge verdict, then checks if the
        confidence meets the threshold for automatic resolution.

        Args:
            conflict: Conflict record dict.
            threshold: Override threshold (0 uses instance default).

        Returns:
            Resolution dict. ``resolved`` is True only if confidence
            meets the threshold.
        """
        thresh = threshold if threshold > 0 else self.confidence_threshold
        prompt = self._build_prompt(conflict)
        verdict = self._query(prompt)

        if not verdict:
            return {
                "resolved": False,
                "verdict": None,
                "strategy": "confidence-merge",
                "threshold": thresh,
                "error": "LLM judge failed to produce a valid verdict",
            }

        confidence = float(verdict.get("confidence", 0))
        resolved = confidence >= thresh

        return {
            "resolved": resolved,
            "verdict": verdict,
            "strategy": "confidence-merge",
            "threshold": thresh,
            "confidence_met": resolved,
            "error": None if resolved else (
                f"Confidence {confidence:.2f} below threshold {thresh:.2f}"
            ),
        }

    def judge(self, conflict: dict, strategy: str = "") -> dict:
        """Evaluate a conflict using the specified strategy.

        Args:
            conflict: Conflict record dict (from ConflictRecord.to_dict()).
            strategy: One of 'single-judge', 'majority-vote',
                      'confidence-merge'. Empty string uses instance default
                      or config-based strategy.

        Returns:
            Resolution dict with keys: resolved, verdict, strategy, error,
            and strategy-specific metadata.
        """
        if not strategy or strategy not in VALID_STRATEGIES:
            import logging
            if strategy:
                logging.getLogger(__name__).warning(
                    "Invalid strategy %r, falling back to %s",
                    strategy, DEFAULT_STRATEGY,
                )
            strategy = DEFAULT_STRATEGY

        conflict_id = conflict.get("conflict_id", "unknown")

        if strategy == "single-judge":
            result = self.single_judge(conflict)
        elif strategy == "majority-vote":
            result = self.majority_vote(conflict)
        else:  # confidence-merge (guaranteed by VALID_STRATEGIES guard)
            result = self.confidence_merge(conflict)

        result["conflict_id"] = conflict_id
        result["judged_at"] = time.time()
        result["judged_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(result["judged_at"])
        )
        result["provider"] = self.provider

        return result


# ── Batch Resolution ──────────────────────────────────────────────────────────

def batch_resolve(
    root: Path,
    strategy: str = DEFAULT_STRATEGY,
    provider: str = DEFAULT_PROVIDER,
    model: str = "",
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    num_votes: int = DEFAULT_NUM_VOTES,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    dry_run: bool = False,
) -> dict:
    """Batch-process pending opinion conflicts through the LLM judge.

    Args:
        root: Project root directory.
        strategy: Resolution strategy.
        provider: LLM provider.
        model: Optional model override.
        confidence_threshold: For confidence-merge strategy.
        num_votes: For majority-vote strategy.
        max_per_run: Maximum conflicts to process per invocation.
        dry_run: If True, evaluate but do not mark as resolved.

    Returns:
        Summary dict with counts and per-conflict results.
    """
    try:
        from memory_protocol import ConflictResolver
    except ImportError:
        return {
            "success": False,
            "error": "memory_protocol module not available",
            "processed": 0,
            "resolved": 0,
        }

    resolver = ConflictResolver(root)
    pending = resolver.list_conflicts(resolved=False)

    # Filter to opinion-type conflicts only
    opinion_conflicts = [
        c for c in pending
        if c.get("resolution") == "flag-for-review"
    ]

    # Cap at max_per_run
    to_process = opinion_conflicts[:max_per_run]

    if not to_process:
        return {
            "success": True,
            "processed": 0,
            "resolved": 0,
            "skipped": 0,
            "total_pending": len(pending),
            "opinion_pending": 0,
            "dry_run": dry_run,
            "results": [],
        }

    judge = ConflictJudge(
        root=root,
        provider=provider,
        model=model,
        confidence_threshold=confidence_threshold,
        num_votes=num_votes,
    )

    results = []
    resolved_count = 0
    skipped_count = 0

    for conflict in to_process:
        result = judge.judge(conflict, strategy=strategy)
        result["dry_run"] = dry_run

        if result.get("resolved") and not dry_run:
            # Mark the conflict as resolved on disk
            conflict_id = _sanitize_conflict_id(
                conflict.get("conflict_id", "")
            )
            if conflict_id:
                success = resolver.resolve_conflict_by_id(conflict_id)
                result["persisted"] = success
                if success:
                    # Save the judge's resolution metadata alongside
                    _save_resolution_metadata(root, conflict_id, result)
                    resolved_count += 1
                else:
                    skipped_count += 1
            else:
                skipped_count += 1
        elif result.get("resolved") and dry_run:
            resolved_count += 1  # Would have resolved
        else:
            skipped_count += 1

        results.append(result)

    return {
        "success": True,
        "processed": len(results),
        "resolved": resolved_count,
        "skipped": skipped_count,
        "total_pending": len(pending),
        "opinion_pending": len(opinion_conflicts),
        "dry_run": dry_run,
        "strategy": strategy,
        "provider": provider,
        "results": results,
    }


def _save_resolution_metadata(root: Path, conflict_id: str, result: dict):
    """Save judge resolution metadata alongside the conflict file."""
    safe_id = _sanitize_conflict_id(conflict_id)
    if not safe_id:
        return
    conflicts_dir = root / ".claude" / "memory" / "conflicts"
    meta_path = conflicts_dir / f"{safe_id}.resolution.json"
    try:
        meta = {
            "conflict_id": conflict_id,
            "strategy": result.get("strategy", ""),
            "provider": result.get("provider", ""),
            "verdict": result.get("verdict", {}),
            "judged_at": result.get("judged_at", 0),
            "judged_iso": result.get("judged_iso", ""),
            "resolution_method": "auto-judge",
        }
        meta_path.write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
