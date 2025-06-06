import json
import pathlib
import pytest
import logging # Added for caplog
from click.testing import CliRunner

from dirdigest.cli import main_cli
from dirdigest.constants import DEFAULT_SORT_ORDER

# Helper function to create a directory structure (remains the same)
def create_test_files(base_path: pathlib.Path, structure: dict):
    for name, content in structure.items():
        path = base_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        elif isinstance(content, dict):
            create_test_files(path, content)

@pytest.fixture
def test_dir_structure(tmp_path: pathlib.Path) -> pathlib.Path:
    base = tmp_path / "test_project"
    base.mkdir()
    structure = {
        "file_alpha.txt": "alpha content",  # 13 bytes
        "file_beta_large.txt": "beta content " * 200,  # 2600 bytes (2.5KB)
        "sub_dir/file_gamma.py": "print('gamma')",  # 13 bytes
        "sub_dir/file_delta_small.md": "# delta",  # 7 bytes
        "sub_dir_empty/": {},
        ".ignored_hidden.txt": "hidden data",  # 11 bytes
        "node_modules/lib.js": "some js code", # 12 bytes (dir excluded)
        "temp_files/big_file.log": "log" * 102401,  # 300.0KB
        "temp_files/another_big_file.data": "d" * (301 * 1024)  # 301.0KB
    }
    create_test_files(base, structure)
    (base / "sub_dir_empty").mkdir(parents=True, exist_ok=True)
    return base

import re # Import re for regex
from rich.markup import escape # Import escape for consistency if needed, though not used in parsing here

# Updated parse_console_log_line to handle Rich markup
def parse_console_log_line(rich_log_line: str) -> dict:
    parts = {}
    # Example: "[log.excluded]Excluded[/log.excluded] File [log.size][Size: 0.0KB][/log.size]: [log.path].ignored_hidden.txt[/log.path] ([log.reason]Is a hidden file[/log.reason])"
    # Example: "[log.included]Included[/log.included] File [log.size][Size: 2.5KB][/log.size]: [log.path]file_beta_large.txt[/log.path]"

    # Regex to capture main parts
    # Status (e.g., "Excluded", "Included")
    # Type (e.g., "File", "Folder")
    # Size (e.g., "0.0KB", "2.5KB")
    # Path (e.g., ".ignored_hidden.txt", "file_beta_large.txt")
    # Reason (optional, e.g., "Is a hidden file")

    pattern_str = (
        r"\[log\.(?P<status_tag>excluded|included)\](?P<status_val>Excluded|Included)\[/log\.(?P=status_tag)\] "
        r"(?P<type>File|Folder) "
        r"\[log\.size\]\[Size: (?P<size_val>[\d\.]+KB|N/A)\]\[/log\.size\]: "
        r"\[log\.path\](?P<path>.*?)\[/log\.path\]"
        r"(?: \(\[log\.reason\](?P<reason>.*?)\[/log\.reason\]\))?"
    )

    match = re.match(pattern_str, rich_log_line)
    if not match:
        raise ValueError(f"Could not parse Rich log line: {rich_log_line}")

    data = match.groupdict()

    parts["status"] = data["status_val"] # "Excluded" or "Included"
    parts["type"] = data["type"]         # "File" or "Folder"

    size_str = data["size_val"]
    if size_str == "N/A":
        parts["size_kb"] = 0.0 # Or handle as None if preferred
    else:
        parts["size_kb"] = float(size_str.replace("KB", ""))

    parts["path"] = data["path"] # Path is already escaped by `rich.markup.escape` in cli.py if it had special chars
                                 # For comparison, we might need the unescaped version if test paths have special chars.
                                 # However, test paths here are simple.
    parts["reason"] = data.get("reason") # Will be None if not present

    return parts

def assert_log_item_details(actual_item, expected_item, item_index, sort_desc=""):
    assert actual_item['status'] == expected_item['status'], f"Item {item_index} status mismatch for {expected_item['path']} ({sort_desc})"
    assert actual_item['type'] == expected_item['type'], f"Item {item_index} type mismatch for {expected_item['path']} ({sort_desc})"
    assert actual_item['path'] == expected_item['path'], f"Item {item_index} path mismatch. Expected {expected_item['path']}, Got {actual_item['path']} ({sort_desc})"
    if actual_item['type'] == 'File': # Only check size for files for precision
        assert abs(actual_item['size_kb'] - expected_item.get('size_kb', 0.0)) < 0.01, \
            f"Item {item_index} size mismatch for {expected_item['path']}. Expected {expected_item.get('size_kb', 0.0)}, Got {actual_item['size_kb']} ({sort_desc})"
    if 'reason' in expected_item: # Only check reason if specified in expected
        assert actual_item.get('reason') == expected_item.get('reason'), f"Item {item_index} reason mismatch for {expected_item['path']}"

