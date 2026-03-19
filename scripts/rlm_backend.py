#!/usr/bin/env python3
"""RLM-style recursive context processing backend for CodeClaw.

Implements a MemoryBackend interface for Recursive Language Model (RLM) style
processing. When contexts exceed the model's window, the system decomposes
queries into sub-queries, processes context slices recursively, and aggregates
results using configurable strategies.

Supports both local (Ollama) and cloud (Claude API) LLM backends for the
recursive processing, with configurable depth limits, chunk overlap strategies,
and aggregation methods.

Strategies:
    map-reduce         Parallel decomposition + merge of sub-results
    iterative-refinement  Sequential deepening of analysis
    tree               Recursive binary split of context

Zero external dependencies — stdlib only (Ollama/Claude accessed via HTTP).
"""

import json
import os
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# Add scripts/ to path for sibling imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_CONTEXT_MB = 10
DEFAULT_AGGREGATION = "map-reduce"
DEFAULT_TIMEOUT = 120
DEFAULT_PROVIDER = "ollama"

VALID_STRATEGIES = ("map-reduce", "iterative-refinement", "tree")

# Maximum total LLM calls to prevent combinatorial explosion (O1)
MAX_LLM_CALLS = 50

# Chunk overlap for context splitting (percentage of chunk size)
CHUNK_OVERLAP_RATIO = 0.1

# RLM model recommendations — imported from canonical source in ollama_manager
try:
    from ollama_manager import RLM_MODEL_RECOMMENDATIONS
except ImportError:
    RLM_MODEL_RECOMMENDATIONS = {"ollama": [], "claude": []}


# ── Configuration ────────────────────────────────────────────────────────────

def load_rlm_config(root: Path) -> dict:
    """Load RLM configuration from project-config.json.

    Reads the vector_memory.rlm section. Returns defaults if not configured.
    """
    config_paths = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                vm = data.get("vector_memory", {})
                return vm.get("rlm", {})
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def get_effective_rlm_config(root: Optional[Path] = None) -> dict:
    """Return effective RLM config with defaults applied.

    Args:
        root: Project root. If None, auto-detected.

    Returns:
        Dict with all RLM configuration keys populated.
    """
    if root is None:
        root = _find_project_root()
    user_cfg = load_rlm_config(root)
    return {
        "enabled": user_cfg.get("enabled", False),
        "provider": user_cfg.get("provider", DEFAULT_PROVIDER),
        "max_depth": user_cfg.get("max_depth", DEFAULT_MAX_DEPTH),
        "max_context_mb": user_cfg.get("max_context_mb", DEFAULT_MAX_CONTEXT_MB),
        "aggregation": user_cfg.get("aggregation", DEFAULT_AGGREGATION),
        "timeout_seconds": user_cfg.get("timeout_seconds", DEFAULT_TIMEOUT),
    }


def _find_project_root() -> Path:
    """Find project root by looking for .claude/ or .git/."""
    d = Path.cwd()
    while d != d.parent:
        if (d / ".claude").is_dir() or (d / ".git").exists():
            return d
        d = d.parent
    return Path.cwd()


# ── Context Management ───────────────────────────────────────────────────────

def chunk_context(context: str, max_chunk_size: int,
                  overlap_ratio: float = CHUNK_OVERLAP_RATIO) -> list[str]:
    """Split context into overlapping chunks for recursive processing.

    Args:
        context: Full context string to split.
        max_chunk_size: Maximum characters per chunk.
        overlap_ratio: Fraction of overlap between consecutive chunks.

    Returns:
        List of context chunks with overlap.
    """
    if len(context) <= max_chunk_size:
        return [context]

    overlap_size = int(max_chunk_size * overlap_ratio)
    step_size = max(1, max_chunk_size - overlap_size)
    chunks = []

    for i in range(0, len(context), step_size):
        chunk = context[i:i + max_chunk_size]
        if chunk:
            chunks.append(chunk)
        if i + max_chunk_size >= len(context):
            break

    return chunks


