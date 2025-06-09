# tests/test_output_formatting.py
import json
import os
import re
from pathlib import Path
from unittest import mock
from typing import Optional, List # Import Optional, List
from rich.markup import escape # For escaping patterns in log messages

import pytest
from click.testing import CliRunner

from dirdigest import cli as dirdigest_cli
from dirdigest.constants import TOOL_VERSION, LogEvent, PathState # Import LogEvent TypedDict and PathState
from dirdigest.formatter import format_log_event_for_cli, RICH_TAG_RE # Function to test and regex

# --- Helper for checking log lines (Copied from test_cli_sorting_and_logging.py) ---
def check_log_line_new(
    line: str,
    expected_status_summary: str, # "included", "excluded", "error", "unknown"
    expected_item_type: str,
    expected_path: str,
    expected_size_kb_str: Optional[str] = None, # e.g. "2.35KB" or None if not applicable
    expected_state_name: Optional[str] = None,
    expected_reason: Optional[str] = None,
    expected_msi: Optional[str] = None,
    expected_mse: Optional[str] = None,
    expected_default_rule: Optional[str] = None,
):
    """Checks if a formatted log line contains all the expected components based on the new format."""

    if expected_status_summary == "included":
        assert "[log.included]" in line and "✔" in line
        assert "Included" in line
    elif expected_status_summary == "excluded":
        assert "[log.excluded]" in line and "✘" in line
        assert "Excluded" in line
    elif expected_status_summary == "error":
        assert "[log.warning]" in line and "!" in line
        assert "Error" in line
    elif expected_status_summary == "unknown":
        assert "[log.warning]" in line and "!" in line
        assert "Unknown" in line

    assert expected_item_type in line
    assert f"[log.path]{expected_path}[/log.path]" in line

    if expected_size_kb_str and expected_size_kb_str != "N/A" and expected_size_kb_str != "":
        # Search for the size string possibly surrounded by Rich tags for color, within parentheses
        # Example: ([grey39]2.35KB[/grey39]) or (2.35KB)
        assert re.search(rf"\(\s*(\[.*?\])?{re.escape(expected_size_kb_str)}(\[.*?\])?\s*\)", line), \
               f"Size string '({expected_size_kb_str})' not found correctly in '{line}'"
    elif expected_size_kb_str == "N/A":
         assert "N/A" in line # Simpler check for N/A as its formatting is also simpler
    elif expected_size_kb_str == "":
        stripped_line_for_size_check = RICH_TAG_RE.sub("", line.split(":")[0])
        assert "KB" not in stripped_line_for_size_check

    if any([expected_state_name, expected_reason, expected_msi, expected_mse, expected_default_rule]):
        assert "[log.details]" in line
        if expected_state_name:
            assert f"State: {expected_state_name}" in line
        if expected_reason:
            assert expected_reason in line
        if expected_msi:
            assert f"MSI: '{escape(expected_msi)}'" in line
        if expected_mse:
            assert f"MSE: '{escape(expected_mse)}'" in line
        if expected_default_rule:
            assert f"DefaultRule: '{escape(expected_default_rule)}'" in line

# --- Unit tests for format_log_event_for_cli (Updated) ---

def test_format_log_event_included_file():
    log_event: LogEvent = {
        "path": "src/main.py", "item_type": "file", "status": "included",
        "state": PathState.FINAL_INCLUDED.name, "reason": "Matches MSI 'src/*.py'",
        "msi": "src/*.py", "size_kb": 2.345
    }
    result = format_log_event_for_cli(log_event)
    check_log_line_new(
        result, expected_status_summary="included", expected_item_type="file", expected_path="src/main.py",
        expected_size_kb_str="2.35KB", expected_state_name=PathState.FINAL_INCLUDED.name,
        expected_reason="Matches MSI 'src/*.py'", expected_msi="src/*.py"
    )

def test_format_log_event_excluded_folder_with_reason(): # Renamed from _new to match original name
    log_event: LogEvent = {
        "path": "node_modules/", "item_type": "folder", "status": "excluded",
        "state": PathState.DEFAULT_EXCLUDED.name, "reason": "Matches default rule: node_modules/",
        "default_rule": "node_modules/", "size_kb": 10240.0
    }
    result = format_log_event_for_cli(log_event)
    check_log_line_new(
        result, expected_status_summary="excluded", expected_item_type="folder", expected_path="node_modules/",
        expected_size_kb_str="10240.00KB", expected_state_name=PathState.DEFAULT_EXCLUDED.name,
        expected_reason="Matches default rule: node_modules/", expected_default_rule="node_modules/"
    )

def test_format_log_event_error_status_with_reason(): # Renamed
    log_event: LogEvent = {
        "path": "bad_dir/", "item_type": "folder", "status": "error",
        "state": PathState.FINAL_EXCLUDED.name,
        "reason": "Read error: Permission denied", "size_kb": 0.0
    }
    result = format_log_event_for_cli(log_event)
    check_log_line_new(
        result, expected_status_summary="error", expected_item_type="folder", expected_path="bad_dir/",
        expected_size_kb_str="",
        expected_state_name=PathState.FINAL_EXCLUDED.name,
        expected_reason="Read error: Permission denied"
    )
    if log_event.get("size_kb", 0.0) == 0.0 and log_event.get("status") == "error": # type: ignore
         assert "KB" not in result.split(":")[0]

