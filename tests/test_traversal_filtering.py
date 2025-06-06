# tests/test_traversal_filtering.py

import json
import os
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from dirdigest import cli as dirdigest_cli


# Helper function to extract relative paths from JSON output
def get_included_files_from_json(json_output_str: str) -> set[str]:
    """Parses JSON output and returns a set of relative_path for all included 'file' type nodes."""
    try:
        data = json.loads(json_output_str)
    except json.JSONDecodeError as e:
        pytest.fail(f"Output was not valid JSON for helper. Error: {e}. Output: '{json_output_str[:500]}...'")

    included_files = set()

    def recurse_node(node):
        if not node:
            return
        if node.get("type") == "file":
            if "relative_path" in node:
                included_files.add(node["relative_path"].replace(os.sep, "/"))

        if "children" in node and isinstance(node["children"], list):
            for child in node["children"]:
                recurse_node(child)

    if "root" in data:
        recurse_node(data["root"])

    return included_files


# --- Test Cases ---


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_basic_traversal_simple_project_default_ignores(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-001 (Conceptual)
    Description: Verifies basic traversal on a simple project with default ignore patterns active.
    Checks that standard text/code files are included.
    Output format is JSON for easier parsing of included files.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "json", "--no-clipboard"])
            if mock_rich_print.call_args_list:
                full_output_parts = []
                for call_obj in mock_rich_print.call_args_list:
                    for arg in call_obj.args:
                        full_output_parts.append(str(arg))
                json_output_str = "".join(full_output_parts)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}\nOutput: {result.output}"
    included_files = get_included_files_from_json(json_output_str)
    expected_files = {
        "file1.txt",
        "file2.md",
        "sub_dir1/script.py",
    }
    assert included_files == expected_files


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_default_ignores_complex_project(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-009 (Conceptual)
    Description: Verifies default ignore patterns on a complex project.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "json", "--no-clipboard"])
            if mock_rich_print.call_args_list:
                full_output_parts = []
                for call_obj in mock_rich_print.call_args_list:
                    for arg in call_obj.args:
                        full_output_parts.append(str(arg))
                json_output_str = "".join(full_output_parts)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}\nOutput: {result.output}"
    included_files = get_included_files_from_json(json_output_str)

    expected_to_be_included = {
        "README.md",
        "config.yaml",
        "src/main.py",
        "src/utils.py",
        "src/feature/module.py",
        "tests/test_main.py",
        "tests/test_utils.py",
        "docs/index.md",
        "docs/api.md",
        "data/small_data.csv",
    }
    assert included_files == expected_to_be_included, (
        f"Mismatch in included files. Got: {included_files}, Expected: {expected_to_be_included}"
    )

    excluded_patterns_to_check_are_absent = [
        ".env",
        ".git/",
        "__pycache__/",
        "build/",
        "node_modules/",
        "data/temp.log",
    ]
    for pattern_str in excluded_patterns_to_check_are_absent:
        if pattern_str.endswith("/"):
            for_test_pattern = pattern_str.rstrip("/")
            found_in_excluded_dir = [f for f in included_files if f.startswith(for_test_pattern + "/")]
            assert not found_in_excluded_dir, (
                f"Files from default-ignored dir '{pattern_str}' found: {found_in_excluded_dir}"
            )
        else:
            assert pattern_str not in included_files, f"Default-ignored file '{pattern_str}' was included."


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_no_default_ignore_flag(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-010 (Conceptual)
    Description: Verifies '--no-default-ignore' disables default ignores.
    Real .pyc files will still be excluded due to UnicodeDecodeError unless --ignore-errors is on.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--no-default-ignore", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                full_output_parts = []
                for call_obj in mock_rich_print.call_args_list:
                    for arg in call_obj.args:
                        full_output_parts.append(str(arg))
                json_output_str = "".join(full_output_parts)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}\nOutput: {result.output}"
    included_files = get_included_files_from_json(json_output_str)

    expected_after_no_default_ignore = {
        "README.md",
        "config.yaml",
        ".env",
        "src/main.py",
        "src/utils.py",
        "src/feature/module.py",
        "tests/test_main.py",
        "tests/test_utils.py",
        "docs/index.md",
        "docs/api.md",
        "data/small_data.csv",
        "data/temp.log",
        ".git/HEAD",
        "__pycache__/utils.cpython-39.pyc",  # This one is text, should be included.
        "node_modules/placeholder.js",
        # Real binary .pyc files created by pytest in tests/__pycache__ will be excluded due to read error.
    }
    assert included_files == expected_after_no_default_ignore