def get_detailed_console_log(caplog_text: str) -> list[str]:
    lines = caplog_text.splitlines()
    detailed_log_lines = []
    in_detailed_log_section = False
    for line in lines:
        # Assuming standard log format: "timestamp LEVEL logger: message"
        # We only care about the message part from our logger
        if "dirdigest.cli" not in line and "dirdigest.core" not in line : # Filter out other loggers if any
            if "--- Detailed Processing Log ---" in line or "--- End Detailed Processing Log ---" in line or "---" == line.strip():
                 # these are direct messages
                 pass
            else: # skip non-dirdigest logs unless they are our specific markers
                continue

        message_part = line.split(":", 3)[-1].strip() if ":" in line else line.strip()

        if message_part == "--- Detailed Processing Log ---":
            in_detailed_log_section = True
            continue
        if message_part == "--- End Detailed Processing Log ---":
            break
        if in_detailed_log_section:
            detailed_log_lines.append(message_part) # This includes '---' separators
    return detailed_log_lines

def check_console_separator_logic(console_log_lines: list[str], expect_separator: bool, sort_desc: str):
    # console_log_lines are the raw messages within the "Detailed Processing Log" block
    item_lines = [line for line in console_log_lines if line != "---"]
    has_excluded = any(item.startswith("Excluded") for item in item_lines)
    has_included = any(item.startswith("Included") for item in item_lines)

    separator_is_present = False
    if has_excluded and has_included:
        for i in range(len(console_log_lines) - 1):
            # Check for a "---" line that is between an Excluded item line and an Included item line
            if console_log_lines[i].startswith("Excluded") and \
               console_log_lines[i+1] == "---":
                if (i+2 < len(console_log_lines) and console_log_lines[i+2].startswith("Included")):
                    separator_is_present = True
                    break

    if expect_separator:
        if not (has_excluded and has_included): # Separator not expected if only one group type exists
             assert not separator_is_present, f"Separator '---' present for {sort_desc}, but not expected as only one status group exists."
        else:
            assert separator_is_present, f"Separator '---' was EXPECTED but not found correctly for {sort_desc}."
    else: # Not expecting separator
        assert not separator_is_present, f"Separator '---' was NOT EXPECTED but found for {sort_desc}."

# --- Test Cases ---

def run_cli_and_get_console_log(runner: CliRunner, caplog, project_dir: pathlib.Path, cli_args: list[str], output_file_name: str | None = None) -> tuple[list[str], str | None]:
    caplog.set_level(logging.INFO)

    full_command = [str(project_dir), "--config", "non_existent_config.toml", "--no-clipboard"] + cli_args
    if output_file_name:
        full_command.extend(["-o", output_file_name])

    result = runner.invoke(main_cli, full_command, catch_exceptions=False)
    assert result.exit_code == 0, f"CLI failed for {cli_args}. Output:\n{result.output}\nStderr:\n{result.stderr}"

    console_log_items = get_detailed_console_log(caplog.text)

    file_content = None
    if output_file_name:
        output_path = project_dir / output_file_name
        assert output_path.exists()
        file_content = output_path.read_text()
        # Assert no processing log in file
        if "--format" in cli_args and "json" in cli_args: # JSON
            data = json.loads(file_content)
            assert "processing_log" not in data
            assert "sort_options_used" not in data["metadata"] # Should be added by CLI for summary, not for file metadata
        else: # Markdown
            assert "## Processing Log" not in file_content
            assert "Detailed Processing Log" not in file_content # Check console markers aren't in file

    return console_log_items, file_content


def test_default_sort_console_log_and_markdown_file(runner: CliRunner, caplog, test_dir_structure: pathlib.Path):
    console_log_lines, md_content = run_cli_and_get_console_log(runner, caplog, test_dir_structure, [], "digest.md")

    item_lines = [line for line in console_log_lines if line != "---"]
    parsed_console_items = [parse_console_log_line(line) for line in item_lines]

    expected_console_items = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
    ]
    assert len(parsed_console_items) == len(expected_console_items)
    for i, actual in enumerate(parsed_console_items):
        assert_log_item_details(actual, expected_console_items[i], i, "default console sort")
    check_console_separator_logic(console_log_lines, expect_separator=True, sort_desc="default console sort")
    assert md_content is not None
    assert "## Processing Log" not in md_content


