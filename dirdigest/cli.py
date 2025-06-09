import functools  # Added for cmp_to_key
import json as json_debugger  # For debug tree printing
import logging
import pathlib
import sys # Required for sys.argv access
import time
from enum import Enum, auto
from typing import List, Tuple  # Added for type hints

import click
from rich.markup import escape

from dirdigest import core
from dirdigest import formatter as dirdigest_formatter
# Import OperationalMode from constants where it's now defined
from dirdigest.constants import TOOL_NAME, TOOL_VERSION, OperationalMode
from dirdigest.core import LogEvent  # Added LogEvent for type hinting
from dirdigest.formatter import format_log_event_for_cli  # Added log event formatter
from dirdigest.utils import clipboard as dirdigest_clipboard
from dirdigest.utils import config as dirdigest_config
from dirdigest.utils import logger as dirdigest_logger
from dirdigest.utils.system import (  # MODIFIED: Import system utils
    convert_wsl_path_to_windows,
    is_running_in_wsl,
)
from dirdigest.utils.tokens import approximate_token_count


@click.command(
    name=TOOL_NAME,
    context_settings=dict(help_option_names=["-h", "--help"]),
    help="Recursively processes directories and files, creating a structured digest suitable for LLM context ingestion.",
)
@click.version_option(version=TOOL_VERSION, prog_name=TOOL_NAME, message="%(prog)s version %(version)s")
@click.pass_context
@click.argument(
    "directory_arg",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        path_type=pathlib.Path,
    ),
    default=".",
    required=False,
    metavar="DIRECTORY",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=pathlib.Path),
    default=None,
    help="Path to the output file. If omitted, the digest is written to standard output (stdout).",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "markdown"], case_sensitive=False),
    default="markdown",
    show_default=True,
    help="Output format for the digest. Choices: 'json', 'markdown'.",
)
@click.option(
    "--include",
    "-i",
    multiple=True,
    help=(
        "Glob pattern(s) for files/directories to INCLUDE. If specified, only items matching these "
        "patterns are processed. Can be used multiple times or comma-separated "
        "(e.g., -i '*.py' -i 'src/' or -i '*.py,src/'). Exclusions are applied first."
    ),
)
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "Glob pattern(s) for files/directories to EXCLUDE. Takes precedence over include patterns. "
        "Can be used multiple times or comma-separated (e.g., -x '*.log' -x 'tests/' or "
        "-x '*.log,tests/'). Default ignores also apply unless --no-default-ignore is set."
    ),
)
@click.option(
    "--max-size",
    "-s",
    type=click.IntRange(min=0),
    default=300,
    show_default=True,
    help="Maximum size (in KB) for individual files to be included. Larger files are excluded.",
)
@click.option(
    "--max-depth",
    "-d",
    type=click.IntRange(min=0),
    default=None,
    show_default="unlimited",
    help="Maximum depth of directories to traverse. Depth 0 processes only the starting directory's files. Unlimited by default.",
)
@click.option(
    "--no-default-ignore",
    is_flag=True,
    show_default=True,  # Default is False
    help=(
        "Disable all default ignore patterns (e.g., .git, __pycache__, node_modules, common "
        "binary/media files, hidden items). Use if you need to include items normally ignored by default."
    ),
)
@click.option(
    "--follow-symlinks",
    is_flag=True,
    show_default=True,  # Default is False
    help="Follow symbolic links to directories and files. By default, symlinks themselves are noted but not traversed/read.",
)
@click.option(
    "--ignore-errors",
    is_flag=True,
    show_default=True,  # Default is False
    help=(
        "Continue processing if an error occurs while reading a file (e.g., permission denied, "
        "decoding error). The file's content will be omitted or noted as an error in the digest."
    ),
)
@click.option(
    "--clipboard/--no-clipboard",
    "-c",
    default=True,
    show_default=True,
    help="Copy the generated digest (or output file path if -o is used) to the system clipboard. Use --no-clipboard to disable.",
)
@click.option(
    "--verbose",
    "-v",
    count=True,
    help="Increase verbosity. -v for INFO, -vv for DEBUG console output.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress all console output below ERROR level. Overrides -v.",
)
@click.option(
    "--log-file",
    type=click.Path(dir_okay=False, writable=True, path_type=pathlib.Path),
    default=None,
    help="Path to a file for detailed logging. All logs (including DEBUG level) will be written here, regardless of console verbosity.",
)
@click.option(
    "--config",
    "config_path_cli",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=pathlib.Path),
    default=None,
    help=(
        f"Specify configuration file path. If omitted, tries to load "
        f"./{dirdigest_config.DEFAULT_CONFIG_FILENAME} from the current directory."
    ),
)
@click.option(
    "--sort-output-log-by",
    multiple=True,
    type=click.Choice(["status", "size", "path"]),
    default=None,  # Handled explicitly later if None or empty
    help="Sort the detailed item-by-item log output. Specify keys in order. 'status': excluded then included. 'size': largest first. 'path': alphabetically. Default: status, size. Allowed multiple times e.g. --sort-output-log-by status --sort-output-log-by size.",
)

