# dirdigest/utils/system.py
import os
import platform
import subprocess
from pathlib import Path  # Import Path

from dirdigest.utils.logger import logger  # Import logger for warnings


def is_running_in_wsl() -> bool:
    """Checks if the script is running inside Windows Subsystem for Linux (WSL)."""
    if platform.system() != "Linux":
        return False

    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True

    try:
        with open("/proc/version", "r", encoding="utf-8") as f:
            proc_version_content = f.read()
            if (
                "microsoft" in proc_version_content.lower()
                or "wsl" in proc_version_content.lower()
            ):
                return True
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug(f"System: Error reading /proc/version: {e}")

    return False


def convert_wsl_path_to_windows(linux_path_str: str) -> str | None:
    """
    Converts a WSL Linux path to its Windows equivalent using `wslpath -w`.
    Returns the Windows path, or None if conversion fails.
    Assumes `is_running_in_wsl()` has already confirmed WSL environment if called.
    """
    # No need to check is_running_in_wsl() here again, caller should do it.
    # Path(linux_path_str).resolve() ensures we pass an absolute path,
    # which is good practice for wslpath.
    try:
        # Ensure the path is absolute for wslpath.
        # If linux_path_str is already absolute, resolve() is idempotent.
        # If relative, it's resolved against CWD.
        resolved_linux_path = str(Path(linux_path_str).resolve())

        result = subprocess.run(
            ["wslpath", "-w", resolved_linux_path],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",  # Specify encoding for subprocess output
        )
        return result.stdout.strip()
    except FileNotFoundError:  # wslpath command not found
        logger.warning(
            "System: 'wslpath' command not found. Cannot convert WSL path to Windows path. Is WSL installed correctly?"
        )
        return None
    except subprocess.CalledProcessError as e:  # wslpath command failed
        logger.warning(
            f"System: 'wslpath -w {resolved_linux_path}' failed: {e.stderr or e.stdout or e}"
        )
        return None
    except Exception as e:  # Catch any other unexpected errors
        logger.warning(
            f"System: Unexpected error during WSL path conversion for '{resolved_linux_path}': {e}",
            exc_info=True,
        )
        return None