@pytest.mark.parametrize("temp_test_dir", ["hidden_files_dir"], indirect=True)
def test_hidden_files_default_exclusion(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-011 (Conceptual)
    Description: Verifies default exclusion of hidden files/directories.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "json", "--no-clipboard"])
            if mock_rich_print.call_args_list:
                full_output_parts = []
                for call_obj in mock_rich_print.call_args_list:
                    for arg in call_obj.args:
                        full_output_parts.append(str(arg))
                json_output_str = "".join(full_output_parts)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}\nOutput: {result.output}"
    included_files = get_included_files_from_json(json_output_str)
    expected_files = {"visible_file.txt"}
    assert included_files == expected_files
    assert ".config_file" not in included_files
    assert ".hidden_subdir/visible_in_hidden.txt" not in included_files
    assert ".hidden_subdir/.another_hidden.dat" not in included_files


@pytest.mark.parametrize("temp_test_dir", ["hidden_files_dir"], indirect=True)
def test_hidden_files_included_with_no_default_ignore(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-012 (Conceptual)
    Description: Verifies hidden files/dirs are included with '--no-default-ignore'.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--no-default-ignore", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                full_output_parts = []
                for call_obj in mock_rich_print.call_args_list:
                    for arg in call_obj.args:
                        full_output_parts.append(str(arg))
                json_output_str = "".join(full_output_parts)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}\nOutput: {result.output}"
    included_files = get_included_files_from_json(json_output_str)

    expected_files = {
        "visible_file.txt",
        ".config_file",
        ".hidden_subdir/visible_in_hidden.txt",
        ".hidden_subdir/.another_hidden.dat",
        ".hidden_subdir/another_hidden.dat",
    }
    assert included_files == expected_files