# OperationalMode is now imported from dirdigest.constants

# Helper function for sorting log events (moved before main_cli)
def _sort_log_events(log_events: List[LogEvent], sort_keys: List[str]) -> List[LogEvent]:
    """Sorts log events based on a list of sort keys."""

    if not log_events:
        return []

    # Default sort: status (excluded then included), then folders by path, then files by size (desc) then path
    if sort_keys == ["status", "size"]:  # This is our special default case

        def compare_default(item1: LogEvent, item2: LogEvent) -> int:
            # 1. Status: 'excluded' < 'included' < 'error' (errors might appear last or first based on preference)
            # Let's make 'excluded' first, then 'included', then 'error'
            status_order = {
                "excluded": 0,
                "included": 1,
                "error": 2,
                "unknown": 3,
            }  # unknown just in case
            s1 = status_order.get(item1.get("status", "unknown"), 3)
            s2 = status_order.get(item2.get("status", "unknown"), 3)
            if s1 != s2:
                return s1 - s2

            # 2. Item Type (within same status): 'folder' < 'file'
            type_order = {"folder": 0, "file": 1}
            t1 = type_order.get(item1.get("item_type", "file"), 1)
            t2 = type_order.get(item2.get("item_type", "file"), 1)
            if t1 != t2:
                return t1 - t2

            # 3. Sorting based on item type
            path1 = item1.get("path", "")
            path2 = item2.get("path", "")

            if item1.get("item_type") == "folder":  # Both are folders
                return (path1 > path2) - (path1 < path2)  # Alphabetical A-Z
            else:  # Both are files
                size1 = item1.get("size_kb", 0.0)
                size2 = item2.get("size_kb", 0.0)
                if size1 != size2:
                    return (size2 > size1) - (size2 < size1)  # Descending size
                return (path1 > path2) - (path1 < path2)  # Alphabetical A-Z for ties

        return sorted(log_events, key=functools.cmp_to_key(compare_default))

    # General case: apply sort keys in order
    mutable_log_events = list(log_events)

    for key_idx in range(len(sort_keys) - 1, -1, -1):
        sort_key = sort_keys[key_idx]

        if sort_key == "status":
            mutable_log_events.sort(
                key=lambda x: ({"excluded": 0, "included": 1, "error": 2}.get(x.get("status", "unknown"), 3))
            )
        elif sort_key == "size":
            mutable_log_events.sort(key=lambda x: x.get("size_kb", 0.0), reverse=True)
        elif sort_key == "path":
            mutable_log_events.sort(key=lambda x: x.get("path", ""))

    return mutable_log_events

