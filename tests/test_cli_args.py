from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from dirdigest import cli as dirdigest_cli
from dirdigest.constants import TOOL_NAME, TOOL_VERSION

# --- Existing passing tests ---


def test_cli_help_short_option(runner: CliRunner):
    """
    Test ID: CLI-023 (Conceptual)
    Description: Verifies that the '-h' option displays the help message and exits successfully.
    Checks for basic usage string and presence of a known option in the output.
    """
    result = runner.invoke(dirdigest_cli.main_cli, ["-h"])
    assert result.exit_code == 0
    assert "Usage: dirdigest [OPTIONS] DIRECTORY" in result.output
    assert TOOL_NAME in result.output
    assert "--output" in result.output


def test_cli_help_long_option(runner: CliRunner):
    """
    Test ID: CLI-023 (Conceptual)
    Description: Verifies that the '--help' option displays the help message and exits successfully.
    Checks for basic usage string and presence of a known option in the output.
    """
    result = runner.invoke(dirdigest_cli.main_cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage: dirdigest [OPTIONS] DIRECTORY" in result.output
    assert "--include" in result.output


def test_cli_version_option(runner: CliRunner):
    """
    Test ID: CLI-024 (Conceptual)
    Description: Verifies that the '--version' option displays the tool's name and version, then exits.
    """
    result = runner.invoke(dirdigest_cli.main_cli, ["--version"])
    assert result.exit_code == 0
    expected_output_start = f"{TOOL_NAME} version {TOOL_VERSION}"
    assert result.output.strip().startswith(expected_output_start)


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_basic_invocation_no_args(runner: CliRunner, temp_test_dir):
    """
    Test ID: CLI-001 (Conceptual)
    Description: Tests basic invocation with no arguments in a mock directory.
    Verifies that the tool runs successfully (exit code 0) and produces some expected Markdown output
    by checking for header and known filenames from the 'simple_project' fixture.
    Output is captured by mocking the Rich console's print method.
    """
    with mock.patch("dirdigest.utils.logger.stdout_console.print") as mock_rich_print:
        # Invoke with '-o -' to force output to stdout for this test
        result = runner.invoke(dirdigest_cli.main_cli, ["-o", "-"])

        assert result.exit_code == 0, f"CLI failed with output:\n{result.output}\nStderr:\n{result.stderr}"

        printed_output_segments = []
        for call_args_item in mock_rich_print.call_args_list:
            if call_args_item.args:
                printed_output_segments.append(str(call_args_item.args[0]))
        actual_stdout_content = "".join(printed_output_segments)

        assert actual_stdout_content is not None, "stdout_console.print was not called"
        assert len(actual_stdout_content) > 0, "stdout_console.print was called with empty string or not captured"
        assert "# Directory Digest" in actual_stdout_content
        assert "file1.txt" in actual_stdout_content
        assert "file2.md" in actual_stdout_content  # Based on last passing test run output
        assert "sub_dir1/script.py" in actual_stdout_content


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_non_existent_directory_arg(runner: CliRunner, temp_test_dir):
    """
    Test ID: CLI-021 (Conceptual)
    Description: Verifies that providing a non-existent directory path as the main argument
    results in a non-zero exit code and an appropriate error message from Click.
    """
    result = runner.invoke(dirdigest_cli.main_cli, ["non_existent_dir"])
    assert result.exit_code != 0
    assert "Error" in result.output
    assert "does not exist" in result.output


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_file_as_directory_arg(runner: CliRunner, temp_test_dir):
    """
    Test ID: CLI-022 (Conceptual)
    Description: Verifies that providing an existing file path (instead of a directory)
    as the main argument results in a non-zero exit code and an error message.
    """
    file_path_arg = "file1.txt"
    result = runner.invoke(dirdigest_cli.main_cli, [file_path_arg])
    assert result.exit_code != 0
    assert "Error" in result.output
    assert "is a file" in result.output


# --- New tests for more CLI arguments ---


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_output_option(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: CLI-003 (Conceptual)
    Description: Tests the '--output <filepath>' option.
    Verifies that the command runs successfully and creates the specified output file
    containing expected digest content (e.g., Markdown header and a known filename).
    """
    output_filename = "my_digest.md"
    # temp_test_dir fixture changes CWD, so output_filename is relative to it.
    output_file_path = Path(output_filename)

    result = runner.invoke(dirdigest_cli.main_cli, ["--output", output_filename])

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"
    assert output_file_path.exists(), f"Output file {output_file_path} was not created."
    assert output_file_path.is_file()

    content = output_file_path.read_text()
    assert "# Directory Digest" in content
    assert "file1.txt" in content


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_format_json_option(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: CLI-004 (Conceptual) / JSON-001 (Conceptual)
    Description: Tests the '--format json' option, directing output to a file.
    Verifies successful execution, creation of the JSON output file,
    valid JSON content, and presence of key structures ('metadata', 'root') and expected data.
    """
    output_filename = "digest.json"
    output_file_path = Path(output_filename)

    result = runner.invoke(dirdigest_cli.main_cli, ["--format", "json", "--output", output_filename])
    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"

    assert output_file_path.exists()
    content = output_file_path.read_text()

    import json

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        pytest.fail(f"Output was not valid JSON: {content}")

    assert "metadata" in data
    assert "root" in data
    assert data["metadata"]["tool_version"] == TOOL_VERSION
    # Check for an expected file in the JSON structure's children
    found_file = False
    if "children" in data["root"]:
        for child in data["root"]["children"]:
            if child.get("type") == "file" and child.get("relative_path") == "file1.txt":
                found_file = True
                break
    assert found_file, "Expected file 'file1.txt' not found in JSON root children."


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_invalid_format_option(runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: (Implied by CLI argument validation)
    Description: Tests providing an invalid value (e.g., 'xml') to the '--format' option.
    Verifies that the command fails with a non-zero exit code and Click displays
    an appropriate error message about the invalid choice.
    """
    result = runner.invoke(dirdigest_cli.main_cli, ["--format", "xml"])
    assert result.exit_code != 0
    assert "Error" in result.output
    assert "Invalid value for '--format' / '-f'" in result.output


@mock.patch("dirdigest.core.process_directory_recursive")
@mock.patch("dirdigest.core.build_digest_tree")
@mock.patch("dirdigest.formatter.MarkdownFormatter.format", return_value="Mocked Markdown")
@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_include_option_parsing(
    mock_md_format,
    mock_build_tree,
    mock_process_dir,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """
    Test ID: CLI-005 (Conceptual)
    Description: Verifies that multiple '--include' options are correctly parsed from the CLI
    and passed as a list of patterns to the core processing function.
    Mocks core functions to isolate CLI parsing.
    """
    mock_process_dir.return_value = (iter([]), {})
    mock_build_tree.return_value = ({}, {})

    runner.invoke(dirdigest_cli.main_cli, ["--include", "*.py", "--include", "docs/"])

    mock_process_dir.assert_called_once()
    kwargs = mock_process_dir.call_args.kwargs

    assert "*.py" in kwargs["include_patterns"]
    assert "docs/" in kwargs["include_patterns"]
    assert len(kwargs["include_patterns"]) == 2


@mock.patch("dirdigest.core.process_directory_recursive")
@mock.patch("dirdigest.core.build_digest_tree", return_value=({}, {}))
@mock.patch("dirdigest.formatter.MarkdownFormatter.format", return_value="Mocked Markdown")
@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_exclude_option_parsing_comma_separated(
    mock_md_format,
    mock_build_tree,
    mock_process_dir,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """
    Test ID: CLI-008 (Conceptual)
    Description: Verifies that a comma-separated list provided to '--exclude' option
    is correctly parsed into multiple distinct patterns and passed to the core processing function.
    Mocks core functions.
    """
    mock_process_dir.return_value = (iter([]), {})

    runner.invoke(dirdigest_cli.main_cli, ["--exclude", "*.log,tmp/"])

    mock_process_dir.assert_called_once()
    kwargs = mock_process_dir.call_args.kwargs

    # The default output file is now also excluded.
    # e.g., simple_project-digest.md or similar based on temp_test_dir.name
    # We need to check for the presence of the original patterns and that the count is now 3.
    assert "*.log" in kwargs["exclude_patterns"]
    assert "tmp/" in kwargs["exclude_patterns"]
    # Check that a generated filename like <dirname>-digest.md is also in excludes
    auto_excluded_output_file_found = any(
        f"{temp_test_dir.name}-digest.md" in pattern for pattern in kwargs["exclude_patterns"]
    )
    assert (
        auto_excluded_output_file_found
    ), f"Default output file pattern not found in excludes: {kwargs['exclude_patterns']}"
    assert len(kwargs["exclude_patterns"]) == 3


@mock.patch("dirdigest.core.process_directory_recursive")
@mock.patch("dirdigest.core.build_digest_tree", return_value=({}, {}))
@mock.patch("dirdigest.formatter.MarkdownFormatter.format", return_value="Mocked Markdown")
@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_max_size_option_parsing(
    mock_md_format,
    mock_build_tree,
    mock_process_dir,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """
    Test ID: CLI-010 (Conceptual)
    Description: Verifies that the '--max-size' option (integer value) is correctly parsed
    and passed as 'max_size_kb' to the core processing function. Mocks core functions.
    """
    mock_process_dir.return_value = (iter([]), {})

    runner.invoke(dirdigest_cli.main_cli, ["--max-size", "500"])

    mock_process_dir.assert_called_once()
    kwargs = mock_process_dir.call_args.kwargs
    assert kwargs["max_size_kb"] == 500


@mock.patch("dirdigest.core.process_directory_recursive")
@mock.patch("dirdigest.core.build_digest_tree", return_value=({}, {}))
@mock.patch("dirdigest.formatter.MarkdownFormatter.format", return_value="Mocked Markdown")
@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_max_depth_option_parsing(
    mock_md_format,
    mock_build_tree,
    mock_process_dir,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """
    Test ID: CLI-012 (Conceptual)
    Description: Verifies that the '--max-depth' option (integer value) is correctly parsed
    and passed to the core processing function. Mocks core functions.
    """
    mock_process_dir.return_value = (iter([]), {})

    runner.invoke(dirdigest_cli.main_cli, ["--max-depth", "3"])

    mock_process_dir.assert_called_once()
    kwargs = mock_process_dir.call_args.kwargs
    assert kwargs["max_depth"] == 3


@pytest.mark.parametrize(
    "flag_name, arg_name_in_core, expected_value",
    [
        ("--no-default-ignore", "no_default_ignore", True),  # CLI-013
        ("--follow-symlinks", "follow_symlinks", True),  # CLI-014
        ("--ignore-errors", "ignore_read_errors", True),  # CLI-015
    ],
)
@mock.patch("dirdigest.core.process_directory_recursive")
@mock.patch("dirdigest.core.build_digest_tree", return_value=({}, {}))
@mock.patch("dirdigest.formatter.MarkdownFormatter.format", return_value="Mocked Markdown")
@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_boolean_flags_for_core(
    mock_md_format,
    mock_build_tree,
    mock_process_dir,
    runner: CliRunner,
    temp_test_dir: Path,
    flag_name: str,
    arg_name_in_core: str,
    expected_value: bool,
):
    """
    Test IDs: CLI-013, CLI-014, CLI-015 (Conceptual)
    Description: Tests various boolean flags (e.g., '--no-default-ignore') and verifies
    that they correctly set the corresponding boolean argument in the call
    to the core processing function. Mocks core functions. Parametrized for different flags.
    """
    mock_process_dir.return_value = (iter([]), {})

    runner.invoke(dirdigest_cli.main_cli, [flag_name])

    mock_process_dir.assert_called_once()
    kwargs = mock_process_dir.call_args.kwargs
    assert kwargs.get(arg_name_in_core) == expected_value


@mock.patch("dirdigest.utils.clipboard.pyperclip.copy")  # Mock the actual copy action
@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
def test_cli_no_clipboard_option(mock_pyperclip_copy, runner: CliRunner, temp_test_dir: Path):
    """
    Test ID: CLI-016 (Conceptual)
    Description: Verifies that using the '--no-clipboard' option prevents the
    'pyperclip.copy' function from being called.
    """
    with mock.patch("dirdigest.utils.logger.stdout_console.print"):
        result = runner.invoke(dirdigest_cli.main_cli, ["--no-clipboard"])

    assert result.exit_code == 0
    mock_pyperclip_copy.assert_not_called()


# --- MODIFIED TESTS FOR CLIPBOARD BEHAVIOR ---


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
@mock.patch("dirdigest.cli.is_running_in_wsl", return_value=False)
@mock.patch("dirdigest.utils.clipboard.pyperclip.copy")
def test_cli_clipboard_copies_dir_path_when_output_file_not_in_wsl(
    mock_pyperclip_copy,
    mock_is_wsl,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """Test that the output file's directory path is copied when -o is used and not in WSL."""
    output_filename = "my_digest_output.md"
    output_file_path = Path(output_filename)  # Relative to temp_test_dir (CWD)

    result = runner.invoke(dirdigest_cli.main_cli, ["--output", output_filename, "--clipboard"])
    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"

    expected_dir_path_copied = str(output_file_path.resolve().parent)
    mock_pyperclip_copy.assert_called_once_with(expected_dir_path_copied)


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
@mock.patch("dirdigest.cli.is_running_in_wsl", return_value=True)
@mock.patch("dirdigest.cli.convert_wsl_path_to_windows")
@mock.patch("dirdigest.utils.clipboard.pyperclip.copy")
def test_cli_clipboard_copies_wsl_dir_path_when_output_file_in_wsl(
    mock_pyperclip_copy,
    mock_convert_wsl_path,
    mock_is_wsl,
    runner: CliRunner,
    temp_test_dir: Path,  # This is the CWD for the test
):
    """Test that a WSL-converted directory path is copied when -o is used and in WSL."""
    output_filename = "wsl_output.md"
    # output_file_path is relative to temp_test_dir (which is current CWD for the invoke)
    output_file_path = Path(output_filename)

    # Determine the Linux absolute path of the parent directory
    linux_abs_dir_path = str(output_file_path.resolve().parent)

    # Mock the WSL converted path for this directory
    # Example: if temp_test_dir (linux_abs_dir_path) is /tmp/pytest-of-user/pytest-0/simple_project0
    # then mock_wsl_converted_dir_path could be \\wsl$\Ubuntu\tmp\pytest-of-user\pytest-0\simple_project0
    escaped_path = linux_abs_dir_path.replace("/", "\\\\")
    mock_wsl_converted_dir_path = f"\\\\wsl$\\DistroName{escaped_path}"
    mock_convert_wsl_path.return_value = mock_wsl_converted_dir_path

    result = runner.invoke(dirdigest_cli.main_cli, ["--output", output_filename, "--clipboard"])
    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"

    mock_convert_wsl_path.assert_called_once_with(linux_abs_dir_path)
    mock_pyperclip_copy.assert_called_once_with(mock_wsl_converted_dir_path)


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
@mock.patch("dirdigest.cli.is_running_in_wsl", return_value=True)
@mock.patch("dirdigest.cli.convert_wsl_path_to_windows", return_value=None)
@mock.patch("dirdigest.utils.clipboard.pyperclip.copy")
def test_cli_clipboard_wsl_dir_path_conversion_fails_copies_linux_dir_path(
    mock_pyperclip_copy,
    mock_convert_wsl_path_fails,
    mock_is_wsl,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """Test that Linux directory path is copied if WSL path conversion fails."""
    output_filename = "wsl_fail_output.md"
    output_file_path = Path(output_filename)

    result = runner.invoke(dirdigest_cli.main_cli, ["--output", output_filename, "--clipboard"])
    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"

    expected_linux_abs_dir_path_copied = str(output_file_path.resolve().parent)
    mock_pyperclip_copy.assert_called_once_with(expected_linux_abs_dir_path_copied)


@pytest.mark.parametrize("temp_test_dir", ["simple_project"], indirect=True)
@mock.patch("dirdigest.utils.clipboard.pyperclip.copy")
def test_cli_clipboard_copies_content_when_no_output_file(
    mock_pyperclip_copy,
    runner: CliRunner,
    temp_test_dir: Path,
):
    """Test that digest content is copied when no -o option is used."""
    captured_stdout_content = ""

    def capture_print_arg(text, **kwargs):
        nonlocal captured_stdout_content
        # Simulating `print(text, end="")` as done in cli.py for stdout
        if "end" not in kwargs or kwargs["end"] == "":
            captured_stdout_content += text
        else:  # if end has some other value, append text and that end value.
            captured_stdout_content += text + kwargs["end"]

    with mock.patch("dirdigest.utils.logger.stdout_console.print", side_effect=capture_print_arg):
        result = runner.invoke(dirdigest_cli.main_cli, ["--clipboard"])

    assert result.exit_code == 0, f"CLI failed. Stderr: {result.stderr}"

    mock_pyperclip_copy.assert_called_once()
    copied_text = mock_pyperclip_copy.call_args[0][0]

    # With default output to file, the clipboard should get the directory path of the output file.
    # The output file will be in the temp_test_dir, named like <temp_test_dir_name>-digest.md
    # So, the copied path should be the path to temp_test_dir.
    # If running in WSL, it will be the WSL-converted path.
    expected_copied_path_str = str(temp_test_dir.resolve())
    if dirdigest_cli.is_running_in_wsl():
        converted_path = dirdigest_cli.convert_wsl_path_to_windows(expected_copied_path_str)
        if converted_path:  # Conversion might fail if wslpath is not available or path is unusual
            expected_copied_path_str = converted_path

    assert (
        copied_text == expected_copied_path_str
    ), f"Expected clipboard to contain dir path '{expected_copied_path_str}', but got '{copied_text}'"

    # To test content copying, a separate test with "-o -" would be needed.
    # This test now verifies the default behavior (output to file, dir path to clipboard).