def test_sort_by_size_console_log(runner: CliRunner, caplog, test_dir_structure: pathlib.Path):
    console_log_lines, _ = run_cli_and_get_console_log(runner, caplog, test_dir_structure, ["--sort-output-log-by", "size"])
    item_lines = [line for line in console_log_lines if line != "---"]
    parsed_console_items = [parse_console_log_line(line) for line in item_lines]

    expected_items = [ # Same as default: status, type, then -size/path
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
    ]
    assert len(parsed_console_items) == len(expected_items)
    for i, actual in enumerate(parsed_console_items):
        assert_log_item_details(actual, expected_items[i], i, "console sort by size")
    check_console_separator_logic(console_log_lines, expect_separator=True, sort_desc="console sort by size")


def test_sort_by_status_path_console_log(runner: CliRunner, caplog, test_dir_structure: pathlib.Path):
    console_log_lines, _ = run_cli_and_get_console_log(runner, caplog, test_dir_structure, ["--sort-output-log-by", "status", "--sort-output-log-by", "path"])
    item_lines = [line for line in console_log_lines if line != "---"]
    parsed_console_items = [parse_console_log_line(line) for line in item_lines]

    expected_items = [ # Status, Type, Path
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'reason': 'Is a hidden file'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'reason': 'Matches default ignore pattern'},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py'},
    ]
    assert len(parsed_console_items) == len(expected_items)
    for i, actual in enumerate(parsed_console_items):
        assert_log_item_details(actual, expected_items[i], i, "console sort by status, path")
    check_console_separator_logic(console_log_lines, expect_separator=True, sort_desc="console sort by status, path")


def test_sort_by_path_console_log(runner: CliRunner, caplog, test_dir_structure: pathlib.Path):
    console_log_lines, _ = run_cli_and_get_console_log(runner, caplog, test_dir_structure, ["--sort-output-log-by", "path"])
    item_lines = [line for line in console_log_lines if line != "---"]
    parsed_console_items = [parse_console_log_line(line) for line in item_lines]

    expected_items = [ # Path, Type
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt'},
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'reason': 'Matches default ignore pattern'},
    ]
    assert len(parsed_console_items) == len(expected_items)
    for i, actual in enumerate(parsed_console_items):
        assert_log_item_details(actual, expected_items[i], i, "console sort by path")
    check_console_separator_logic(console_log_lines, expect_separator=False, sort_desc="console sort by path")


def test_sort_by_size_path_console_log(runner: CliRunner, caplog, test_dir_structure: pathlib.Path):
    console_log_lines, _ = run_cli_and_get_console_log(runner, caplog, test_dir_structure, ["--sort-output-log-by", "size", "--sort-output-log-by", "path"])
    item_lines = [line for line in console_log_lines if line != "---"]
    parsed_console_items = [parse_console_log_line(line) for line in item_lines]

    expected_items = [ # Type, then Path for Folders / -Size,Path for Files
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
    ]
    assert len(parsed_console_items) == len(expected_items)
    for i, actual in enumerate(parsed_console_items):
        assert_log_item_details(actual, expected_items[i], i, "console sort by size, path")
    check_console_separator_logic(console_log_lines, expect_separator=False, sort_desc="console sort by size, path")


def test_json_file_output_no_processing_log(runner: CliRunner, caplog, test_dir_structure: pathlib.Path):
    """Test JSON output file does not contain processing_log or sort_options_used in metadata."""
    # Run with default sort, output to json file
    console_log_lines, json_content_str = run_cli_and_get_console_log(
        runner, caplog, test_dir_structure, ["--format", "json"], "digest.json"
    )

    assert json_content_str is not None
    parsed_json_file = json.loads(json_content_str)

    assert "processing_log" not in parsed_json_file, "processing_log should not be in JSON file output."
    assert "sort_options_used" not in parsed_json_file["metadata"], "sort_options_used should not be in file metadata."
    assert "root" in parsed_json_file # Basic structure check

    # Also check console log for default sort as a bonus
    item_lines = [line for line in console_log_lines if line != "---"]
    parsed_console_items = [parse_console_log_line(line) for line in item_lines]
    expected_console_items = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
    ]
    assert len(parsed_console_items) == len(expected_console_items)
    for i, actual in enumerate(parsed_console_items):
        assert_log_item_details(actual, expected_console_items[i], i, "console log for JSON output test")
    check_console_separator_logic(console_log_lines, expect_separator=True, sort_desc="console log for JSON output test")

```