def main_cli(
    ctx: click.Context,
    directory_arg: pathlib.Path,
    output: pathlib.Path | None,
    format: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    max_size: int,
    max_depth: int | None,
    no_default_ignore: bool,
    follow_symlinks: bool,
    ignore_errors: bool,
    clipboard: bool,
    verbose: int,
    quiet: bool,
    log_file: pathlib.Path | None,
    config_path_cli: pathlib.Path | None,
    sort_output_log_by: Tuple[str, ...],  # Added new sort parameter
):
    start_time = time.monotonic()

    cfg_file_values = dirdigest_config.load_config_file(config_path_cli)
    cli_params_for_merge = ctx.params.copy()
    if "directory_arg" in cli_params_for_merge and "directory" not in cli_params_for_merge:
        cli_params_for_merge["directory"] = cli_params_for_merge.pop("directory_arg")
    if "config_path_cli" in cli_params_for_merge and "config" not in cli_params_for_merge:
        cli_params_for_merge["config"] = cli_params_for_merge.pop("config_path_cli")
    final_settings = dirdigest_config.merge_config(cli_params_for_merge, cfg_file_values, ctx)

    final_verbose = final_settings.get("verbose", 0)
    final_quiet = final_settings.get("quiet", False)
    final_log_file_val = final_settings.get("log_file")
    if isinstance(final_log_file_val, str):
        final_log_file_val = pathlib.Path(final_log_file_val)

    dirdigest_logger.setup_logging(verbose_level=final_verbose, quiet=final_quiet, log_file_path=final_log_file_val)
    log = dirdigest_logger.logger  # Use the globally configured logger

    final_directory = final_settings.get("directory", directory_arg)
    if isinstance(final_directory, str):
        final_directory = pathlib.Path(final_directory)
        if not final_directory.exists() or not final_directory.is_dir():
            log.error(
                f"Directory '{final_directory}' from config does not exist or is not a directory. Using CLI/default: '{directory_arg}'"
            )
            final_directory = directory_arg

    final_output_path = final_settings.get("output", output)
    if isinstance(final_output_path, str):
        final_output_path = pathlib.Path(final_output_path)

    final_format = final_settings.get("format", format)
    final_include = final_settings.get("include", include if include else [])

    raw_exclude_patterns = final_settings.get("exclude", exclude if exclude else [])
    if not isinstance(raw_exclude_patterns, list):
        if isinstance(raw_exclude_patterns, tuple):
            raw_exclude_patterns = list(raw_exclude_patterns)
        elif isinstance(raw_exclude_patterns, str):
            raw_exclude_patterns = [p.strip() for p in raw_exclude_patterns.split(",") if p.strip()]
        else:
            raw_exclude_patterns = []

    final_exclude = list(raw_exclude_patterns)

    if final_output_path:
        try:
            output_file_relative_to_base = final_output_path.resolve().relative_to(final_directory.resolve())
            final_exclude.append(str(output_file_relative_to_base))
            log.info(
                f"CLI: Automatically excluding output file from processing: [log.path]{output_file_relative_to_base}[/log.path]"
            )
        except ValueError:
            log.debug(
                f"CLI: Output file [log.path]{final_output_path.resolve()}[/log.path] is not inside the target directory "
                f"[log.path]{final_directory.resolve()}[/log.path]. Not adding to relative excludes for scan."
            )

    final_max_size = final_settings.get("max_size", max_size)
    final_max_depth = final_settings.get("max_depth", max_depth)
    final_no_default_ignore = final_settings.get("no_default_ignore", no_default_ignore)
    final_follow_symlinks = final_settings.get("follow_symlinks", follow_symlinks)
    final_ignore_errors = final_settings.get("ignore_errors", ignore_errors)
    final_clipboard = final_settings.get("clipboard", clipboard)
    final_sort_output_log_by = final_settings.get("sort_output_log_by", sort_output_log_by)

    # Handle default sort keys
    if not final_sort_output_log_by:  # Empty tuple or None
        effective_sort_keys = ["status", "size"]
    else:
        effective_sort_keys = list(final_sort_output_log_by)

    log.debug(f"CLI: Final effective settings after merge: {final_settings}")
    log.info(f"CLI: Processing directory: [log.path]{final_directory}[/log.path]")
    if final_output_path:
        log.info(f"CLI: Output will be written to: [log.path]{final_output_path}[/log.path]")
    else:
        log.info("CLI: Output will be written to stdout")
    log.info(f"CLI: Format: {final_format.upper()}")
    log.info(f"CLI: Sorting item log by: {effective_sort_keys}")  # Log effective sort keys

    if final_verbose > 0:  # Keep existing detailed logging for other params
        log.info(f"CLI: Include patterns: {final_include if final_include else 'N/A'}")
        log.info(f"CLI: Exclude patterns: {final_exclude if final_exclude else 'N/A'}")
        log.info(
            f"CLI: Max size: {final_max_size}KB, Max depth: {final_max_depth if final_max_depth is not None else 'unlimited'}"
        )
        log.info(f"CLI: Default ignores {'DISABLED' if final_no_default_ignore else 'ENABLED'}")
        log.info(f"CLI: Follow symlinks: {final_follow_symlinks}, Ignore errors: {final_ignore_errors}")
        log.info(f"CLI: Clipboard: {final_clipboard}")

    # Determine Operational Mode based on sys.argv and final include/exclude lists
    first_i_idx = float('inf')
    first_x_idx = float('inf')

    # Find the first occurrence of -i/--include and -x/--exclude in sys.argv
    for idx, arg in enumerate(sys.argv):
        if arg == "-i" or arg == "--include":
            if idx < first_i_idx:
                first_i_idx = idx
        elif arg == "-x" or arg == "--exclude":
            if idx < first_x_idx:
                first_x_idx = idx

    operational_mode: OperationalMode

    # Use `final_include` (which is already resolved from CLI + Config)
    # Use `raw_exclude_patterns` for excludes, as this is before auto-adding output file path.
    has_final_includes = bool(final_include)
    has_user_excludes = bool(raw_exclude_patterns) # raw_exclude_patterns = final_settings.get("exclude", exclude if exclude else [])

    if not has_final_includes and not has_user_excludes:
        operational_mode = OperationalMode.MODE_INCLUDE_ALL_DEFAULT
    elif has_final_includes and not has_user_excludes:
        operational_mode = OperationalMode.MODE_ONLY_INCLUDE
    elif not has_final_includes and has_user_excludes:
        operational_mode = OperationalMode.MODE_ONLY_EXCLUDE
    else:  # Both include and user-specified exclude patterns are present
        if first_i_idx < first_x_idx:
            operational_mode = OperationalMode.MODE_INCLUDE_FIRST
        elif first_x_idx < first_i_idx:
            operational_mode = OperationalMode.MODE_EXCLUDE_FIRST
        else:
            # This means both include and exclude patterns are present,
            # but their relative order couldn't be determined from CLI flags
            # (e.g., all from config, or one from CLI and other from config in a way that doesn't set both idx).
            # Defaulting to EXCLUDE_FIRST for such ambiguous mixed cases.
            log.debug(
                "CLI: Both include and exclude patterns present, but order via CLI flags is ambiguous "
                "(e.g., patterns from config or mixed sources). Defaulting to EXCLUDE_FIRST behavior."
            )
            operational_mode = OperationalMode.MODE_EXCLUDE_FIRST

    log.info(f"CLI: Operational mode determined: {operational_mode.name}")

    # Pass operational_mode to core.process_directory_recursive
    processed_items_generator, stats_from_core, log_events_from_core = core.process_directory_recursive(
        base_dir_path=final_directory,
        operational_mode=operational_mode,
        include_patterns=final_include,
        user_exclude_patterns=raw_exclude_patterns, # For MSE determination (user-defined rules)
        effective_app_exclude_patterns=final_exclude, # For actual exclusion (includes auto output file)
        no_default_ignore=final_no_default_ignore,
        max_depth=final_max_depth,
        follow_symlinks=final_follow_symlinks,
        max_size_kb=final_max_size,
        ignore_read_errors=final_ignore_errors,
    )

    # Consume the generator to a list. This will populate log_events_from_core.
    processed_items_list = list(processed_items_generator)

    # --- Process and print log events ---
    if log_events_from_core:
        log.debug(f"CLI: Received {len(log_events_from_core)} log events from core.")
        sorted_log_events = _sort_log_events(log_events_from_core, effective_sort_keys)
        log.debug(f"CLI: Sorted {len(sorted_log_events)} log events.")

        # Print headers and log items
        # These logs should go through the main logger to respect quiet/verbose and log file settings
        # format_log_event_for_cli produces Rich-formatted strings, which logger handles.
        printed_excluded_header = False
        printed_included_header = False
        for event in sorted_log_events:
            formatted_event_str = format_log_event_for_cli(event)
            if effective_sort_keys != ["path"]:
                if event.get("status") == "excluded" and not printed_excluded_header:
                    # Use log.info for these headers so they go to log file and respect verbosity
                    log.info(
                        "\n\n[bold red]========================== EXCLUDED ITEMS ==========================[/bold red]\n\n"
                    )
                    printed_excluded_header = True
                elif event.get("status") == "included" and not printed_included_header:
                    log.info(
                        "\n\n[bold green]========================== INCLUDED ITEMS ==========================[/bold green]\n\n"
                    )
                    printed_included_header = True
            log.info(formatted_event_str)  # Each event is logged as INFO
    else:
        log.debug("CLI: No log events received from core.")
    # --- End Process and print log events ---

    log.info("\n\nCLI: Building digest tree...")  # This message now appears after individual logs
    root_node, metadata_for_output = core.build_digest_tree(
        final_directory, iter(processed_items_list), stats_from_core
    )
    log.debug(f"CLI: Digest tree built. Root node children: {len(root_node.get('children', []))}")
    log.debug(f"CLI: Metadata for output: {metadata_for_output}")

    selected_formatter: dirdigest_formatter.BaseFormatter
    if final_format.lower() == "json":
        selected_formatter = dirdigest_formatter.JsonFormatter(final_directory, metadata_for_output)
    elif final_format.lower() == "markdown":
        selected_formatter = dirdigest_formatter.MarkdownFormatter(final_directory, metadata_for_output)
    else:
        log.critical(f"CLI: Invalid format '{final_format}' encountered. Exiting.")
        ctx.exit(1)
        return

    log.info(f"CLI: Formatting output as {final_format.upper()}...")

    generated_digest_content = ""
    output_generation_succeeded = False

    # MODIFIED: Prepare string for stdout/clipboard (handles newline for stdout)
    raw_generated_digest = selected_formatter.format(root_node)

    # This string is for stdout printing and for clipboard if outputting to stdout
    string_for_stdout_or_clipboard_content = raw_generated_digest
    if not final_output_path:  # If outputting to stdout
        if not raw_generated_digest.endswith("\n") and raw_generated_digest:
            string_for_stdout_or_clipboard_content = raw_generated_digest + "\n"

    try:
        if final_output_path:
            final_output_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure dir exists
            with open(final_output_path, "w", encoding="utf-8") as f_out:
                f_out.write(raw_generated_digest)  # Write the original digest to file
            log.info(f"CLI: Digest successfully written to [log.path]{final_output_path}[/log.path]")
        else:  # stdout
            # Print the potentially newline-appended version
            dirdigest_logger.stdout_console.print(string_for_stdout_or_clipboard_content, end="", markup=False)
            # The conditional print for newline is now handled by string_for_stdout_or_clipboard_content construction

        generated_digest_content = raw_generated_digest  # For token counting, use original
        output_generation_succeeded = True

    except Exception as e:
        exc_type_str = escape(type(e).__name__)
        exc_msg_str = escape(str(e))
        log.error(
            f"CLI: Error during output formatting or writing. Type: {exc_type_str}, Message: {exc_msg_str}",
            exc_info=True,
        )
        generated_digest_content = f"Error generating output: {e}"  # For token counting of error
        output_generation_succeeded = False

    # --- Clipboard ---
    if final_clipboard:
        text_to_copy = ""
        # Initialize clipboard_log_message for clarity, will be overwritten
        clipboard_log_message = "CLI: Clipboard processing initiated."

        if final_output_path and output_generation_succeeded:
            # Path to be copied is the DIRECTORY containing the output file.
            abs_output_file_path = final_output_path.resolve()
            target_dir_to_copy_obj = abs_output_file_path.parent
            path_str_for_clipboard = str(target_dir_to_copy_obj)  # This is the Linux/local directory path string

            if is_running_in_wsl():
                log.debug(
                    f"CLI: Detected WSL environment. Attempting conversion for directory path: {path_str_for_clipboard}"
                )
                # Pass the Linux/local DIRECTORY path for conversion
                windows_dir_path = convert_wsl_path_to_windows(path_str_for_clipboard)
                if windows_dir_path:
                    path_str_for_clipboard = windows_dir_path  # Update to the converted Windows directory path
                    clipboard_log_message = f"CLI: Copied WSL-converted output directory path to clipboard: [log.path]{path_str_for_clipboard}[/log.path]"
                else:
                    # Conversion failed, path_str_for_clipboard remains the Linux/local directory path
                    log.warning(
                        f"CLI: Failed to convert WSL path for output directory '{target_dir_to_copy_obj}'. Copying original directory path instead."
                    )
                    clipboard_log_message = f"CLI: Copied output directory path (original, WSL conversion failed) to clipboard: [log.path]{path_str_for_clipboard}[/log.path]"
            else:  # Not in WSL
                # path_str_for_clipboard is already the Linux/local directory path
                clipboard_log_message = (
                    f"CLI: Copied output directory path to clipboard: [log.path]{path_str_for_clipboard}[/log.path]"
                )

            text_to_copy = path_str_for_clipboard

        elif not final_output_path and output_generation_succeeded and string_for_stdout_or_clipboard_content:
            # Output was to stdout, copy the (potentially newline-adjusted) content
            text_to_copy = string_for_stdout_or_clipboard_content
            clipboard_log_message = "CLI: Copied generated digest (from stdout) to clipboard."

        elif not output_generation_succeeded:
            log.warning("CLI: Output generation failed (see error above), not copying to clipboard.")
            # clipboard_log_message remains the default or previous state, not critical here
        else:  # Output succeeded but content was empty (e.g. for stdout) or other edge case
            log.debug("CLI: Clipboard enabled, but output was empty or not suitable for copying (e.g. empty stdout).")
            # clipboard_log_message remains the default or previous state

        # Perform the copy operation
        if text_to_copy:
            # Added explicit debug before copying
            log.debug(f"CLI_Clipboard_DEBUG: Attempting to copy. Text: '{text_to_copy}'")
            if dirdigest_clipboard.copy_to_clipboard(text_to_copy):
                # Log the specific message determined above only on successful copy
                if (
                    clipboard_log_message and clipboard_log_message != "CLI: Clipboard processing initiated."
                ):  # Ensure it was updated
                    log.info(clipboard_log_message)
                else:  # Should not happen if text_to_copy was set
                    log.info("CLI: Content/path copied to clipboard successfully (generic message).")
            # else: copy_to_clipboard already logs its own failure
        elif final_clipboard and output_generation_succeeded and not text_to_copy:
            # This case handles if output_generation_succeeded but text_to_copy ended up empty
            # (e.g. empty digest from stdout, or if final_output_path was somehow root '/')
            log.debug("CLI: Clipboard copy enabled, but there was nothing to copy (e.g., empty digest or root path).")

    else:  # final_clipboard is False
        log.debug("CLI: Clipboard copy disabled by user.")
    # --- Clipboard --- END ---

    execution_time = time.monotonic() - start_time
    inc_count = metadata_for_output.get("included_files_count", 0)
    exc_count = metadata_for_output.get("excluded_items_count", 0)  # This key is now consistent from core.py
    total_size = metadata_for_output.get("total_content_size_kb", 0.0)

    approx_tokens = 0
    if output_generation_succeeded and generated_digest_content:  # Use original content for tokens
        approx_tokens = approximate_token_count(generated_digest_content)

    log.info("\n\n[bold blue]============================== SUMMARY ============================== [/bold blue]\n\n")
    log.info(
        f"[log.summary_key]Total files included:[/log.summary_key] [log.summary_value_inc]{inc_count}[/log.summary_value_inc]"
    )
    log.info(
        f"[log.summary_key]Total items excluded (files/dirs):[/log.summary_key] [log.summary_value_exc]{exc_count}[/log.summary_value_exc]"
    )
    log.info(
        f"[log.summary_key]Total content size:[/log.summary_key] [log.summary_value_neutral]{total_size:.2f} KB[/log.summary_value_neutral]"
    )
    log.info(
        f"[log.summary_key]Approx. Token Count:[/log.summary_key] [log.summary_value_neutral]{approx_tokens:,}[/log.summary_value_neutral]"
    )
    log.info(
        f"[log.summary_key]Execution time:[/log.summary_key] [log.summary_value_neutral]{execution_time:.2f} seconds[/log.summary_value_neutral]"
    )
    log.info("\n" + "=" * (60 + len(" SUMMARY ")))

    will_log_debug_tree = False
    if log.isEnabledFor(logging.DEBUG):
        for handler in log.handlers:
            if handler.level <= logging.DEBUG:
                will_log_debug_tree = True
                break

    if will_log_debug_tree:

        def json_default_serializer(obj):
            if isinstance(obj, pathlib.Path):
                return str(obj)
            return f"<not serializable: {type(obj).__name__}>"

        log.debug("CLI: --- Generated Data Tree (Debug from CLI) ---")
        try:
            json_tree_str = json_debugger.dumps(root_node, indent=2, default=json_default_serializer)
            escaped_json_string = escape(json_tree_str)
            log.debug(escaped_json_string, extra={"markup": False})
        except TypeError as e:
            log.debug(f"CLI: Error serializing data tree to JSON for debug: {escape(str(e))}")
        log.debug("CLI: --- End Generated Data Tree ---")
