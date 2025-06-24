# tests/test_output_formatting.py
import json
import os
import re
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from dirdigest import cli as dirdigest_cli
from dirdigest.constants import TOOL_VERSION
from dirdigest.core import LogEvent  # For type hinting
from dirdigest.formatter import format_log_event_for_cli  # Function to test

# --- Helper for checking log lines ---


def check_log_line(
    line: str,
    status: str,
    item_type: str,
    path: str,
    size_str: str,
    reason: str | None = None,
):
    """Checks if a formatted log line contains all the expected components."""
    assert f"[log.{status}]{status.capitalize()}" in line
    # The formatter may add padding, so a simple 'in' check is robust.
    assert item_type in line
    assert f"({size_str})" in line
    assert f"[log.path]{path}[/log.path]" in line
    if reason:
        assert f"([log.reason]{reason}[/log.reason])" in line
    else:
        # If no reason, the reason tag should not be present at all.
        assert "[log.reason]" not in line


# --- Unit tests for format_log_event_for_cli ---


def test_format_log_event_included_file():
    log_event: LogEvent = {
        "path": "src/main.py",
        "item_type": "file",
        "status": "included",
        "size_kb": 2.345,
        "reason": None,
    }
    result = format_log_event_for_cli(log_event)
    check_log_line(
        result,
        status="included",
        item_type="file",
        path="src/main.py",
        size_str="2.35KB",
    )


def test_format_log_event_excluded_folder_with_reason():
    log_event: LogEvent = {
        "path": "node_modules/",
        "item_type": "folder",
        "status": "excluded",
        "size_kb": 10240.0,
        "reason": "Matches default ignore pattern",
    }
    result = format_log_event_for_cli(log_event)
    check_log_line(
        result,
        status="excluded",
        item_type="folder",
        path="node_modules/",
        size_str="10240.00KB",
        reason="Matches default ignore pattern",
    )


def test_format_log_event_error_status_with_reason():
    log_event: LogEvent = {
        "path": "bad_dir/",
        "item_type": "folder",
        "status": "error",
        "size_kb": 0.0,
        "reason": "Error calculating size: Permission denied",
    }
    result = format_log_event_for_cli(log_event)
    check_log_line(
        result,
        status="error",
        item_type="folder",
        path="bad_dir/",
        size_str="0.00KB",
        reason="Error calculating size: Permission denied",
    )


def test_format_log_event_missing_reason_for_excluded():
    log_event: LogEvent = {
        "path": "temp.tmp",
        "item_type": "file",
        "status": "excluded",
        "size_kb": 1.0,
        "reason": None,  # Excluded but reason is None
    }
    result = format_log_event_for_cli(log_event)
    # Reason part should be omitted if reason is None, even if excluded
    check_log_line(result, status="excluded", item_type="file", path="temp.tmp", size_str="1.00KB")


def test_format_log_event_size_not_numeric():
    log_event: LogEvent = {
        "path": "data.bin",
        "item_type": "file",
        "status": "included",
        "size_kb": "very large",  # Invalid size type
        "reason": None,
    }
    result = format_log_event_for_cli(log_event)
    check_log_line(result, status="included", item_type="file", path="data.bin", size_str="N/AKB")


def test_format_log_event_minimal_data():
    log_event: LogEvent = {  # type: ignore
        "path": "minimal.txt",
        # item_type, status, size_kb, reason are missing
    }
    # .get() in formatter should provide defaults
    # status: "unknown", item_type: "item", size_kb: 0.0
    result = format_log_event_for_cli(log_event)
    check_log_line(
        result,
        status="unknown",
        item_type="item",
        path="minimal.txt",
        size_str="0.00KB",
    )


# --- Existing tests for JSON/Markdown output format ---


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
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "markdown", "-o", "-", "--no-clipboard"])
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

    # After sorting fix (folders first)
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
                [".", "--format", "markdown", "--max-depth", "3", "-o", "-", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                markdown_output = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0
    match = re.search(r"## Directory Structure\n+```text\n(.*?)\n```", markdown_output, re.DOTALL)
    assert match, "Directory structure block not found"
    structure_text = match.group(1).replace(os.sep, "/")

    # Based on corrected sorting: Folders first (alpha), then files (alpha).
    # Folders: data, docs, src, tests
    # Files: README.md, config.yaml
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

    # Verify default ignored are not present
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
                [".", "--format", "markdown", "--no-default-ignore", "-o", "-", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                markdown_output = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0

    markdown_output = markdown_output.replace(os.sep, "/")

    # The `echo` command in the setup script adds a newline to the file content.
    # The regex needs to account for this. Using `\s*` to be flexible.
    assert re.search(
        r"### `./script\.py`\s*```py\s*print\(\"python\"\)\s*```",
        markdown_output,
    )
    assert re.search(
        r"### `./styles\.css`\s*```css\s*body \{ color: blue; \}\s*```",
        markdown_output,
    )
    assert re.search(
        r"### `./data\.json`\s*```json\s*\{\"key\": \"value\"\}\s*```",
        markdown_output,
    )
    assert re.search(r"### `./README\.md`\s*```md\s*# Markdown\s*```", markdown_output)
    assert re.search(
        r"### `./unknown\.xyz`\s*```xyz\s*some data\s*```",
        markdown_output,
    )
    assert re.search(
        r"### `./no_ext_file`\s*```\s*text with no extension\s*```",
        markdown_output,
    )


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

            # Verify the permission change worked
            try:
                file_to_make_unreadable.read_text()
                permission_change_successful = False
            except PermissionError:
                permission_change_successful = True

        # Skip if we couldn't make the file unreadable
        if not permission_change_successful:
            pytest.skip(f"Could not make {file_to_make_unreadable} unreadable on this platform")

        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [
                    ".",
                    "--format",
                    "markdown",
                    "--ignore-errors",
                    "--no-default-ignore",
                    "-o",
                    "-",
                    "--no-clipboard",
                ],
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
    assert re.search(
        r"```(text)?\s*Error reading file:.*?Permission denied.*?\s*```",
        markdown_output,
        re.DOTALL,
    )


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_json_output_metadata_and_root_structure(runner: CliRunner, temp_test_dir: Path):
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "json", "-o", "-", "--no-clipboard"])
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
    # In simple_project, there are no default ignored files, so excluded count should be 0.
    # Plus one for the auto-excluded output file if we weren't using "-o -"
    assert metadata["included_files_count"] == 3
    assert metadata["excluded_items_count"] == 0  # No auto-exclude for stdout

    assert "root" in data
    root_node = data["root"]
    assert root_node["relative_path"] == "."
    assert root_node["type"] == "folder"
    assert "children" in root_node
    assert isinstance(root_node["children"], list)

    # Check that children are sorted (folders first, then files, all alphabetically)
    child_paths = [c["relative_path"].replace(os.sep, "/") for c in root_node["children"]]
    assert child_paths == ["sub_dir1", "file1.txt", "file2.md"]