def test_format_log_event_excluded_no_specific_pattern_details():
    log_event: LogEvent = {
        "path": "temp.tmp", "item_type": "file", "status": "excluded",
        "state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name,
        "reason": "No matching include pattern", "size_kb": 1.0
    }
    result = format_log_event_for_cli(log_event)
    check_log_line_new(
        result, expected_status_summary="excluded", expected_item_type="file", expected_path="temp.tmp",
        expected_size_kb_str="1.00KB",
        expected_state_name=PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name,
        expected_reason="No matching include pattern"
    )

def test_format_log_event_size_none_or_invalid():
    log_event_none: LogEvent = {
        "path": "data.bin", "item_type": "file", "status": "included",
        "state": PathState.FINAL_INCLUDED.name, "size_kb": None,
        "reason": "Included by default"
    }
    result_none = format_log_event_for_cli(log_event_none)
    check_log_line_new(
        result_none, expected_status_summary="included", expected_item_type="file",
        expected_path="data.bin", expected_size_kb_str="N/A",
        expected_state_name=PathState.FINAL_INCLUDED.name, expected_reason="Included by default"
    )
    assert "([grey39]N/A[/grey39])" in result_none

    log_event_invalid: LogEvent = { # type: ignore
        "path": "data2.bin", "item_type": "file", "status": "excluded",
        "state": PathState.FINAL_EXCLUDED.name, "size_kb": "very large",
        "reason": "Size could not be determined"
    }
    result_invalid = format_log_event_for_cli(log_event_invalid)
    check_log_line_new(
        result_invalid, expected_status_summary="excluded", expected_item_type="file",
        expected_path="data2.bin", expected_size_kb_str="N/A",
        expected_state_name=PathState.FINAL_EXCLUDED.name,
        expected_reason="Size could not be determined"
    )
    assert "([grey39]N/A[/grey39])" in result_invalid


def test_format_log_event_minimal_data(): # Renamed
    log_event: LogEvent = {"path": "minimal.txt"}
    result = format_log_event_for_cli(log_event)
    check_log_line_new(
        result, expected_status_summary="unknown", expected_item_type="item",
        expected_path="minimal.txt",
        expected_size_kb_str="",
        expected_state_name=PathState.PENDING_EVALUATION.name
    )
    assert "KB" not in result.split(":")[0]


# --- Existing tests for JSON/Markdown output format (remain unchanged) ---
def get_included_files_from_json(json_output_str: str) -> set[str]:
    try:
        data = json.loads(json_output_str)
    except json.JSONDecodeError as e:
        pytest.fail(f"Output was not valid JSON for helper. Error: {e}. Output: '{json_output_str[:500]}...'")
    included_files = set()

    def recurse_node(node):
        if node.get("type") == "file":
            if "relative_path" in node:
                included_files.add(node["relative_path"])
        if "children" in node and isinstance(node["children"], list):
            for child in node["children"]:
                recurse_node(child)

    if "root" in data:
        recurse_node(data["root"])
    return included_files


def structure_text_contains(markdown_output: str, substring: str) -> bool:
    match = re.search(r"## Directory Structure\n+```text\n(.*?)\n```", markdown_output, re.DOTALL)
    if not match:
        return False
    return substring in match.group(1)


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_markdown_output_basic_structure_simple_project(runner: CliRunner, temp_test_dir: Path):
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    markdown_output = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "markdown", "--no-clipboard"])
            if mock_rich_print.call_args_list:
                markdown_output = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0
    assert len(markdown_output) > 0
    assert f"# Directory Digest: {str(temp_test_dir.resolve())}" in markdown_output
    assert re.search(
        rf"\*Generated by dirdigest v{TOOL_VERSION} on \d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}(\.\d+)?\*",
        markdown_output,
    )
    assert re.search(r"\*Included files: \d+, Total content size: [\d\.]+ KB\*", markdown_output)
    assert "\n---\n" in markdown_output
    assert "\n## Directory Structure\n" in markdown_output
    assert "\n```text\n" in markdown_output

    assert structure_text_contains(markdown_output, "├── sub_dir1/")
    assert structure_text_contains(markdown_output, "│   └── script.py")
    assert structure_text_contains(markdown_output, "├── file1.txt")
    assert structure_text_contains(markdown_output, "└── file2.md")

    assert "\n```\n" in markdown_output
    assert "\n## Contents\n" in markdown_output
    assert re.search(r"### `./sub_dir1/script\.py`\s*```py(.*?\s*)*?```", markdown_output, re.DOTALL)
    assert re.search(r"### `./file1\.txt`\s*```(.*?\s*)*?```", markdown_output, re.DOTALL)


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_markdown_directory_structure_visualization_complex(runner: CliRunner, temp_test_dir: Path):
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    markdown_output = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "markdown", "--max-depth", "3", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                markdown_output = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0
    match = re.search(r"## Directory Structure\n+```text\n(.*?)\n```", markdown_output, re.DOTALL)
    assert match, "Directory structure block not found"
    structure_text = match.group(1).replace(os.sep, "/")

    assert ".\n" in structure_text
    assert "├── data/\n" in structure_text
    assert "│   └── small_data.csv" in structure_text
    assert "├── docs/\n" in structure_text
    assert "│   ├── api.md\n" in structure_text
    assert "│   └── index.md" in structure_text
    assert "├── src/\n" in structure_text
    assert "│   ├── feature/\n" in structure_text
    assert "│   │   └── module.py" in structure_text
    assert "│   ├── main.py\n" in structure_text
    assert "│   └── utils.py" in structure_text
    assert "├── tests/\n" in structure_text
    assert "│   ├── test_main.py\n" in structure_text
    assert "│   └── test_utils.py" in structure_text
    assert "├── README.md\n" in structure_text
    assert "└── config.yaml" in structure_text.strip()

    assert ".git/" not in structure_text
    assert "__pycache__/" not in structure_text
    assert "node_modules/" not in structure_text


