import json
import pathlib
import pytest
from click.testing import CliRunner

from dirdigest.cli import main_cli
from dirdigest.constants import DEFAULT_SORT_ORDER, SORT_OPTIONS

# Helper function to create a directory structure
def create_test_files(base_path: pathlib.Path, structure: dict):
    """
    Creates files and directories based on the structure.
    Example structure:
    {
        "file1.txt": "content1", (size: 8 bytes)
        "file_large.txt": "a" * 2048, (size: 2KB)
        "sub_dir/file2.py": "print('hello')", (size: 14 bytes)
        "sub_dir/empty.txt": "", (size: 0 bytes)
        ".hidden_file.txt": "hidden",
        "node_modules/some_lib/index.js": "content", # Excluded by default
        "big_file.bin": "b" * 500 * 1024 # 500KB, excluded by default max_size (300KB)
    }
    """
    for name, content in structure.items():
        path = base_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str): # It's a file
            path.write_text(content, encoding="utf-8")
        elif isinstance(content, dict): # It's a directory (implicitly created by children)
            create_test_files(path, content) # Recursively create
        # Add more types if needed, e.g. for symlinks later

@pytest.fixture
def test_dir_structure(tmp_path: pathlib.Path) -> pathlib.Path:
    """Creates a standard test directory structure for sorting and formatting tests."""
    base = tmp_path / "test_project"
    base.mkdir()

    structure = {
        "file_alpha.txt": "alpha content",          # included, ~13 bytes
        "file_beta_large.txt": "beta content " * 200, # included, ~2.6KB
        "sub_dir/file_gamma.py": "print('gamma')",   # included, 13 bytes
        "sub_dir/file_delta_small.md": "# delta",   # included, 7 bytes
        "sub_dir_empty/": {},                       # included (empty dir)
        ".ignored_hidden.txt": "hidden data",       # excluded (hidden)
        "node_modules/lib.js": "some js code",      # excluded (default pattern)
        "temp_files/big_file.log": "log" * 100000,  # excluded (>300KB if log*100k is large enough, ~0.3MB), also by pattern
                                                    # Let's make it clearly > 300KB
                                                    # 300KB = 300 * 1024 bytes = 307200 bytes
                                                    # "log" is 3 bytes. 3 * 102400 = 307200. So "log" * 102401
        "temp_files/another_big_file.data": "d" * (301 * 1024) # excluded (size)
    }
    create_test_files(base, structure)

    # Create an empty file explicitly for sub_dir_empty if not handled by create_test_files
    (base / "sub_dir_empty").mkdir(parents=True, exist_ok=True) # Ensure it exists as a dir

    return base

def run_dirdigest_and_parse_output(
    runner: CliRunner, command_args: list[str], project_dir: pathlib.Path
) -> tuple[dict | None, list[str] | None, dict | None]:
    """
    Runs dirdigest with given args and returns parsed JSON, Markdown log, and full Markdown.
    Returns (parsed_json, markdown_log_lines, raw_markdown_lines)
    """
    full_command = ["--config", "non_existent_config.toml"] + command_args # Avoid loading default config
    if project_dir:
        full_command.insert(0, str(project_dir))

    result = runner.invoke(main_cli, full_command, catch_exceptions=False)
    assert result.exit_code == 0, f"Dirdigest CLI failed. Output:\n{result.output}\nStderr:\n{result.stderr}"

    output_content = result.stdout

    parsed_json = None
    markdown_log_lines = None
    raw_markdown_lines = None

    if "--format" in command_args and "json" in command_args:
        try:
            parsed_json = json.loads(output_content)
        except json.JSONDecodeError:
            pytest.fail(f"Failed to parse JSON output: {output_content}")
    else: # Markdown by default
        raw_markdown_lines = output_content.splitlines()
        in_processing_log_section = False
        markdown_log_lines = []
        for line in raw_markdown_lines:
            if line.strip() == "## Processing Log":
                in_processing_log_section = True
                continue
            if in_processing_log_section:
                if line.strip() == "---": # End of section
                    break
                if line.strip().startswith("- "): # Log item
                    markdown_log_lines.append(line.strip())

    return parsed_json, markdown_log_lines, raw_markdown_lines