# --- New tests for max-depth and include/exclude patterns ---


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_max_depth_zero(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-002 (Conceptual)
    Description: Verifies that '--max-depth 0' includes only files in the root directory.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--max-depth", "0", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Output: {result.output}"
    included_files = get_included_files_from_json(json_output_str)
    expected_files_at_depth_0 = {"README.md", "config.yaml"}
    assert included_files == expected_files_at_depth_0


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_max_depth_one(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-003 (Conceptual)
    Description: Verifies that '--max-depth 1' includes files in root and immediate subdirectories.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--max-depth", "1", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Output: {result.output}"
    included_files = get_included_files_from_json(json_output_str)

    expected_files_at_depth_1 = {
        "README.md",
        "config.yaml",
        "src/main.py",
        "src/utils.py",
        "tests/test_main.py",
        "tests/test_utils.py",
        "docs/index.md",
        "docs/api.md",
        "data/small_data.csv",
    }
    assert included_files == expected_files_at_depth_1


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_include_specific_file_type(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-004 (Conceptual)
    Description: Verifies that '--include *.py' includes only Python files.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--include", "*.py", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)
    expected_py_files = {
        "src/main.py",
        "src/utils.py",
        "src/feature/module.py",
        "tests/test_main.py",
        "tests/test_utils.py",
    }
    assert included_files == expected_py_files
    assert "README.md" not in included_files
    assert "config.yaml" not in included_files


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_include_specific_directory(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-005 (Conceptual)
    Description: Verifies '--include src/' includes all processable files within 'src/'
    and its subdirectories. This test passed after the patterns.py fix.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--include", "src/", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)
    expected_src_files = {
        "src/main.py",
        "src/utils.py",
        "src/feature/module.py",
    }
    assert included_files == expected_src_files
    assert "README.md" not in included_files


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_exclude_specific_file_type(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-006 (Conceptual)
    Description: Verifies that '--exclude *.md' excludes all Markdown files.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--exclude", "*.md", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)

    assert "README.md" not in included_files
    assert "docs/index.md" not in included_files
    assert "docs/api.md" not in included_files

    assert "config.yaml" in included_files
    assert "src/main.py" in included_files


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_exclude_specific_directory(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-007 (Conceptual)
    Description: Verifies that '--exclude tests/' excludes all files within 'tests/'.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--exclude", "tests/", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)

    assert "tests/test_main.py" not in included_files
    assert "tests/test_utils.py" not in included_files

    assert "src/main.py" in included_files
    assert "README.md" in included_files


@pytest.mark.parametrize("temp_test_dir", ["complex_project"], indirect=True)
def test_exclude_overrides_include(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-008 (Conceptual)
    Description: Verifies --exclude takes precedence over --include.
    Include '*.md' but exclude 'docs/index.md'.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [
                    ".",
                    "--format",
                    "json",
                    "--include",
                    "*.md",
                    "--exclude",
                    "docs/index.md",
                    "--no-clipboard",
                ],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)

    expected_included_md_files = {"README.md", "docs/api.md"}
    assert included_files == expected_included_md_files
    assert "docs/index.md" not in included_files
    assert "config.yaml" not in included_files


# --- Tests for Symlink Handling ---


@pytest.mark.parametrize("temp_test_dir", ["symlink_dir"], indirect=True)
def test_symlinks_not_followed_by_default(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-013 (Conceptual)
    Description: Verifies symlinks are not followed by default.
    """
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

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)
    expected_files = {"actual_file.txt", "actual_dir/file_in_actual_dir.txt"}
    assert included_files == expected_files
    assert "link_to_file" not in included_files


@pytest.mark.parametrize("temp_test_dir", ["symlink_dir"], indirect=True)
def test_symlinks_followed_with_flag(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: FTF-014 & FTF-015 (Conceptual)
    Description: Verifies symlinks ARE followed with '--follow-symlinks'.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    json_output_str = ""
    try:
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
            result = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--follow-symlinks", "--no-clipboard"],
            )
            if mock_rich_print.call_args_list:
                json_output_str = "".join(str(call.args[0]) for call in mock_rich_print.call_args_list if call.args)
    finally:
        os.chdir(original_cwd)

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    included_files = get_included_files_from_json(json_output_str)
    expected_files = {
        "actual_file.txt",
        "link_to_file",
        "actual_dir/file_in_actual_dir.txt",
        "link_to_dir/file_in_actual_dir.txt",
    }
    assert included_files == expected_files


@pytest.mark.parametrize("temp_test_dir", ["symlink_dir"], indirect=True)
def test_broken_symlinks_handling(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: (Derived for symlink robustness)
    Description: Tests handling of broken symlinks.
    - Default: Broken symlinks should not cause crashes and not be included.
    - Follow + Ignore Errors: Broken symlinks should appear in output with a read_error.
    """
    original_cwd = os.getcwd()
    os.chdir(temp_test_dir)
    try:
        # Case 1: Default (no follow, no ignore errors)
        json_output_str_no_follow = ""
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print_nf:
            result_nf = runner.invoke(dirdigest_cli.main_cli, [".", "--format", "json", "--no-clipboard"])
            if mock_rich_print_nf.call_args_list:
                json_output_str_no_follow = "".join(
                    str(call.args[0]) for call in mock_rich_print_nf.call_args_list if call.args
                )
        assert result_nf.exit_code == 0
        included_nf = get_included_files_from_json(json_output_str_no_follow)
        assert "broken_link" not in included_nf

        # Case 2: Follow symlinks, no ignore errors
        json_output_str_follow = ""
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print_f:
            result_f = runner.invoke(
                dirdigest_cli.main_cli,
                [".", "--format", "json", "--follow-symlinks", "--no-clipboard"],
            )
            if mock_rich_print_f.call_args_list:
                json_output_str_follow = "".join(
                    str(call.args[0]) for call in mock_rich_print_f.call_args_list if call.args
                )
        assert result_f.exit_code == 0
        included_f = get_included_files_from_json(json_output_str_follow)
        assert "broken_link" not in included_f

        # Case 3: Follow symlinks, WITH ignore errors
        json_output_str_follow_ignore = ""
        with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print_fi:
            result_fi = runner.invoke(
                dirdigest_cli.main_cli,
                [
                    ".",
                    "--format",
                    "json",
                    "--follow-symlinks",
                    "--ignore-errors",
                    "--no-clipboard",
                ],
            )
            if mock_rich_print_fi.call_args_list:
                json_output_str_follow_ignore = "".join(
                    str(call.args[0]) for call in mock_rich_print_fi.call_args_list if call.args
                )
        assert result_fi.exit_code == 0

        data_fi = json.loads(json_output_str_follow_ignore)
        processed_broken_link_node = None

        queue_nodes = [data_fi["root"]]
        while queue_nodes:
            current_node = queue_nodes.pop(0)
            if not current_node:
                continue
            if (
                current_node.get("type") == "file"
                and current_node.get("relative_path", "").replace(os.sep, "/") == "broken_link"
            ):
                processed_broken_link_node = current_node
                break
            if "children" in current_node and isinstance(current_node["children"], list):
                for child_node in current_node["children"]:
                    queue_nodes.append(child_node)

        assert processed_broken_link_node is not None, (
            "broken_link node not found in JSON output with --follow-symlinks --ignore-errors"
        )
        assert "read_error" in processed_broken_link_node, "broken_link node should have a 'read_error' attribute"
        assert processed_broken_link_node.get("content") is None, (
            "broken_link node should have no content due to read_error"
        )
    finally:
        os.chdir(original_cwd)
