import json
import pathlib
import pytest
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
        "sub_dir_empty/": {}, # Empty directory
        ".ignored_hidden.txt": "hidden data",  # 11 bytes, excluded (hidden)
        "node_modules/lib.js": "some js code",  # 12 bytes, excluded (default pattern for node_modules dir)
        # Make big_file.log excluded by pattern first, then by size if pattern was missed.
        # Default ignore patterns include "*.log"
        "temp_files/big_file.log": "log" * 102401,  # 307203 bytes (300.0KB), excluded by pattern
        "temp_files/another_big_file.data": "d" * (301 * 1024)  # 308224 bytes (301.0KB), excluded by size
    }
    create_test_files(base, structure)
    (base / "sub_dir_empty").mkdir(parents=True, exist_ok=True)
    return base

# run_dirdigest_and_parse_output: crucial change to return all_md_lines for separator check
def run_dirdigest_and_parse_output(
    runner: CliRunner, command_args: list[str], project_dir: pathlib.Path
) -> tuple[dict | None, list[str] | None, list[str] | None]: # Added list[str] for all_md_lines
    full_command = ["--config", "non_existent_config.toml"] + command_args
    if project_dir:
        full_command = [str(project_dir)] + full_command


    result = runner.invoke(main_cli, full_command, catch_exceptions=False)
    assert result.exit_code == 0, f"Dirdigest CLI failed. Output:\n{result.output}\nStderr:\n{result.stderr}"

    output_content = result.stdout

    parsed_json = None
    markdown_log_lines = [] # Store parsed - item lines
    all_markdown_lines_in_log_section = [] # Store all lines in log section including separators

    if "--format" in command_args and "json" in command_args[command_args.index("--format") + 1]:
        try:
            parsed_json = json.loads(output_content)
        except json.JSONDecodeError:
            pytest.fail(f"Failed to parse JSON output: {output_content}")
        # For JSON, we don't populate markdown_log_lines or all_markdown_lines_in_log_section
        return parsed_json, None, None
    else: # Markdown by default
        raw_md_lines = output_content.splitlines()
        in_processing_log_section = False
        for line_num, line_content in enumerate(raw_md_lines):
            stripped_line = line_content.strip()
            if stripped_line == "## Processing Log":
                in_processing_log_section = True
                continue
            if in_processing_log_section:
                all_markdown_lines_in_log_section.append(stripped_line) # Add raw line
                if stripped_line.startswith("- "):
                    markdown_log_lines.append(stripped_line) # Add parsed item line
                # Check if this is the final "---" that ends the Processing Log section
                # This assumes the "---" after the log is the immediate next non-empty line or specific structure
                # For simplicity, let's assume the section ends if we see "---" and it's not part of an item,
                # or if we hit another "##" section header.
                if stripped_line == "---" and (line_num + 1 < len(raw_md_lines) and raw_md_lines[line_num+1].strip().startswith("## ")):
                    all_markdown_lines_in_log_section.pop() # Remove this final "---" as it's a section ender
                    break
                if stripped_line.startswith("## ") and stripped_line != "## Processing Log": # Next section started
                    if all_markdown_lines_in_log_section and all_markdown_lines_in_log_section[-1] == "---":
                         all_markdown_lines_in_log_section.pop() # Remove trailing separator if it's the last thing before next heading
                    break
        # Remove trailing "---" if it's the last line captured and it's the section ender
        if all_markdown_lines_in_log_section and all_markdown_lines_in_log_section[-1] == "---":
            is_last_line_section_ender = True
            # Heuristic: if the line after "---" in original output is a new section or empty then it's an ender
            original_index_of_this_line = -1
            temp_line_counter = 0
            in_temp_section = False
            for i, l_content in enumerate(output_content.splitlines()):
                s_line = l_content.strip()
                if s_line == "## Processing Log": in_temp_section = True; continue
                if in_temp_section:
                    temp_line_counter +=1
                    if temp_line_counter == len(all_markdown_lines_in_log_section): # this '---' is the one in question
                        original_index_of_this_line = i
                        break
            if original_index_of_this_line != -1 and original_index_of_this_line + 1 < len(output_content.splitlines()):
                next_original_line = output_content.splitlines()[original_index_of_this_line+1].strip()
                if next_original_line.startswith("## ") or not next_original_line:
                    all_markdown_lines_in_log_section.pop()
            elif original_index_of_this_line != -1 and original_index_of_this_line + 1 == len(output_content.splitlines()): # last line
                 all_markdown_lines_in_log_section.pop()


    return parsed_json, markdown_log_lines, all_markdown_lines_in_log_section


