#!/usr/bin/env bash
# setup-github-labels.sh — Create all required GitHub labels for the task/idea workflow.
# Reads configuration from .claude/github-issues.json.
#
# Usage:
#   bash scripts/setup-github-labels.sh
#
# Prerequisites:
#   - gh CLI installed and authenticated (gh auth status)
#   - jq installed
#   - .claude/github-issues.json exists with "repo" configured

set -euo pipefail

CONFIG=".claude/github-issues.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG not found. Copy .claude/github-issues.example.json to $CONFIG and configure it."
  exit 1
fi

REPO=$(jq -r '.repo' "$CONFIG")
if [ -z "$REPO" ] || [ "$REPO" = "null" ] || [ "$REPO" = "owner/repo" ]; then
  echo "ERROR: 'repo' is not configured in $CONFIG. Set it to your GitHub repository (e.g., 'user/project')."
  exit 1
fi

echo "Setting up labels for repository: $REPO"
echo "---"

create_label() {
  local name="$1"
  local color="$2"
  local description="${3:-}"
  if gh label create "$name" --repo "$REPO" --color "$color" --description "$description" 2>/dev/null; then
    echo "  Created: $name"
  else
    echo "  Exists:  $name"
  fi
}

# Source label
SOURCE=$(jq -r '.labels.source' "$CONFIG")
create_label "$SOURCE" "0052cc" "Created by Claude Code"

# Type labels
TASK_LABEL=$(jq -r '.labels.task' "$CONFIG")
IDEA_LABEL=$(jq -r '.labels.idea' "$CONFIG")
create_label "$TASK_LABEL" "1d76db" "Task work item"
create_label "$IDEA_LABEL" "5319e7" "Idea proposal"

# Priority labels
echo ""
echo "Priority labels:"
for key in $(jq -r '.labels.priority | keys[]' "$CONFIG"); do
  label=$(jq -r ".labels.priority[\"$key\"]" "$CONFIG")
  case "$key" in
    HIGH)  color="d73a4a" ;;
    MEDIUM) color="fbca04" ;;
    LOW)   color="0e8a16" ;;
    *)     color="ededed" ;;
  esac
  create_label "$label" "$color" "Priority: $key"
done

# Status labels
echo ""
echo "Status labels:"
for key in $(jq -r '.labels.status | keys[]' "$CONFIG"); do
  label=$(jq -r ".labels.status[\"$key\"]" "$CONFIG")
  case "$key" in
    todo)        color="cfd3d7" ;;
    in-progress) color="fbca04" ;;
    done)        color="0e8a16" ;;
    *)           color="ededed" ;;
  esac
  create_label "$label" "$color" "Status: $key"
done

# Section labels (if any configured)
SECTIONS_COUNT=$(jq '.labels.sections | length' "$CONFIG")
if [ "$SECTIONS_COUNT" -gt 0 ]; then
  echo ""
  echo "Section labels:"
  for key in $(jq -r '.labels.sections | keys[]' "$CONFIG"); do
    label=$(jq -r ".labels.sections[\"$key\"]" "$CONFIG")
    create_label "$label" "c5def5" "Section: $key"
  done
fi

echo ""
echo "Done! All labels are set up for $REPO."
