# tests/conftest.py
import os
import shutil
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

# Define the root for mock directory structures, relative to this conftest.py file
MOCK_DIRS_ROOT = Path(__file__).parent / "fixtures" / "test_dirs"

from dirdigest.utils.logger import logger # Added for fallback logging


@pytest.fixture
def runner() -> CliRunner:
    """Provides a Click CliRunner instance for invoking CLI commands."""
    return CliRunner()


@pytest.fixture
def temp_test_dir(tmp_path: Path, request):
    """
    Creates a temporary directory, copies a specified mock directory structure into it,
    changes the current working directory to it for the duration of the test,
    and cleans up afterward.

    To use, decorate your test function with:
    @pytest.mark.parametrize("temp_test_dir", ["name_of_mock_dir"], indirect=True)
    'name_of_mock_dir' should be a subdirectory under tests/fixtures/test_dirs/
    The fixture will yield the Path object to the created temporary test directory.
    """
    mock_dir_name = request.param
    source_path = MOCK_DIRS_ROOT / mock_dir_name
    test_specific_tmp_dir = tmp_path / mock_dir_name # Define dest_path (as test_specific_tmp_dir) early

    if not source_path.is_dir():
        logger.warning(f"Mock directory '{mock_dir_name}' not found at '{source_path}'. Attempting to create fallback.")
        if mock_dir_name == "simple_project":
            logger.info(f"Creating fallback structure for 'simple_project' at {test_specific_tmp_dir}")
            test_specific_tmp_dir.mkdir(parents=True, exist_ok=True)
            (test_specific_tmp_dir / "subdir").mkdir(parents=True, exist_ok=True)
            (test_specific_tmp_dir / "root.txt").write_text("Root file")
            (test_specific_tmp_dir / "subdir" / "sub.txt").write_text("Subdir file")
            (test_specific_tmp_dir / "empty.txt").write_text("Empty file")
            (test_specific_tmp_dir / "subdir" / "another_empty.txt").touch()
        elif mock_dir_name == "complex_project":
            logger.info(f"Creating fallback structure for 'complex_project' at {test_specific_tmp_dir}")
            test_specific_tmp_dir.mkdir(parents=True, exist_ok=True)
            (test_specific_tmp_dir / "dir1").mkdir()
            (test_specific_tmp_dir / "dir1" / "file1a.txt").write_text("file1a content")
            (test_specific_tmp_dir / "dir1" / "file1b.md").write_text("# Markdown 1b")
            (test_specific_tmp_dir / "dir2").mkdir()
            (test_specific_tmp_dir / "dir2" / "sub_dir_2_1").mkdir()
            (test_specific_tmp_dir / "dir2" / "sub_dir_2_1" / "file21a.py").write_text("print('hello')")
            (test_specific_tmp_dir / "file_root.txt").write_text("root file in complex")
        elif mock_dir_name == "content_processing_dir": # Added fallback
            logger.info(f"Creating fallback structure for 'content_processing_dir' at {test_specific_tmp_dir}")
            test_specific_tmp_dir.mkdir(parents=True, exist_ok=True)
            (test_specific_tmp_dir / "small.txt").write_text("small content")
            (test_specific_tmp_dir / "large.txt").write_text("large content" * 1024) # Approx 13KB
            (test_specific_tmp_dir / "empty.txt").touch()
            (test_specific_tmp_dir / "binary_file.bin").write_bytes(b"\x00\x01\x02\x80\xff")
            (test_specific_tmp_dir / "unreadable.txt").touch() # Permissions set in test
            (test_specific_tmp_dir / "utf8_example.txt").write_text("こんにちは世界")
        elif mock_dir_name == "lang_hint_project": # Added fallback
            logger.info(f"Creating fallback structure for 'lang_hint_project' at {test_specific_tmp_dir}")
            test_specific_tmp_dir.mkdir(parents=True, exist_ok=True)
            (test_specific_tmp_dir / "script.py").write_text("print('Python')")
            (test_specific_tmp_dir / "script.js").write_text("console.log('JavaScript')")
            (test_specific_tmp_dir / "style.css").write_text("body { color: blue; }")
            (test_specific_tmp_dir / "nodot").write_text("no dot extension")
            (test_specific_tmp_dir / ".dotfile").write_text("dotfile")
        else:
            # Original error path
            raise ValueError(
                f"Mock directory '{mock_dir_name}' not found at '{source_path}'. "
                "Did you create it under tests/fixtures/test_dirs/? No fallback available."
            )
    else:
        # CRITICAL FIX FOR SYMLINK TESTS: Add symlinks=True
        shutil.copytree(source_path, test_specific_tmp_dir, symlinks=True)

    original_cwd = Path.cwd()
    os.chdir(test_specific_tmp_dir)

    try:
        yield test_specific_tmp_dir
    finally:
        os.chdir(original_cwd)


@pytest.fixture
def mock_pyperclip(monkeypatch):
    """
    Mocks pyperclip.copy and pyperclip.paste.
    The mock_copy function stores the copied text in clipboard_content["text"].
    Returns a tuple: (mock_copy_object, mock_paste_object, clipboard_content_dict).
    """
    mock_copy_object = mock.MagicMock()
    mock_paste_object = mock.MagicMock(return_value="")
    clipboard_content_dict = {"text": None}

    def custom_pyperclip_copy(text_to_copy):
        clipboard_content_dict["text"] = text_to_copy
        mock_copy_object(text_to_copy)

    def custom_pyperclip_paste():
        return mock_paste_object()

    monkeypatch.setattr("dirdigest.utils.clipboard.pyperclip.copy", custom_pyperclip_copy)
    monkeypatch.setattr("dirdigest.utils.clipboard.pyperclip.paste", custom_pyperclip_paste)

    try:
        import pyperclip

        mock_copy_object.PyperclipException = pyperclip.PyperclipException
        mock_paste_object.PyperclipException = pyperclip.PyperclipException
    except ImportError:

        class DummyPyperclipException(Exception):
            pass

        mock_copy_object.PyperclipException = DummyPyperclipException
        mock_paste_object.PyperclipException = DummyPyperclipException

    return mock_copy_object, mock_paste_object, clipboard_content_dict