# Helper to extract relevant parts (same as before)
def parse_log_line(log_line: str) -> dict:
    parts = {}
    status_type_part = log_line[2:].split(" [Size:", 1)[0]
    parts["status"] = status_type_part.split(" ", 1)[0]
    parts["type"] = status_type_part.split(" ", 1)[1]

    try:
        size_str = log_line.split("[Size: ", 1)[1].split("KB]", 1)[0]
        parts["size_kb"] = float(size_str) if size_str != "N/A" else 0.0
    except IndexError:
        parts["size_kb"] = 0.0

    path_part_full = log_line.split("]: ", 1)[1]
    if " (" in path_part_full:
        parts["path"] = path_part_full.split(" (", 1)[0].strip("`")
        parts["reason"] = path_part_full.split(" (", 1)[1].rstrip(")")
    else:
        parts["path"] = path_part_full.strip("`")
        parts["reason"] = None
    return parts

def assert_log_item_details(actual_item, expected_item, item_index, sort_desc=""):
    assert actual_item['status'] == expected_item['status'], f"Item {item_index} status mismatch for {expected_item['path']} ({sort_desc})"
    assert actual_item['type'] == expected_item['type'], f"Item {item_index} type mismatch for {expected_item['path']} ({sort_desc})"
    assert actual_item['path'] == expected_item['path'], f"Item {item_index} path mismatch. Expected {expected_item['path']}, Got {actual_item['path']} ({sort_desc})"
    if actual_item['type'] == 'File':
        assert abs(actual_item['size_kb'] - expected_item.get('size_kb', 0.0)) < 0.01, \
            f"Item {item_index} size mismatch for {expected_item['path']}. Expected {expected_item.get('size_kb', 0.0)}, Got {actual_item['size_kb']} ({sort_desc})"
    if 'reason' in expected_item:
        assert actual_item.get('reason') == expected_item.get('reason'), f"Item {item_index} reason mismatch for {expected_item['path']} ({sort_desc})"

def check_separator_logic(all_log_section_lines: list[str], expect_separator: bool, sort_desc: str):
    has_excluded = any(line.startswith("- Excluded") for line in all_log_section_lines)
    has_included = any(line.startswith("- Included") for line in all_log_section_lines)

    separator_found_correctly = False
    if expect_separator and has_excluded and has_included:
        for i in range(len(all_log_section_lines) - 1):
            if all_log_section_lines[i].startswith("- Excluded") and \
               all_log_section_lines[i+1] == "---" and \
               (i+2 < len(all_log_section_lines) and all_log_section_lines[i+2].startswith("- Included")):
                separator_found_correctly = True
                break
        assert separator_found_correctly, f"Separator '---' was EXPECTED but not found correctly between Excluded and Included groups for {sort_desc}."
    elif not expect_separator:
        incorrect_separator_found = False
        for i in range(len(all_log_section_lines) - 1):
            if all_log_section_lines[i].startswith("- Excluded") and \
               all_log_section_lines[i+1] == "---" and \
               (i+2 < len(all_log_section_lines) and all_log_section_lines[i+2].startswith("- Included")):
                incorrect_separator_found = True
                break
        assert not incorrect_separator_found, f"Separator '---' was NOT EXPECTED but found between Excluded and Included groups for {sort_desc}."


# --- Test Cases ---

def test_default_sort_order_and_format_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test default sort order (status, size) and Markdown format. Expect separator."""
    _, parsed_log_lines, all_log_section_lines = run_dirdigest_and_parse_output(
        runner, ["--no-clipboard"], test_dir_structure
    )
    assert parsed_log_lines is not None
    assert all_log_section_lines is not None
    parsed_log_items = [parse_log_line(line) for line in parsed_log_lines]

    # Default sort: ['status', 'size'] -> Excluded first, then type (folder), then path for folders / -size,path for files
    expected_items = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'size_kb':0.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        # Separator expected here
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0}, # 13 bytes
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0}, # 7 bytes
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0}, # 13 bytes
    ]
    assert len(parsed_log_items) == len(expected_items)
    for i, actual in enumerate(parsed_log_items):
        assert_log_item_details(actual, expected_items[i], i, "default sort")
    check_separator_logic(all_log_section_lines, expect_separator=True, sort_desc="default sort")


def test_sort_by_size_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test '--sort-output-log-by size'. Expect separator as status is primary implicit key."""
    _, parsed_log_lines, all_log_section_lines = run_dirdigest_and_parse_output(
        runner, ["--sort-output-log-by", "size", "--no-clipboard"], test_dir_structure
    )
    assert parsed_log_lines is not None
    assert all_log_section_lines is not None
    parsed_log_items = [parse_log_line(line) for line in parsed_log_lines]

    # Sort: ['size'] -> Status, Type, then Path for Folders / -Size,Path for Files
    expected_items = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'size_kb':0.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        # Separator expected here
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
    ]
    assert len(parsed_log_items) == len(expected_items)
    for i, actual in enumerate(parsed_log_items):
        assert_log_item_details(actual, expected_items[i], i, "sort by size")
    check_separator_logic(all_log_section_lines, expect_separator=True, sort_desc="sort by size")


