---
name: app-restart
description: Restart the project's development environment. Stops existing processes, then starts fresh with setup and dev server, with error monitoring.
disable-model-invocation: true
allowed-tools: Bash
---

# Restart the Application

You are a DevOps operator for this project. Your job is to cleanly restart the development environment — stop everything, then start fresh.

## Current Environment State

### Listening ports:
!`lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | awk '{print $1, $2, $9}' | tail -20 || echo "No listening ports found"`

> Cross-reference the ports above against the `DEV_PORTS` configured in CLAUDE.md to identify which belong to this project.

### Docker containers:
!`docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Docker not available or no containers running"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Stop existing processes

Regardless of whether the app appears to be running, perform a clean stop to ensure no stale processes remain.

**Kill all processes on dev ports:**

```bash
for port in [DEV_PORTS]; do
  pid=$(lsof -iTCP:${port} -sTCP:LISTEN -t 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "Killing PID $pid (port $port)..."
    kill -TERM "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  fi
done
```

**Verify ports are free:**

```bash
sleep 2
remaining=$(lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -E ":(DEV_PORTS)" || true)
if [ -n "$remaining" ]; then
  echo "WARNING: Ports still in use, retrying..."
  echo "$remaining" | awk '{print $2}' | sort -u | while read pid; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done
  sleep 2
fi
```

If ports are still occupied after 2 retries, inform the user and stop.

### Step 2: Run pre-start setup (if applicable)

Run the pre-start command to ensure services are up and dependencies are synchronized:

```bash
# [PREDEV_COMMAND] — as configured in CLAUDE.md (if defined)
```

Wait for it to complete. If it fails:
- Diagnose the error
- Common issues: Docker not running, port occupied, schema errors
- Attempt to fix if possible, otherwise inform the user and stop

### Step 3: Start the dev server (background)

Run the start command with `run_in_background: true`:

```bash
# [START_COMMAND] — as configured in CLAUDE.md
```

### Step 4: Monitor startup for errors

1. **Wait 8 seconds** for startup:
   ```bash
   sleep 8
   ```

2. **Verify ports are bound:**
   ```bash
   lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -E ":(DEV_PORTS)"
   ```

3. **Check Docker health** (if applicable):
   ```bash
   docker ps --format "{{.Names}}: {{.Status}}"
   ```

4. **Read the background process output** using `TaskOutput` for errors. Look for common error indicators:
   - Port conflicts: `EADDRINUSE`, `Address already in use`, `port is already allocated`
   - Missing dependencies: `Cannot find module`, `ModuleNotFoundError`, `no required module`, `package not found`
   - Connection failures: `ECONNREFUSED`, `Connection refused`, `connection error`
   - Generic errors: `Error`, `FATAL`, `panic`, `traceback`, stack traces or crash dumps

5. **Report results:**

   **Success:**
   > "Application restarted successfully:
   > - [list bound ports and their services]
   > - Docker containers: [healthy / N/A]"

   **Failure:**
   - Show the error output
   - Attempt to diagnose and fix
   - If fixable, stop processes and retry from Step 2 (max 1 retry)
   - If not fixable, present the error and suggest remediation
