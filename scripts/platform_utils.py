#!/usr/bin/env python3
"""Cross-platform utilities for CodeClaw scripts.

Provides shared helpers that abstract away OS-specific differences
(Windows vs macOS vs Linux) so that all CodeClaw scripts work identically
on every supported platform.

Zero external dependencies -- stdlib only.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


# -- Python Command Detection ------------------------------------------------

def detect_python_cmd() -> str:
    """Auto-detect the correct Python command for the current system.

    Tries ``python3`` first (standard on macOS/Linux), then ``python``
    (common on Windows).  Returns whichever is found on PATH, or falls
    back to ``sys.executable`` as a last resort.
    """
    for candidate in ("python3", "python"):
        path = shutil.which(candidate)
        if path is not None:
            # Verify it is Python 3.x
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version_str = result.stdout.strip() or result.stderr.strip()
                if version_str.startswith("Python 3"):
                    return candidate
            except (subprocess.TimeoutExpired, OSError):
                continue
    # Ultimate fallback: the interpreter running this script
    return sys.executable


# -- Shell Detection ----------------------------------------------------------

def get_shell_info() -> dict:
    """Detect the current shell type and return metadata.

    Returns a dict with:
        shell   -- short name: "bash", "zsh", "powershell", "cmd", "unknown"
        path    -- absolute path to the shell binary (or None)
        cat_cmd -- the command to read a file's contents into a variable
                   (e.g. ``$(cat file)`` on bash, ``$(Get-Content file)``
                   on PowerShell)
    """
    shell_env = os.environ.get("SHELL", "")
    comspec = os.environ.get("COMSPEC", "")

    if IS_WINDOWS:
        # Check for PowerShell first (preferred on Windows)
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh:
            return {
                "shell": "powershell",
                "path": pwsh,
                "cat_cmd": "$(Get-Content {file})",
            }
        # Fallback: cmd.exe
        return {
            "shell": "cmd",
            "path": comspec or r"C:\Windows\System32\cmd.exe",
            "cat_cmd": None,  # cmd.exe has no inline file-read syntax
        }

    # Unix-like: inspect $SHELL
    shell_name = Path(shell_env).name if shell_env else ""
    if shell_name in ("bash", "zsh", "sh", "dash", "fish", "ksh"):
        return {
            "shell": shell_name,
            "path": shell_env,
            "cat_cmd": "$(cat {file})",
        }

    return {
        "shell": "unknown",
        "path": shell_env or None,
        "cat_cmd": "$(cat {file})",
    }


# -- File Copy ----------------------------------------------------------------

def safe_copy_tree(src: str | Path, dst: str | Path) -> None:
    """Recursively copy a directory tree, cross-platform.

    Replaces Unix-specific ``cp -r`` calls with ``shutil.copytree``.
    If the destination already exists, files are merged (existing files
    are overwritten).

    Parameters
    ----------
    src : str | Path
        Source directory.
    dst : str | Path
        Destination directory.
    """
    src = Path(src)
    dst = Path(dst)

    if not src.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {src}")

    # Python 3.8+: dirs_exist_ok=True handles merging
    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)


# -- Shell Command Helpers ----------------------------------------------------

def read_file_for_prompt(file_path: str | Path) -> str:
    """Read a file's contents for use as a CLI prompt argument.

    On Unix shells this would normally be done with ``$(cat file)``, but
    that fails on Windows cmd.exe.  This function reads the file directly
    in Python, which works on all platforms.

    Parameters
    ----------
    file_path : str | Path
        Path to the file to read.

    Returns
    -------
    str
        The file contents.
    """
    return Path(file_path).read_text(encoding="utf-8")


def build_shell_invocation(cmd_parts: list[str], *, shell: bool = False) -> dict:
    """Prepare a subprocess invocation dict that works cross-platform.

    When *shell* is False (the default), returns list-format args which
    bypass the shell entirely and work on all OSes.  When *shell* is True,
    returns a single string suitable for the native shell.

    Returns
    -------
    dict
        Keys: ``args`` (list | str), ``shell`` (bool).
    """
    if shell:
        return {"args": " ".join(cmd_parts), "shell": True}
    return {"args": cmd_parts, "shell": False}


# -- Subprocess Audit Helpers -------------------------------------------------

def run_command(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    capture: bool = True,
    timeout: int = 120,
    check: bool = False,
) -> dict:
    """Run a command using list-format invocation (no shell).

    This is the recommended way to call subprocesses across all CodeClaw
    scripts.  Using list-format avoids shell injection risks and works
    identically on Windows, macOS, and Linux.

    Parameters
    ----------
    cmd : list[str]
        Command and arguments.
    cwd : str | Path | None
        Working directory.
    capture : bool
        Capture stdout/stderr.
    timeout : int
        Timeout in seconds.
    check : bool
        Raise CalledProcessError on non-zero exit.

    Returns
    -------
    dict
        Keys: success, returncode, stdout, stderr.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
            check=check,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip() if capture else "",
            "stderr": result.stderr.strip() if capture else "",
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "returncode": e.returncode,
            "stdout": (e.stdout or "").strip() if capture else "",
            "stderr": (e.stderr or "").strip() if capture else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command not found: {cmd[0]}",
        }


# -- File Opener --------------------------------------------------------------

def open_file(path: str | Path) -> bool:
    """Open a file with the system's default application.

    Cross-platform: uses ``xdg-open`` on Linux, ``open`` on macOS, and
    ``os.startfile`` on Windows.

    Parameters
    ----------
    path : str | Path
        Path to the file to open.

    Returns
    -------
    bool
        True if the file open command was launched successfully.
    """
    path = Path(path)
    if not path.exists():
        return False

    try:
        if IS_WINDOWS:
            os.startfile(str(path))
            return True
        elif IS_MACOS:
            subprocess.Popen(
                ["open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        elif IS_LINUX:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    except (OSError, FileNotFoundError):
        pass

    return False


# -- CLI Entry Point ----------------------------------------------------------

def main() -> None:
    """CLI for quick platform diagnostics."""
    import json

    info = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python_command": detect_python_cmd(),
        "python_version": platform.python_version(),
        "shell": get_shell_info(),
        "is_windows": IS_WINDOWS,
        "is_macos": IS_MACOS,
        "is_linux": IS_LINUX,
    }
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