# Helper to extract relevant parts from a parsed Markdown log line
def parse_log_line(log_line: str) -> dict:
    parts = {}
    # Example: "- Included File [Size: 13.0KB]: file_alpha.txt"
    # Example: "- Excluded Folder [Size: 0.0KB]: node_modules (Matches default ignore pattern)"

    # Status and Type
    status_type_part = log_line[2:].split(" [Size:")[0] # Remove "- " prefix
    parts["status"] = status_type_part.split(" ")[0]
    parts["type"] = status_type_part.split(" ")[1]

    # Size
    try:
        size_str = log_line.split("[Size: ")[1].split("KB]")[0]
        parts["size_kb"] = float(size_str) if size_str != "N/A" else 0.0 # Treat N/A as 0 for sorting comparison
    except IndexError:
        parts["size_kb"] = 0.0 # Or some other default if size is missing

    # Path
    path_part = log_line.split("]: ")[1]
    if " (" in path_part: # Has reason
        parts["path"] = path_part.split(" (")[0].strip("`")
        parts["reason"] = path_part.split(" (")[1].rstrip(")")
    else:
        parts["path"] = path_part.strip("`")
        parts["reason"] = None
    return parts


# --- Test Cases ---

def test_default_sort_order_and_format_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test default sort order (status, size) and Markdown format."""
    _, log_lines, _ = run_dirdigest_and_parse_output(
        runner, ["--no-clipboard"], test_dir_structure # no-clipboard to avoid issues in CI
    )
    assert log_lines is not None

    parsed_log_items = [parse_log_line(line) for line in log_lines]

    # Expected order:
    # 1. Excluded Folders (by path asc)
    #    - node_modules (Matches default ignore pattern)
    # 2. Excluded Files (by size desc, then path asc)
    #    - temp_files/another_big_file.data (Exceeds max size...)
    #    - temp_files/big_file.log (Exceeds max size...)
    #    - .ignored_hidden.txt (Is a hidden file)
    # 3. Included Folders (by path asc) - these are not explicitly in the log unless they also have a status like excluded
    #    The current log lists all items it makes a decision on. Empty included folders are not listed.
    #    Let's verify based on what IS logged.
    #    - sub_dir
    #    - sub_dir_empty
    # 4. Included Files (by size desc, then path asc)
    #    - file_beta_large.txt
    #    - file_alpha.txt
    #    - sub_dir/file_gamma.py
    #    - sub_dir/file_delta_small.md

    # Define expected items with their properties for easier assertion
    # Sizes are approximate from file contents. Exact sizes depend on OS (newlines)
    # file_alpha.txt: "alpha content" -> 13 bytes -> 0.0KB (or 0.013KB)
    # file_beta_large.txt: "beta content " * 200 -> 13 * 200 = 2600 bytes -> 2.5KB
    # sub_dir/file_gamma.py: "print('gamma')" -> 13 bytes -> 0.0KB
    # sub_dir/file_delta_small.md: "# delta" -> 7 bytes -> 0.0KB
    # .ignored_hidden.txt: "hidden data" -> 11 bytes -> 0.0KB
    # node_modules/lib.js: "some js code" -> 12 bytes -> 0.0KB
    # temp_files/another_big_file.data: 301 * 1024 -> 301.0KB
    # temp_files/big_file.log: "log" * 102401 -> 3 * 102401 = 307203 bytes -> 300.0KB (approx, due to rounding in output)

    # Note: Default max-size is 300KB.
    # temp_files/big_file.log should be ~300.0KB, temp_files/another_big_file.data is 301.0KB.

    expected_paths_ordered = [
        # Excluded Folders (sorted by path alphabetically)
        "node_modules", # Excluded by pattern
        # Excluded Files (sorted by size desc, then path)
        "temp_files/another_big_file.data", # 301.0KB, Excluded by size
        "temp_files/big_file.log",          # ~300.0KB, Excluded by size (or pattern if it matches one)
                                            # In constants.py, `*.log` is a default ignore pattern.
                                            # So, it will be "Matches default ignore pattern"
        ".ignored_hidden.txt",              # 0.0KB (hidden file)
        # Included Folders (these are not directly in the log unless they have a specific status like excluded)
        # The log shows items process_directory_recursive yields.
        # Included files (sorted by size desc, then path)
        "file_beta_large.txt",      # 2.5KB
        "file_alpha.txt",           # 0.0KB
        "sub_dir/file_gamma.py",    # 0.0KB
        "sub_dir/file_delta_small.md", # 0.0KB
        # What about sub_dir and sub_dir_empty?
        # Folders are only listed if they are EXCLUDED. Included folders are implicitly part of paths of included files.
        # The "Processing Log" should list all items that `process_directory_recursive` yields decisions for.
        # `process_directory_recursive` yields excluded folders.
        # It does not yield "included folders" as separate loggable items. They are part of the structure.
    ]

    # Let's refine expected_paths_ordered based on actual log items
    # Status: Excluded, Type: Folder, Path: node_modules, Reason: Matches default ignore pattern
    # Status: Excluded, Type: File, Path: temp_files/another_big_file.data, Reason: Exceeds max size
    # Status: Excluded, Type: File, Path: temp_files/big_file.log, Reason: Matches default ignore pattern (or size)
    # Status: Excluded, Type: File, Path: .ignored_hidden.txt, Reason: Is a hidden file
    # Status: Included, Type: File, Path: file_beta_large.txt
    # Status: Included, Type: File, Path: file_alpha.txt
    # Status: Included, Type: File, Path: sub_dir/file_gamma.py
    # Status: Included, Type: File, Path: sub_dir/file_delta_small.md

    actual_paths_ordered = [item['path'] for item in parsed_log_items]
    print("Actual paths ordered:", actual_paths_ordered) # For debugging during test development

    # Assertions need to be precise based on the sorting logic in core.py:
    # Sort key: (status_order, type_order, size_for_sort, path_for_sort)
    # status_order: 0 for 'included', 1 for 'excluded'
    # type_order: 0 for 'folder', 1 for 'file'
    # size_for_sort: -size_kb for files (desc), 0 for folders

    # Expected sorted sequence (conceptual groups):
    # Group 1: Included Folders (status=0, type=0) - Not logged explicitly unless also excluded.
    # Group 2: Included Files (status=0, type=1) - Sorted by -size, then path
    # Group 3: Excluded Folders (status=1, type=0) - Sorted by path (size is 0)
    # Group 4: Excluded Files (status=1, type=1) - Sorted by -size, then path

    # So, the log should show:
    # 1. Included Files (size desc, then path asc)
    #    - file_beta_large.txt (2.5KB)
    #    - file_alpha.txt (0.0KB)
    #    - sub_dir/file_delta_small.md (0.0KB) path: sub_dir/file_delta_small.md
    #    - sub_dir/file_gamma.py (0.0KB)   path: sub_dir/file_gamma.py
    # 2. Excluded Folders (path asc)
    #    - node_modules
    # 3. Excluded Files (size desc, then path asc)
    #    - temp_files/another_big_file.data (301.0KB)
    #    - temp_files/big_file.log (approx 300.0KB, reason: matches default ignore)
    #    - .ignored_hidden.txt (0.0KB, reason: hidden)

    # Need to verify sizes from debug output of dirdigest if these are not exact
    # file_alpha.txt (13B -> 0.0KB), file_beta_large.txt (2600B -> 2.5KB),
    # file_gamma.py (13B -> 0.0KB), file_delta_small.md (7B -> 0.0KB)
    # .ignored_hidden.txt (11B -> 0.0KB)
    # node_modules/lib.js (12B -> 0.0KB) - this one should be listed as excluded!
    # temp_files/another_big_file.data (308224B -> 301.0KB)
    # temp_files/big_file.log (307203B -> 300.0KB)

    expected_log_item_details = [
        # Included Files
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0}, # 13 bytes
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0}, # 7 bytes
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0}, # 13 bytes
        # Excluded Folders
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        # Excluded Files
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason': 'Matches default ignore pattern'}, # Also large, but pattern takes precedence if checked first
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason': 'Is a hidden file'}, # 11 bytes
        # node_modules/lib.js will be inside node_modules, which is excluded as a whole.
        # So, individual files inside an excluded dir are not typically listed again unless traversal goes there first.
        # If node_modules itself is excluded, its contents are not processed further to be listed.
    ]

    assert len(parsed_log_items) == len(expected_log_item_details), \
        f"Mismatch in number of log items. Got {len(parsed_log_items)}, expected {len(expected_log_item_details)}." \
        f"\nActual items: {actual_paths_ordered}"


    for i, actual_item in enumerate(parsed_log_items):
        expected_item = expected_log_item_details[i]
        assert actual_item['status'] == expected_item['status'], f"Item {i} status mismatch for {expected_item['path']}"
        assert actual_item['type'] == expected_item['type'], f"Item {i} type mismatch for {expected_item['path']}"
        assert actual_item['path'] == expected_item['path'], f"Item {i} path mismatch. Expected {expected_item['path']}, Got {actual_item['path']}"
        # Size comparison for files, allow small tolerance for floats
        if actual_item['type'] == 'File':
             assert abs(actual_item['size_kb'] - expected_item['size_kb']) < 0.01, \
                 f"Item {i} size mismatch for {expected_item['path']}. Expected {expected_item['size_kb']}, Got {actual_item['size_kb']}"
        if 'reason' in expected_item:
            assert actual_item['reason'] == expected_item['reason'], f"Item {i} reason mismatch for {expected_item['path']}"
        else:
            assert actual_item.get('reason') is None, f"Item {i} unexpected reason for {expected_item['path']}: {actual_item.get('reason')}"


def test_sort_by_size_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test '--sort-output-log-by size' and Markdown format."""
    _, log_lines, _ = run_dirdigest_and_parse_output(
        runner, ["--sort-output-log-by", "size", "--no-clipboard"], test_dir_structure
    )
    assert log_lines is not None
    parsed_log_items = [parse_log_line(line) for line in log_lines]

    # Expected order with "--sort-output-log-by size":
    # Folders first (sorted by path), then Files (sorted by -size, then path)
    # 1. Excluded Folders (by path) - Size sort puts folders before files.
    #    - node_modules
    # 2. Files (by size desc, then path asc), irrespective of status.
    #    - temp_files/another_big_file.data (Excluded, 301.0KB)
    #    - temp_files/big_file.log (Excluded, 300.0KB)
    #    - file_beta_large.txt (Included, 2.5KB)
    #    - file_alpha.txt (Included, 0.0KB)
    #    - .ignored_hidden.txt (Excluded, 0.0KB)
    #    - sub_dir/file_delta_small.md (Included, 0.0KB)
    #    - sub_dir/file_gamma.py (Included, 0.0KB)

    expected_log_item_details = [
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules', 'reason': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log', 'size_kb': 300.0},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        # Files with 0.0KB, sorted by path
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt', 'size_kb': 0.0}, # path: .ignored_hidden.txt
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt', 'size_kb': 0.0},      # path: file_alpha.txt
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0}, # path: sub_dir/file_delta_small.md
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},   # path: sub_dir/file_gamma.py
    ]

    actual_paths_ordered = [item['path'] for item in parsed_log_items]
    print("Actual paths ordered (sort by size):", actual_paths_ordered)

    assert len(parsed_log_items) == len(expected_log_item_details), \
        f"Mismatch in number of log items. Got {len(parsed_log_items)}, expected {len(expected_log_item_details)}." \
        f"\nActual items: {actual_paths_ordered}"

    for i, actual_item in enumerate(parsed_log_items):
        expected_item = expected_log_item_details[i]
        assert actual_item['status'] == expected_item['status'], f"Item {i} status mismatch for {expected_item['path']}"
        assert actual_item['type'] == expected_item['type'], f"Item {i} type mismatch for {expected_item['path']}"
        assert actual_item['path'] == expected_item['path'], f"Item {i} path mismatch. Expected {expected_item['path']}, Got {actual_item['path']}"
        if actual_item['type'] == 'File':
             assert abs(actual_item['size_kb'] - expected_item['size_kb']) < 0.01, \
                 f"Item {i} size mismatch for {expected_item['path']}. Expected {expected_item['size_kb']}, Got {actual_item['size_kb']}"
        # Reason is not checked here as it's not part of primary sort criteria for this test


