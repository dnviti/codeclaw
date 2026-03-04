#!/usr/bin/env bash
# =============================================================================
# Task Manager Hook for Claude Code
# Analyzes modified files and shows correlated tasks from to-do.txt
# =============================================================================

# Find project root: try git first, otherwise walk up looking for to-do.txt
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$PROJECT_ROOT" ]; then
  SEARCH_DIR="$(pwd)"
  while [ "$SEARCH_DIR" != "/" ] && [ "$SEARCH_DIR" != "" ]; do
    if [ -f "$SEARCH_DIR/to-do.txt" ]; then
      PROJECT_ROOT="$SEARCH_DIR"
      break
    fi
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
  done
fi

TODO_FILE="$PROJECT_ROOT/to-do.txt"
PROGRESS_FILE="$PROJECT_ROOT/progressing.txt"
DONE_FILE="$PROJECT_ROOT/done.txt"

if [ ! -f "$TODO_FILE" ]; then
  exit 0
fi

# Sanitize files (remove Windows \r) into variables
TODO_CONTENT="$(tr -d '\r' < "$TODO_FILE")"
PROGRESS_CONTENT=""
DONE_CONTENT=""
[ -f "$PROGRESS_FILE" ] && PROGRESS_CONTENT="$(tr -d '\r' < "$PROGRESS_FILE")"
[ -f "$DONE_FILE" ] && DONE_CONTENT="$(tr -d '\r' < "$DONE_FILE")"

# ---------------------------------------------------------------------------
# Map: file pattern -> task code
# [TODO: Populate this map with your project's file-to-task associations]
# Example:
#   ["auth.service.ts"]="AUTH-001"
#   ["LoginPage.tsx"]="AUTH-001"
#   ["dashboard.tsx"]="UI-002"
# ---------------------------------------------------------------------------
declare -A FILE_TASK_MAP=(
  # Add your file-to-task mappings here
)

# ---------------------------------------------------------------------------
# Task descriptions
# [TODO: Populate with your task code descriptions]
# Example:
#   ["AUTH-001"]="User authentication"
#   ["UI-002"]="Dashboard layout"
# ---------------------------------------------------------------------------
declare -A TASK_NAMES=(
  # Add your task descriptions here
)

# ---------------------------------------------------------------------------
# Function: extract task status from task files
# ---------------------------------------------------------------------------
get_task_status() {
  local code="$1"
  local line

  # Search in done.txt first (completed)
  if [ -n "$DONE_CONTENT" ]; then
    line=$(echo "$DONE_CONTENT" | grep -E "^\[x\] ${code}" | head -1)
    if [ -n "$line" ]; then
      echo "COMPLETED"
      return
    fi
  fi

  # Search in progressing.txt (in-progress)
  if [ -n "$PROGRESS_CONTENT" ]; then
    line=$(echo "$PROGRESS_CONTENT" | grep -E "^\[~\] ${code}" | head -1)
    if [ -n "$line" ]; then
      echo "IN PROGRESS"
      return
    fi
  fi

  # Search in to-do.txt (pending/blocked)
  line=$(echo "$TODO_CONTENT" | grep -E "^\[.\] ${code}" | head -1)
  if [ -z "$line" ]; then
    line=$(echo "$TODO_CONTENT" | grep -B1 "$code" | grep -E '^\[' | head -1)
  fi
  if echo "$line" | grep -q '\[!\]'; then
    echo "BLOCKED"
  elif echo "$line" | grep -q '\[ \]'; then
    echo "TODO"
  else
    echo "N/A"
  fi
}

# ---------------------------------------------------------------------------
# Function: count tasks by status
# ---------------------------------------------------------------------------
show_summary() {
  local done progress todo blocked total pct

  # Count from the correct files
  done=$(echo "$DONE_CONTENT" | grep -cE '^\[x\] [A-Z0-9]' || true)
  progress=$(echo "$PROGRESS_CONTENT" | grep -cE '^\[~\] [A-Z0-9]' || true)
  todo=$(echo "$TODO_CONTENT" | grep -cE '^\[ \] [A-Z0-9]' || true)
  blocked=$(echo "$TODO_CONTENT" | grep -cE '^\[!\] [A-Z0-9]' || true)

  # Remove stray whitespace/newlines
  done=${done//[^0-9]/}
  progress=${progress//[^0-9]/}
  todo=${todo//[^0-9]/}
  blocked=${blocked//[^0-9]/}

  # Default to 0 if empty
  done=${done:-0}
  progress=${progress:-0}
  todo=${todo:-0}
  blocked=${blocked:-0}

  total=$((done + progress + todo + blocked))

  echo ""
  echo "=== TASK SUMMARY ==="
  echo "  Completed:   $done/$total"
  echo "  In progress: $progress"
  echo "  Todo:        $todo"
  echo "  Blocked:     $blocked"
  if [ "$total" -gt 0 ]; then
    pct=$((done * 100 / total))
    echo "  Progress:    ${pct}%"
  fi
  echo "====================="
}

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
main() {
  local modified_file="$1"

  if [ -z "$modified_file" ]; then
    show_summary
    exit 0
  fi

  local filename
  filename=$(basename "$modified_file")

  local task_code="${FILE_TASK_MAP[$filename]}"

  if [ -n "$task_code" ]; then
    local task_name="${TASK_NAMES[$task_code]}"
    local task_status
    task_status=$(get_task_status "$task_code")

    echo ""
    echo "--- Related Task ---"
    echo "  File:   $modified_file"
    echo "  Task:   [$task_code] $task_name"
    echo "  Status: $task_status"
    echo "--------------------"
  fi

  show_summary
}

main "$@"