def test_sort_by_status_path_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test '--sort-output-log-by status --sort-output-log-by path'. Expect separator."""
    _, parsed_log_lines, all_log_section_lines = run_dirdigest_and_parse_output(
        runner, ["--sort-output-log-by", "status", "--sort-output-log-by", "path", "--no-clipboard"], test_dir_structure
    )
    assert parsed_log_lines is not None
    assert all_log_section_lines is not None
    parsed_log_items = [parse_log_line(line) for line in parsed_log_lines]

    # Sort: ['status', 'path'] -> Status, Type, Path
    expected_items = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'reason': 'Is a hidden file'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'reason': 'Matches default ignore pattern'},
        # Separator expected here
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py'},
    ]
    assert len(parsed_log_items) == len(expected_items)
    for i, actual in enumerate(parsed_log_items):
        assert_log_item_details(actual, expected_items[i], i, "sort by status, path")
    check_separator_logic(all_log_section_lines, expect_separator=True, sort_desc="sort by status, path")


def test_sort_by_path_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test '--sort-output-log-by path'. No status grouping, no separator expected between status groups."""
    _, parsed_log_lines, all_log_section_lines = run_dirdigest_and_parse_output(
        runner, ["--sort-output-log-by", "path", "--no-clipboard"], test_dir_structure
    )
    assert parsed_log_lines is not None
    assert all_log_section_lines is not None
    parsed_log_items = [parse_log_line(line) for line in parsed_log_lines]

    # Sort: ['path'] -> Path, Type
    expected_items = [
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt'},
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'reason': 'Matches default ignore pattern'},
    ]
    assert len(parsed_log_items) == len(expected_items)
    for i, actual in enumerate(parsed_log_items):
        assert_log_item_details(actual, expected_items[i], i, "sort by path")
    check_separator_logic(all_log_section_lines, expect_separator=False, sort_desc="sort by path")


def test_sort_by_size_path_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test '--sort-output-log-by size --sort-output-log-by path'. No status grouping, no separator."""
    _, parsed_log_lines, all_log_section_lines = run_dirdigest_and_parse_output(
        runner, ["--sort-output-log-by", "size", "--sort-output-log-by", "path", "--no-clipboard"], test_dir_structure
    )
    assert parsed_log_lines is not None
    assert all_log_section_lines is not None
    parsed_log_items = [parse_log_line(line) for line in parsed_log_lines]

    # Sort: ['size', 'path'] -> Type, then Path for Folders / -Size,Path for Files
    expected_items = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
    ]
    assert len(parsed_log_items) == len(expected_items)
    for i, actual in enumerate(parsed_log_items):
        assert_log_item_details(actual, expected_items[i], i, "sort by size, path")
    check_separator_logic(all_log_section_lines, expect_separator=False, sort_desc="sort by size, path")


def test_json_output_with_default_sort(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test JSON output format with default sort. Checks metadata and processing_log order."""
    parsed_json, _, _ = run_dirdigest_and_parse_output(
        runner, ["--format", "json", "--no-clipboard"], test_dir_structure
    )
    assert parsed_json is not None
    assert parsed_json['metadata']['sort_options_used'] == DEFAULT_SORT_ORDER

    processing_log = parsed_json['processing_log']
    # Expected order from default sort (status, size)
    expected_json_items = [
        {'status': 'excluded', 'type': 'folder', 'path': 'node_modules', 'size_kb':0.0, 'reason_excluded': 'Matches default ignore pattern'},
        {'status': 'excluded', 'type': 'file', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason_excluded': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'excluded', 'type': 'file', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason_excluded': 'Matches default ignore pattern'},
        {'status': 'excluded', 'type': 'file', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason_excluded': 'Is a hidden file'},
        {'status': 'included', 'type': 'file', 'path': 'file_beta_large.txt', 'size_kb': 2.5, 'reason_excluded': None},
        {'status': 'included', 'type': 'file', 'path': 'file_alpha.txt', 'size_kb': 0.0, 'reason_excluded': None},
        {'status': 'included', 'type': 'file', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0, 'reason_excluded': None},
        {'status': 'included', 'type': 'file', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0, 'reason_excluded': None},
    ]
    assert len(processing_log) == len(expected_json_items)
    for i, actual_item_json in enumerate(processing_log):
        expected_item = expected_json_items[i]
        assert actual_item_json['path'] == str(expected_item['path'])
        assert actual_item_json['type'] == expected_item['type']
        assert actual_item_json['status'] == expected_item['status'] # JSON status is already lowercase
        if actual_item_json['type'] == 'file':
            assert abs(actual_item_json['size_kb'] - expected_item['size_kb']) < 0.01
        assert actual_item_json.get('reason_excluded') == expected_item.get('reason_excluded')
        # Check all expected fields are present
        assert all(k in actual_item_json for k in ["path", "type", "status", "size_kb", "reason_excluded"])

```