def test_sort_by_status_path_markdown(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test '--sort-output-log-by status --sort-output-log-by path' and Markdown format."""
    _, log_lines, _ = run_dirdigest_and_parse_output(
        runner, ["--sort-output-log-by", "status", "--sort-output-log-by", "path", "--no-clipboard"], test_dir_structure
    )
    assert log_lines is not None
    parsed_log_items = [parse_log_line(line) for line in log_lines]

    # Expected order with "status", "path":
    # Grouped by status (Included first), then by type (Folder first), then by path. Size is secondary tie-breaker.
    # 1. Included Folders (by path) - Not logged unless also excluded.
    # 2. Included Files (by path asc)
    #    - file_alpha.txt
    #    - file_beta_large.txt
    #    - sub_dir/file_delta_small.md
    #    - sub_dir/file_gamma.py
    # 3. Excluded Folders (by path asc)
    #    - node_modules
    # 4. Excluded Files (by path asc)
    #    - .ignored_hidden.txt
    #    - temp_files/another_big_file.data
    #    - temp_files/big_file.log

    expected_log_item_details = [
        # Included Files (sorted by path)
        {'status': 'Included', 'type': 'File', 'path': 'file_alpha.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'file_beta_large.txt'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_delta_small.md'},
        {'status': 'Included', 'type': 'File', 'path': 'sub_dir/file_gamma.py'},
        # Excluded Folders (sorted by path)
        {'status': 'Excluded', 'type': 'Folder', 'path': 'node_modules'},
        # Excluded Files (sorted by path)
        {'status': 'Excluded', 'type': 'File', 'path': '.ignored_hidden.txt'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/another_big_file.data'},
        {'status': 'Excluded', 'type': 'File', 'path': 'temp_files/big_file.log'},
    ]

    actual_paths_ordered = [item['path'] for item in parsed_log_items]
    print("Actual paths ordered (sort by status, path):", actual_paths_ordered)

    assert len(parsed_log_items) == len(expected_log_item_details), \
        f"Mismatch in number of log items. Got {len(parsed_log_items)}, expected {len(expected_log_item_details)}." \
        f"\nActual items: {actual_paths_ordered}"

    for i, actual_item in enumerate(parsed_log_items):
        expected_item = expected_log_item_details[i]
        assert actual_item['status'] == expected_item['status'], f"Item {i} status mismatch for {expected_item['path']}"
        assert actual_item['type'] == expected_item['type'], f"Item {i} type mismatch for {expected_item['path']}"
        assert actual_item['path'] == expected_item['path'], f"Item {i} path mismatch. Expected {expected_item['path']}, Got {actual_item['path']}"
        # Size and Reason are not primary sort keys here, so not strictly checked for order based on them.


def test_json_output_with_default_sort(runner: CliRunner, test_dir_structure: pathlib.Path):
    """Test JSON output format, including metadata.sort_options_used and processing_log order."""
    parsed_json, _, _ = run_dirdigest_and_parse_output(
        runner, ["--format", "json", "--no-clipboard"], test_dir_structure
    )
    assert parsed_json is not None

    # Check metadata for sort_options_used
    assert parsed_json['metadata']['sort_options_used'] == DEFAULT_SORT_ORDER # ['status', 'size']

    # Check processing_log items structure and order (same as default Markdown test)
    processing_log = parsed_json['processing_log']
    assert len(processing_log) > 0 # Ensure log is not empty

    # Expected order is same as `test_default_sort_order_and_format_markdown`
    expected_log_item_details = [
        {'status': 'Included', 'type': 'file', 'path': 'file_beta_large.txt', 'size_kb': 2.5},
        {'status': 'Included', 'type': 'file', 'path': 'file_alpha.txt', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'file', 'path': 'sub_dir/file_delta_small.md', 'size_kb': 0.0},
        {'status': 'Included', 'type': 'file', 'path': 'sub_dir/file_gamma.py', 'size_kb': 0.0},
        {'status': 'Excluded', 'type': 'folder', 'path': 'node_modules', 'reason_excluded': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'file', 'path': 'temp_files/another_big_file.data', 'size_kb': 301.0, 'reason_excluded': 'Exceeds max size (301.0KB > 300KB)'},
        {'status': 'Excluded', 'type': 'file', 'path': 'temp_files/big_file.log', 'size_kb': 300.0, 'reason_excluded': 'Matches default ignore pattern'},
        {'status': 'Excluded', 'type': 'file', 'path': '.ignored_hidden.txt', 'size_kb': 0.0, 'reason_excluded': 'Is a hidden file'},
    ]

    assert len(processing_log) == len(expected_log_item_details)

    for i, actual_item_json in enumerate(processing_log):
        expected_item = expected_log_item_details[i]
        # In JSON, paths are strings, not pathlib.Path objects, so direct comparison.
        assert actual_item_json['path'] == str(expected_item['path']) # Ensure path is string
        assert actual_item_json['type'] == expected_item['type']
        assert actual_item_json['status'] == expected_item['status'].lower() # JSON uses lowercase status

        # Size comparison for files
        if actual_item_json['type'] == 'file':
             assert abs(actual_item_json['size_kb'] - expected_item['size_kb']) < 0.01

        if 'reason_excluded' in expected_item: # JSON uses reason_excluded
            assert actual_item_json['reason_excluded'] == expected_item['reason_excluded']
        else:
            assert actual_item_json.get('reason_excluded') is None

        # Check all expected fields are present
        assert "path" in actual_item_json
        assert "type" in actual_item_json
        assert "status" in actual_item_json
        assert "size_kb" in actual_item_json
        assert "reason_excluded" in actual_item_json # Should always be there, None if not excluded
```
