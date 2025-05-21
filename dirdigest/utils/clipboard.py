import pyperclip  # type: ignore[import-untyped]

from dirdigest.utils.logger import logger


def copy_to_clipboard(text: str) -> bool:
    """
    Copies the given text to the system clipboard.

    :param text: The string to copy.
    :return: True if successful, False otherwise.
    """
    if not text:
        logger.debug("Clipboard: No text provided to copy.")
        return False
    try:
        pyperclip.copy(text)
        # Success message is now handled by the caller (cli.py)
        return True
    except pyperclip.PyperclipException as e:  # Catch specific pyperclip errors
        logger.warning(
            f"Clipboard: Pyperclip could not access the clipboard system: {e}. "
            "This might be due to a missing copy/paste mechanism (e.g., xclip or xsel on Linux). "
            "Please see pyperclip documentation for setup."
        )
        return False
    except Exception as e:  # Catch any other unexpected errors
        logger.warning(
            f"Clipboard: An unexpected error occurred while trying to copy to clipboard: {e}",
            exc_info=True,
        )
        return False


def is_clipboard_available() -> bool:
    """
    Checks if the clipboard functionality seems to be available.
    Tries a benign paste operation.
    """
    try:
        pyperclip.paste()
        return True
    except pyperclip.PyperclipException:
        return False
    except Exception:
        return False