def prepare_context_slices(context_data: dict,
                           max_size_mb: float = DEFAULT_MAX_CONTEXT_MB
                           ) -> list[dict]:
    """Prepare context data into manageable slices.

    If the total context exceeds max_size_mb, it is split into slices
    that can each be processed independently.

    Args:
        context_data: Dict mapping file paths to their content.
        max_size_mb: Maximum size in MB per slice.

    Returns:
        List of context slice dicts.
    """
    max_bytes = int(max_size_mb * 1024 * 1024)
    serialized = json.dumps(context_data)

    if len(serialized.encode("utf-8")) <= max_bytes:
        return [context_data]

    # Split by files into approximately equal slices
    slices = []
    current_slice = {}
    current_size = 0

    for path, content in context_data.items():
        entry_size = len(json.dumps({path: content}).encode("utf-8"))
        if current_size + entry_size > max_bytes and current_slice:
            slices.append(current_slice)
            current_slice = {}
            current_size = 0
        current_slice[path] = content
        current_size += entry_size

    if current_slice:
        slices.append(current_slice)

    return slices if slices else [context_data]


# ── LLM Providers ───────────────────────────────────────────────────────────

def _query_ollama(prompt: str, model: str = "qwen2.5-coder:7b",
                  timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Query Ollama for RLM processing.

    Args:
        prompt: The prompt to send.
        model: Ollama model name.
        timeout: Request timeout in seconds.

    Returns:
        Dict with 'success', 'response', and optional 'error'.
    """
    try:
        from ollama_manager import query_ollama
        return query_ollama(
            model=model,
            prompt=prompt,
            temperature=0.1,
            max_tokens=4096,
        )
    except ImportError:
        # Fallback: direct HTTP call
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 4096},
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return {
                    "success": True,
                    "response": result.get("response", ""),
                }
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            return {"success": False, "response": "", "error": str(e)}


def _query_claude(prompt: str, model: str = "claude-sonnet-4-20250514",
                  timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Query Claude API for RLM processing.

    Requires ANTHROPIC_API_KEY environment variable.

    Args:
        prompt: The prompt to send.
        model: Claude model identifier.
        timeout: Request timeout in seconds.

    Returns:
        Dict with 'success', 'response', and optional 'error'.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "success": False,
            "response": "",
            "error": "ANTHROPIC_API_KEY not set",
        }

    payload = {
        "model": model,
        "max_tokens": 4096,
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result.get("content", [])
            text = content[0].get("text", "") if content else ""
            return {"success": True, "response": text}
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return {"success": False, "response": "", "error": str(e)}


def query_llm(prompt: str, config: dict) -> dict:
    """Route a query to the configured LLM provider.

    Args:
        prompt: The prompt to send.
        config: Effective RLM configuration.

    Returns:
        Dict with 'success', 'response', and optional 'error'.
    """
    provider = config.get("provider", DEFAULT_PROVIDER)
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT)

    if provider == "claude":
        return _query_claude(prompt, timeout=timeout)
    else:
        return _query_ollama(prompt, timeout=timeout)


# ── Core RLM Operations ─────────────────────────────────────────────────────

def decompose(query: str, context_summary: str, config: dict) -> list[str]:
    """Decompose a complex query into sub-queries using the LLM.

    The LLM analyzes the query and context to produce focused sub-queries
    that can each be answered from smaller context slices.

    Args:
        query: The original complex query.
        context_summary: Brief summary of available context.
        config: Effective RLM configuration.

    Returns:
        List of sub-query strings. Returns [query] if decomposition fails.
    """
    # Prompt injection: inherent to LLM-in-the-loop; mitigated by sandbox validation of generated code
    prompt = textwrap.dedent(f"""\
        You are decomposing a complex query into simpler sub-queries for
        recursive analysis of a large codebase context.

        Original query: {query}

        Context summary: {context_summary}

        Break this into 2-5 focused sub-queries that together answer the
        original query. Each sub-query should be answerable from a subset
        of the context.

        Output ONLY a JSON array of sub-query strings, nothing else.
        Example: ["What functions handle authentication?", "How is session state managed?"]
    """)

    result = query_llm(prompt, config)
    if not result.get("success"):
        return [query]

    try:
        response = result["response"].strip()
        # Extract JSON array from response
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            sub_queries = json.loads(response[start:end])
            if isinstance(sub_queries, list) and all(isinstance(q, str) for q in sub_queries):
                return sub_queries if sub_queries else [query]
    except (json.JSONDecodeError, ValueError):
        pass

    return [query]


def _analyze_chunk(query: str, context_chunk: str, config: dict) -> dict:
    """Analyze a single context chunk against a query.

    This is the leaf operation in the recursive processing tree.

    Args:
        query: The query to answer.
        context_chunk: The context chunk to analyze.
        config: Effective RLM configuration.

    Returns:
        Dict with 'findings' (list of strings) and 'relevance' (float 0-1).
    """
    # Try executor-based analysis first
    try:
        from rlm_executor import execute_analysis, build_analysis_prompt

        # Build analysis code prompt
        analysis_prompt = build_analysis_prompt(
            query, {"type": "text", "length": len(context_chunk)}
        )
        code_result = query_llm(analysis_prompt, config)

        if code_result.get("success") and code_result.get("response"):
            # Extract code from response (strip markdown fences if present)
            code = code_result["response"].strip()
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            exec_result = execute_analysis(
                context_data=context_chunk,
                analysis_code=code,
                timeout_seconds=min(30, config.get("timeout_seconds", 30)),
            )

            if exec_result.success and exec_result.results:
                findings = []
                for r in exec_result.results:
                    if isinstance(r, dict):
                        findings.append(r.get("content", str(r)))
                    else:
                        findings.append(str(r))
                return {"findings": findings, "relevance": 0.8}
    except (ImportError, Exception):
        pass

    # Fallback: direct LLM analysis
    # Prompt injection: inherent to LLM-in-the-loop; mitigated by sandbox validation of generated code
    prompt = textwrap.dedent(f"""\
        Analyze the following context to answer this query.

        Query: {query}

        Context (truncated to first 8000 chars):
        {context_chunk[:8000]}

        Provide your findings as a JSON object with:
        - "findings": list of key findings (strings)
        - "relevance": float 0-1 indicating how relevant this context is

        Output ONLY valid JSON, nothing else.
    """)

    result = query_llm(prompt, config)
    if not result.get("success"):
        return {"findings": [], "relevance": 0.0}

    try:
        response = result["response"].strip()
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(response[start:end])
            return {
                "findings": parsed.get("findings", []),
                "relevance": float(parsed.get("relevance", 0.5)),
            }
    except (json.JSONDecodeError, ValueError):
        pass

    return {"findings": [result.get("response", "")[:500]], "relevance": 0.3}


# ── Aggregation Strategies ───────────────────────────────────────────────────

def aggregate(results: list[dict], strategy: str = DEFAULT_AGGREGATION,
              config: Optional[dict] = None) -> dict:
    """Merge sub-query results using the specified aggregation strategy.

    Args:
        results: List of result dicts, each with 'findings' and 'relevance'.
        strategy: One of 'map-reduce', 'iterative-refinement', 'tree'.
        config: Optional RLM config for LLM-assisted aggregation.

    Returns:
        Aggregated result dict with 'findings', 'relevance', and 'strategy'.
    """
    if not results:
        return {"findings": [], "relevance": 0.0, "strategy": strategy}

    if strategy == "map-reduce":
        return _aggregate_map_reduce(results, config)
    elif strategy == "iterative-refinement":
        return _aggregate_iterative(results, config)
    elif strategy == "tree":
        return _aggregate_tree(results, config)
    else:
        return _aggregate_map_reduce(results, config)


def _aggregate_map_reduce(results: list[dict],
                          config: Optional[dict] = None) -> dict:
    """Map-reduce aggregation: collect all findings, deduplicate, rank.

    Combines all findings from parallel sub-queries, removes duplicates,
    and orders by relevance.
    """
    all_findings = []
    total_relevance = 0.0

    for r in results:
        findings = r.get("findings", [])
        relevance = r.get("relevance", 0.5)
        for f in findings:
            all_findings.append({"text": f, "relevance": relevance})
        total_relevance += relevance

    # Deduplicate by content similarity (exact match for now)
    seen = set()
    unique_findings = []
    for f in all_findings:
        text = f["text"].strip()
        if text and text not in seen:
            seen.add(text)
            unique_findings.append(f)

    # Sort by relevance
    unique_findings.sort(key=lambda x: x["relevance"], reverse=True)

    avg_relevance = total_relevance / len(results) if results else 0.0

    return {
        "findings": [f["text"] for f in unique_findings],
        "relevance": avg_relevance,
        "strategy": "map-reduce",
        "source_count": len(results),
    }


def _aggregate_iterative(results: list[dict],
                         config: Optional[dict] = None) -> dict:
    """Iterative refinement: sequentially refine findings.

    Each result builds on and refines the previous one.
    """
    refined_findings = []

    for i, r in enumerate(results):
        new_findings = r.get("findings", [])
        if i == 0:
            refined_findings = list(new_findings)
        else:
            # Add non-duplicate findings
            existing = set(f.strip() for f in refined_findings)
            for f in new_findings:
                if f.strip() and f.strip() not in existing:
                    refined_findings.append(f)
                    existing.add(f.strip())

    relevances = [r.get("relevance", 0.5) for r in results]
    max_relevance = max(relevances) if relevances else 0.0

    return {
        "findings": refined_findings,
        "relevance": max_relevance,
        "strategy": "iterative-refinement",
        "refinement_steps": len(results),
    }


def _aggregate_tree(results: list[dict],
                    config: Optional[dict] = None) -> dict:
    """Tree aggregation: recursive binary merge of results.

    Pairs adjacent results and merges them, repeating until a single
    result remains.
    """
    if len(results) <= 1:
        if results:
            return {**results[0], "strategy": "tree"}
        return {"findings": [], "relevance": 0.0, "strategy": "tree"}

    # Binary merge: pair adjacent results
    merged = []
    for i in range(0, len(results), 2):
        if i + 1 < len(results):
            # Merge pair
            combined_findings = list(results[i].get("findings", []))
            seen = set(f.strip() for f in combined_findings)
            for f in results[i + 1].get("findings", []):
                if f.strip() and f.strip() not in seen:
                    combined_findings.append(f)
                    seen.add(f.strip())
            merged_relevance = max(
                results[i].get("relevance", 0),
                results[i + 1].get("relevance", 0),
            )
            merged.append({
                "findings": combined_findings,
                "relevance": merged_relevance,
            })
        else:
            merged.append(results[i])

    # Recurse until single result
    if len(merged) > 1:
        return _aggregate_tree(merged, config)

    return {**merged[0], "strategy": "tree"}


# ── Main Search Interface ───────────────────────────────────────────────────

def search(
    query: str,
    context_paths: Optional[list[str]] = None,
    context_data: Optional[dict] = None,
    max_depth: Optional[int] = None,
    aggregation: Optional[str] = None,
    config: Optional[dict] = None,
) -> dict:
    """Perform RLM-style recursive search over context.

    This is the main entry point for the RLM backend. It:
    1. Loads or receives context data
    2. Decomposes the query if context is large
    3. Recursively processes context slices
    4. Aggregates results using the configured strategy

    Args:
        query: The search query.
        context_paths: Optional list of file paths to load as context.
        context_data: Pre-loaded context data (dict mapping paths to content).
        max_depth: Maximum recursion depth (overrides config).
        aggregation: Aggregation strategy (overrides config).
        config: RLM configuration (auto-loaded if None).

    Returns:
        Dict with 'success', 'findings', 'metadata'.
    """
    start_time = time.time()

    if config is None:
        config = get_effective_rlm_config()

    if max_depth is None:
        max_depth = config.get("max_depth", DEFAULT_MAX_DEPTH)
    if aggregation is None:
        aggregation = config.get("aggregation", DEFAULT_AGGREGATION)

    if aggregation not in VALID_STRATEGIES:
        aggregation = DEFAULT_AGGREGATION

    # Resolve max_context_mb early so it is available for file-read limits
    max_context_mb = config.get("max_context_mb", DEFAULT_MAX_CONTEXT_MB)

    # Load context from files if paths provided
    # Cap per-file read to avoid OOM from symlinks or huge files (S7)
    max_file_bytes = int(max_context_mb * 1024 * 1024)
    if context_data is None:
        context_data = {}
        if context_paths:
            for fpath in context_paths:
                try:
                    p = Path(fpath)
                    # Skip symlinks and files exceeding the context budget
                    if p.is_symlink():
                        continue
                    if p.stat().st_size > max_file_bytes:
                        print(
                            f"  RLM: Skipping {fpath} "
                            f"({p.stat().st_size / (1024*1024):.1f} MB > "
                            f"{max_context_mb} MB limit)",
                            file=sys.stderr,
                        )
                        continue
                    content = p.read_text(encoding="utf-8", errors="replace")
                    context_data[fpath] = content
                except OSError:
                    continue

    if not context_data:
        return {
            "success": False,
            "findings": [],
            "metadata": {"error": "No context data provided"},
        }

    # Check context size (estimate without full serialization to avoid O(n) copy)
    context_size_bytes = sum(
        len(k.encode("utf-8")) + len(v.encode("utf-8"))
        for k, v in context_data.items()
    )
    context_size_mb = context_size_bytes / (1024 * 1024)

    if context_size_mb > max_context_mb:
        print(
            f"  RLM: Context ({context_size_mb:.1f} MB) exceeds limit "
            f"({max_context_mb} MB), splitting...",
            file=sys.stderr,
        )

    # Prepare context slices
    slices = prepare_context_slices(context_data, max_context_mb)

    # Perform recursive search with call budget to prevent explosion (O1)
    call_counter = [0]  # mutable counter shared across recursion
    result = _recursive_search(
        query=query,
        context_slices=slices,
        depth=0,
        max_depth=max_depth,
        aggregation=aggregation,
        config=config,
        call_counter=call_counter,
    )

    elapsed = time.time() - start_time

    return {
        "success": True,
        "findings": result.get("findings", []),
        "metadata": {
            "strategy": aggregation,
            "depth_used": min(max_depth, len(slices)),
            "slices_processed": len(slices),
            "context_size_mb": round(context_size_mb, 2),
            "elapsed_seconds": round(elapsed, 2),
            "provider": config.get("provider", DEFAULT_PROVIDER),
        },
    }


def _recursive_search(
    query: str,
    context_slices: list[dict],
    depth: int,
    max_depth: int,
    aggregation: str,
    config: dict,
    call_counter: Optional[list] = None,
) -> dict:
    """Internal recursive search implementation.

    At each level of recursion:
    - If we have a single small slice, analyze it directly
    - If we have multiple slices, decompose and process each
    - Aggregate results at each level

    Args:
        query: Current query (may be a sub-query).
        context_slices: List of context dicts to process.
        depth: Current recursion depth.
        max_depth: Maximum allowed depth.
        aggregation: Aggregation strategy.
        config: RLM configuration.
        call_counter: Mutable list [count] tracking total LLM calls to
            prevent combinatorial explosion.

    Returns:
        Aggregated result dict.
    """
    if call_counter is None:
        call_counter = [0]

    # Base case: max depth reached or single small slice
    # Sequential: thread safety of LLM client not guaranteed; parallelization deferred pending client audit
    if depth >= max_depth or len(context_slices) <= 1:
        results = []
        for ctx_slice in context_slices:
            if call_counter[0] >= MAX_LLM_CALLS:
                break
            context_text = json.dumps(ctx_slice) if isinstance(ctx_slice, dict) else str(ctx_slice)
            chunk_result = _analyze_chunk(query, context_text, config)
            call_counter[0] += 1
            results.append(chunk_result)
        return aggregate(results, aggregation, config)

    # Budget check before decomposition
    if call_counter[0] >= MAX_LLM_CALLS:
        return {"findings": ["LLM call budget exhausted"], "relevance": 0.1}

    # Recursive case: decompose query and process slices
    context_summary = f"{len(context_slices)} slices, depth {depth}/{max_depth}"
    sub_queries = decompose(query, context_summary, config)
    call_counter[0] += 1  # decompose uses one LLM call

    all_results = []
    for sub_query in sub_queries:
        for ctx_slice in context_slices:
            if call_counter[0] >= MAX_LLM_CALLS:
                break
            # Further split if needed
            sub_slices = prepare_context_slices(
                ctx_slice,
                config.get("max_context_mb", DEFAULT_MAX_CONTEXT_MB) / 2,
            )
            sub_result = _recursive_search(
                query=sub_query,
                context_slices=sub_slices,
                depth=depth + 1,
                max_depth=max_depth,
                aggregation=aggregation,
                config=config,
                call_counter=call_counter,
            )
            all_results.append(sub_result)

    return aggregate(all_results, aggregation, config)


def get_model_recommendations(provider: str = "ollama") -> list[dict]:
    """Get RLM-specific model recommendations for the given provider.

    Args:
        provider: 'ollama' or 'claude'.

    Returns:
        List of model recommendation dicts.
    """
    return RLM_MODEL_RECOMMENDATIONS.get(provider, [])


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """CLI entry point for the RLM backend."""
    import argparse

    parser = argparse.ArgumentParser(
        description="RLM-style recursive context processing backend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s search "How does authentication work?" --files src/auth.py src/session.py
              %(prog)s search "Find security vulnerabilities" --files src/ --strategy tree
              %(prog)s decompose "Complex query" --context-summary "50 files, 10MB"
              %(prog)s recommend --provider ollama
              %(prog)s config
        """),
    )
    sub = parser.add_subparsers(dest="command")

    # search
    s = sub.add_parser("search", help="RLM recursive search over files")
    s.add_argument("query", help="Search query")
    s.add_argument("--files", nargs="+", default=[],
                   help="File paths to include as context")
    s.add_argument("--strategy", choices=VALID_STRATEGIES,
                   default=None, help="Aggregation strategy")
    s.add_argument("--max-depth", type=int, default=None,
                   help="Maximum recursion depth")
    s.add_argument("--json", dest="json_output", action="store_true",
                   help="Output as JSON")

    # decompose
    d = sub.add_parser("decompose", help="Decompose a query into sub-queries")
    d.add_argument("query", help="Query to decompose")
    d.add_argument("--context-summary", default="",
                   help="Brief context summary")

    # recommend
    r = sub.add_parser("recommend",
                       help="Get RLM model recommendations")
    r.add_argument("--provider", default="ollama",
                   choices=["ollama", "claude"],
                   help="LLM provider")

    # config
    sub.add_parser("config", help="Show effective RLM configuration")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "search":
        result = search(
            query=args.query,
            context_paths=args.files,
            max_depth=args.max_depth,
            aggregation=args.strategy,
        )
        if getattr(args, "json_output", False):
            print(json.dumps(result, indent=2))
        else:
            if result["success"]:
                print(f"RLM Search Results ({result['metadata']['strategy']}):")
                print(f"  Slices: {result['metadata']['slices_processed']}")
                print(f"  Time: {result['metadata']['elapsed_seconds']}s")
                print()
                for i, finding in enumerate(result["findings"], 1):
                    print(f"  {i}. {finding}")
            else:
                print(f"Error: {result['metadata'].get('error', 'Unknown')}")
                sys.exit(1)

    elif args.command == "decompose":
        config = get_effective_rlm_config()
        sub_queries = decompose(args.query, args.context_summary, config)
        print(json.dumps(sub_queries, indent=2))

    elif args.command == "recommend":
        recs = get_model_recommendations(args.provider)
        print(json.dumps(recs, indent=2))

    elif args.command == "config":
        config = get_effective_rlm_config()
        print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
