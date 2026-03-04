---
name: app-start
description: Start the project's development environment. Checks for running processes, runs setup commands, and launches the dev server with error monitoring.
disable-model-invocation: true
allowed-tools: Bash
---

# Start the Application

You are a DevOps operator for this project. Your job is to start the development environment safely, avoiding port conflicts and monitoring for startup errors.

## Current Environment State

### Listening ports:
!`lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | awk '{print $1, $2, $9}' | tail -20 || echo "No listening ports found"`

> Cross-reference the ports above against the `DEV_PORTS` configured in CLAUDE.md to identify which belong to this project.

### Docker containers:
!`docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Docker not available or no containers running"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

> **Configuration required:** Before using this skill, ensure CLAUDE.md defines:
> - **DEV_PORTS**: Which ports your dev server uses (e.g., `3000`, `8000`, `8080`)
> - **START_COMMAND**: The command to start your dev server (e.g., `npm run dev`, `python manage.py runserver`, `cargo run`, `go run .`)
> - **PREDEV_COMMAND**: Optional pre-start setup (e.g., `docker compose up -d`, database migrations, dependency generation)

### Step 1: Check if the app is already running

Examine the environment state above. The app is considered "running" if **any** of the configured dev ports are in use.

**If ports are in use:**
- Inform the user: "The app appears to be already running (ports in use: [list ports and PIDs])."
- Ask the user using `AskUserQuestion`: "Would you like me to restart it (stop + start fresh), or skip?"
  - **"Restart"** — proceed to Step 2 (stop first), then continue to Step 3.
  - **"Skip"** — stop here.

**If no ports are in use:**
- Proceed directly to Step 3.

### Step 2: Stop existing processes (only if restarting)

Kill all processes on dev ports. For each configured port, run:

```bash
for port in [DEV_PORTS]; do
  pid=$(lsof -iTCP:${port} -sTCP:LISTEN -t 2>/dev/null)
  if [ -n "$pid" ]; then
    echo "Killing PID $pid (port $port)..."
    kill -TERM "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  fi
done
```

After killing, wait 2 seconds then verify all ports are free:

```bash
sleep 2
still_used=$(lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -E ":(DEV_PORTS)" || true)
if [ -n "$still_used" ]; then
  echo "WARNING: Some ports still in use after kill:"
  echo "$still_used"
else
  echo "All ports are free."
fi
```

If ports are still occupied after 3 retries (kill + 2s wait), inform the user and stop.

### Step 3: Run pre-start setup (if applicable)

If a pre-start command is defined (e.g., Docker containers, database migrations, dependency generation):

```bash
# [PREDEV_COMMAND] — as configured in CLAUDE.md (if defined)
```

This command runs synchronously. Wait for it to complete.

**If it fails:**
- Read the error output carefully
- Common issues:
  - Docker not running — inform the user to start Docker
  - Port conflicts — another service occupying required ports
  - Database errors — schema or migration issues
- Do NOT proceed to Step 4 if pre-start fails

### Step 4: Start the dev server (background)

Run the start command using the Bash tool with `run_in_background: true`:

```bash
# [START_COMMAND] — as configured in CLAUDE.md
```

### Step 5: Monitor startup for errors

After starting the background process:

1. **Wait 8 seconds** for initial startup:
   ```bash
   sleep 8
   ```

2. **Check that ports are bound** — verify dev ports are now listening:
   ```bash
   lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -E ":(DEV_PORTS)"
   ```

3. **Check Docker containers are healthy** (if applicable):
   ```bash
   docker ps --format "{{.Names}}: {{.Status}}"
   ```

4. **Read the background process output** using `TaskOutput` to check for errors. Look for common error indicators:
   - Port conflicts: `EADDRINUSE`, `Address already in use`, `port is already allocated`
   - Missing dependencies: `Cannot find module`, `ModuleNotFoundError`, `no required module`, `package not found`
   - Connection failures: `ECONNREFUSED`, `Connection refused`, `connection error`
   - Generic errors: `Error`, `FATAL`, `panic`, `traceback`, stack traces or crash dumps

5. **Report results to the user:**

   **If all checks pass** (all ports listening, no errors in output):
   > "The application is running successfully:
   > - [list bound ports and their services]
   > - Docker containers: [healthy / N/A]
   >
   > You can access the app at http://localhost:[PORT]"

   **If errors are detected:**
   - Show the error output to the user
   - Attempt to diagnose the root cause
   - If fixable (e.g., missing dependency install), fix it, stop the failed processes, and restart from Step 3
   - If not fixable automatically, present the error and suggest next steps

### Error Recovery

If the app fails to start after one retry:
1. Stop any partially-started processes (Step 2)
2. Present all collected error output to the user
3. Suggest specific remediation steps based on the error type
4. Do NOT enter an infinite retry loop — max 1 automatic retry
