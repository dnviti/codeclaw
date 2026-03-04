---
name: app-stop
description: Stop the project's development environment. Kills dev server processes and optionally stops Docker containers.
disable-model-invocation: true
allowed-tools: Bash
---

# Stop the Application

You are a DevOps operator for this project. Your job is to cleanly stop the development environment.

## Current Environment State

### Listening ports:
!`lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | awk '{print $1, $2, $9}' | tail -20 || echo "No listening ports found"`

> Cross-reference the ports above against the `DEV_PORTS` configured in CLAUDE.md to identify which belong to this project.

### Docker containers:
!`docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Docker not available or no containers running"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Check if the app is running

Examine the environment state above. The app is considered "running" if **any** dev ports are in use.

**If no dev ports are in use and no Docker containers are running:**
- Inform the user: "The application does not appear to be running. Nothing to stop."
- Stop here.

**If dev ports are in use OR Docker containers are running:**
- Proceed to Step 2.

### Step 2: Kill dev server processes

For each dev port, find the PID and kill it:

```bash
for port in [DEV_PORTS]; do
  pid=$(lsof -iTCP:${port} -sTCP:LISTEN -t 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "Killing PID $pid (port $port)..."
    kill -TERM "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  fi
done
```

### Step 3: Verify processes are stopped

Wait briefly, then confirm ports are free:

```bash
sleep 2
remaining=$(lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -E ":(DEV_PORTS)" || true)
if [ -n "$remaining" ]; then
  echo "WARNING: Some ports still in use:"
  echo "$remaining"
else
  echo "All dev server ports are free."
fi
```

If ports are still occupied, retry the kill one more time. If still occupied after retry, inform the user that manual intervention may be needed and show the PIDs.

### Step 4: Ask about Docker containers

Check if Docker dev containers are running:

```bash
docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null
```

**If Docker containers are running:**
- If the argument contains "all" or "docker": stop Docker without asking.
- Otherwise ask the user: "Docker containers are still running. Would you like me to stop them too?"
- If yes: run your project's Docker stop command (e.g., `docker compose down`).
- If no: leave them running (they can be reused on next start).

**If no Docker containers are running:**
- Skip this step.

### Step 5: Report

Present a summary:

> "Application stopped:
> - Dev server processes: [killed / were not running]
> - Docker containers: [stopped / left running / were not running]"