@pytest.mark.parametrize("temp_test_dir", ["lang_hint_project"], indirect=True)
def test_markdown_code_block_language_hints(runner: CliRunner, temp_test_dir: Path):
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    markdown_output = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "markdown", "--no-default-ignore", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                markdown_output = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0
    markdown_output = markdown_output.replace(os.sep, "/")

    assert re.search(r"### `./script\.py`\s*```py\s*print\(\"python\"\)\s*```", markdown_output,)
    assert re.search(r"### `./styles\.css`\s*```css\s*body \{ color: blue; \}\s*```", markdown_output,)
    assert re.search(r"### `./data\.json`\s*```json\s*\{\"key\": \"value\"\}\s*```", markdown_output,)
    assert re.search(r"### `./README\.md`\s*```md\s*# Markdown\s*```", markdown_output)
    assert re.search(r"### `./unknown\.xyz`\s*```xyz\s*some data\s*```", markdown_output,)
    assert re.search(r"### `./no_ext_file`\s*```\s*text with no extension\s*```", markdown_output,)


@pytest.mark.parametrize("temp_test_dir", ["content_processing_dir"], indirect=True)
def test_markdown_file_with_read_error(runner: CliRunner, temp_test_dir: Path):
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    markdown_output = ""
    file_to_make_unreadable = Path("permission_denied_file.txt")
    original_permissions = None
    permission_change_successful = False

    try:
        if file_to_make_unreadable.exists():
            original_permissions = file_to_make_unreadable.stat().st_mode
            os.chmod(file_to_make_unreadable, 0o000)
            try:
                file_to_make_unreadable.read_text()
                permission_change_successful = False
            except PermissionError:
                permission_change_successful = True
        if not permission_change_successful:
            pytest.skip(f"Could not make {file_to_make_unreadable} unreadable on this platform")

        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "markdown", "--ignore-errors", "--no-default-ignore", "--no-clipboard",],
            )
            if mock_rich_print.call_args_list:
                markdown_output = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        if original_permissions is not None and file_to_make_unreadable.exists():
            os.chmod(file_to_make_unreadable, original_permissions)
        os.chdir(original_cwd)

    assert result.exit_code == 0
    markdown_output = markdown_output.replace(os.sep, "/")
    assert f"\n### `./{file_to_make_unreadable.name}`\n" in markdown_output
    assert re.search(r"```(text)?\s*Error reading file:.*?Permission denied.*?\s*```", markdown_output, re.DOTALL,)


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_json_output_metadata_and_root_structure(runner: CliRunner, temp_test_dir: Path):
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "json", "--no-clipboard"])
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0
    try:
        data = json.loads(json_output_str)
    except json.JSONDecodeError:
        pytest.fail(f"Output was not valid JSON: {json_output_str}")

    assert "metadata" in data
    metadata = data["metadata"]
    assert metadata["tool_version"] == TOOL_VERSION
    assert "created_at" in metadata
    assert Path(metadata["base_directory"]) == temp_test_dir.resolve()
    assert "included_files_count" in metadata
    assert "excluded_items_count" in metadata
    assert "total_content_size_kb" in metadata
    assert isinstance(metadata["included_files_count"], int)
    assert isinstance(metadata["excluded_items_count"], int)
    assert isinstance(metadata["total_content_size_kb"], (float, int))
    assert metadata["included_files_count"] == 3
    assert metadata["excluded_items_count"] == 0

    assert "root" in data
    root_node = data["root"]
    assert root_node["relative_path"] == "."
    assert root_node["type"] == "folder"
    assert "children" in root_node
    assert isinstance(root_node["children"], list)

    child_paths = [c["relative_path"].replace(os.sep, "/") for c in root_node["children"]]
    assert child_paths == ["sub_dir1", "file1.txt", "file2.md"]
