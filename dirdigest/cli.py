import json as json_debugger  # For debug tree printing
import logging
import pathlib
import time

import click
from rich.markup import escape

from dirdigest import core
from dirdigest import formatter as dirdigest_formatter
from dirdigest.constants import TOOL_NAME, TOOL_VERSION, DEFAULT_SORT_ORDER, SORT_OPTIONS
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
@click.option(
    "--sort-output-log-by",
    multiple=True,
    type=click.Choice(SORT_OPTIONS, case_sensitive=False),
    help=(
        "Sort the output log by one or more keys. Default: 'status', 'size'. "
        "Available options: 'status', 'size', 'path'. "
        "Specify multiple times for multi-key sorting (e.g., --sort-output-log-by status --sort-output-log-by size)."
    ),
)
@click.version_option(
    version=TOOL_VERSION, prog_name=TOOL_NAME, message="%(prog)s version %(version)s"
)
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
    sort_output_log_by: tuple[str, ...],
):
    start_time = time.monotonic()

    cfg_file_values = dirdigest_config.load_config_file(config_path_cli)
    cli_params_for_merge = ctx.params.copy()
    if (
        "directory_arg" in cli_params_for_merge
        and "directory" not in cli_params_for_merge
    ):
        cli_params_for_merge["directory"] = cli_params_for_merge.pop("directory_arg")
    if (
        "config_path_cli" in cli_params_for_merge
        and "config" not in cli_params_for_merge
    ):
        cli_params_for_merge["config"] = cli_params_for_merge.pop("config_path_cli")
    final_settings = dirdigest_config.merge_config(
        cli_params_for_merge, cfg_file_values, ctx
    )

    final_verbose = final_settings.get("verbose", 0)
    final_quiet = final_settings.get("quiet", False)
    final_log_file_val = final_settings.get("log_file")
    if isinstance(final_log_file_val, str):
        final_log_file_val = pathlib.Path(final_log_file_val)

    dirdigest_logger.setup_logging(
        verbose_level=final_verbose, quiet=final_quiet, log_file_path=final_log_file_val
    )
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
            raw_exclude_patterns = [
                p.strip() for p in raw_exclude_patterns.split(",") if p.strip()
            ]
        else:
            raw_exclude_patterns = []

    final_exclude = list(raw_exclude_patterns)

    if final_output_path:
        try:
            output_file_relative_to_base = final_output_path.resolve().relative_to(
                final_directory.resolve()
            )
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

    if not final_sort_output_log_by: # If empty tuple from CLI and not in config
        final_sort_output_log_by = DEFAULT_SORT_ORDER
    # Ensure it's a list for potential modification or consistent use later
    final_sort_output_log_by = list(final_sort_output_log_by)

    log.debug(f"CLI: Final effective settings after merge: {final_settings}")
    log.info(f"CLI: Processing directory: [log.path]{final_directory}[/log.path]")
    if final_output_path:
        log.info(
            f"CLI: Output will be written to: [log.path]{final_output_path}[/log.path]"
        )
    else:
        log.info("CLI: Output will be written to stdout")
    log.info(f"CLI: Format: {final_format.upper()}")
    if final_verbose > 0:
        log.info(f"CLI: Include patterns: {final_include if final_include else 'N/A'}")
        log.info(f"CLI: Exclude patterns: {final_exclude if final_exclude else 'N/A'}")
        log.info(
            f"CLI: Max size: {final_max_size}KB, Max depth: {final_max_depth if final_max_depth is not None else 'unlimited'}"
        )
        log.info(
            f"CLI: Default ignores {'DISABLED' if final_no_default_ignore else 'ENABLED'}"
        )
        log.info(
            f"CLI: Follow symlinks: {final_follow_symlinks}, Ignore errors: {final_ignore_errors}"
        )
        log.info(f"CLI: Clipboard: {final_clipboard}")
        log.info(f"CLI: Sort output log by: {final_sort_output_log_by}")

    processed_items_generator, stats_from_core = core.process_directory_recursive(
        base_dir_path=final_directory,
        include_patterns=final_include,
        exclude_patterns=final_exclude,
        no_default_ignore=final_no_default_ignore,
        max_depth=final_max_depth,
        follow_symlinks=final_follow_symlinks,
        max_size_kb=final_max_size,
        ignore_read_errors=final_ignore_errors,
    )

    all_processed_items = list(processed_items_generator)

    # Prepare sorted list for console logging
    # Note: final_sort_output_log_by is already defined and defaulted earlier
    sorted_items_for_console = core.prepare_output_list(iter(all_processed_items), final_sort_output_log_by)

    # Print Sorted Console Log (if verbosity allows for INFO)
    if log.isEnabledFor(logging.INFO):
        log.info("--- Detailed Processing Log ---")
        previous_item_status = None

        # Determine if a separator is needed for console output
        separator_needed_for_console = False
        if final_sort_output_log_by:
            if final_sort_output_log_by[0] == 'status' or \
               final_sort_output_log_by == ['size'] or \
               final_sort_output_log_by == ['status', 'size']:
                separator_needed_for_console = True

        has_any_excluded = any(item['status'] == 'excluded' for item in sorted_items_for_console)

        for item in sorted_items_for_console:
            status_str = item['status'].capitalize()
            type_str = item['type'].capitalize()
            size_val = item['size_kb']
            # Ensure folders show 0.0KB or as desired, files show their size
            size_display = f"{size_val:.1f}KB" if isinstance(size_val, float) else "N/A"
            if item['type'] == 'folder' and size_val == 0.0 : # Explicitly show 0.0KB for folders
                size_display = "0.0KB"

            path_str = str(item['path'])
            escaped_path_str = escape(path_str)

            reason_raw = item.get('reason_excluded')
            escaped_reason_str = escape(reason_raw) if reason_raw else ""
            reason_part = f" ([log.reason]{escaped_reason_str}[/log.reason])" if reason_raw else ""

            tag_for_status = "log.included" if item['status'] == 'included' else "log.excluded"

            # Consider if type_str needs styling, e.g., [bold]{type_str}[/bold]
            # For now, keeping it simple as per direct instructions.
            log_line = f"[{tag_for_status}]{status_str}[/{tag_for_status}] {type_str} [log.size][Size: {size_display}][/log.size]: [log.path]{escaped_path_str}[/log.path]{reason_part}"

            current_item_status = item['status']
            if separator_needed_for_console and \
               current_item_status == 'included' and \
               previous_item_status == 'excluded' and \
               has_any_excluded: # Only add separator if there were excluded items
                log.info("---")  # Visual separator

            log.info(log_line)
            previous_item_status = current_item_status
        log.info("--- End Detailed Processing Log ---")

    log.info("CLI: Building digest tree...")
    # build_digest_tree now takes all_processed_items and returns only root_node, metadata_for_output
    root_node, metadata_for_output = core.build_digest_tree(
        base_dir_path=final_directory,
        all_processed_items=all_processed_items,
        initial_stats_from_traversal=stats_from_core
    )
    log.debug(
        f"CLI: Digest tree built. Root node children: {len(root_node.get('children', []))}"
    )
    # metadata_for_output no longer contains sorted_log_items or sort_options_used from core.py
    log.debug(f"CLI: Metadata for output from core: {metadata_for_output}")

    # Add sort_options_used to metadata for summary and potentially for formatter if needed by a specific format.
    # However, formatters are now reverted to not use it.
    # This is mainly for the console summary.
    metadata_for_output_with_sort_info = metadata_for_output.copy()
    metadata_for_output_with_sort_info['sort_options_used'] = final_sort_output_log_by


    selected_formatter: dirdigest_formatter.BaseFormatter
    if final_format.lower() == "json":
        selected_formatter = dirdigest_formatter.JsonFormatter(
            base_dir_path=final_directory,
            # Pass the original metadata_for_output without sort info for the digest file itself
            cli_metadata=metadata_for_output
        )
    elif final_format.lower() == "markdown":
        selected_formatter = dirdigest_formatter.MarkdownFormatter(
            base_dir_path=final_directory,
            cli_metadata=metadata_for_output
        )
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
            final_output_path.parent.mkdir(
                parents=True, exist_ok=True
            )  # Ensure dir exists
            with open(final_output_path, "w", encoding="utf-8") as f_out:
                f_out.write(raw_generated_digest)  # Write the original digest to file
            log.info(
                f"CLI: Digest successfully written to [log.path]{final_output_path}[/log.path]"
            )
        else:  # stdout
            # Print the potentially newline-appended version
            dirdigest_logger.stdout_console.print(
                string_for_stdout_or_clipboard_content, end="", markup=False
            )
            # The conditional print for newline is now handled by string_for_stdout_or_clipboard_content construction

        generated_digest_content = (
            raw_generated_digest  # For token counting, use original
        )
        output_generation_succeeded = True

    except Exception as e:
        exc_type_str = escape(type(e).__name__)
        exc_msg_str = escape(str(e))
        log.error(
            f"CLI: Error during output formatting or writing. Type: {exc_type_str}, Message: {exc_msg_str}",
            exc_info=True,
        )
        generated_digest_content = (
            f"Error generating output: {e}"  # For token counting of error
        )
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
            path_str_for_clipboard = str(
                target_dir_to_copy_obj
            )  # This is the Linux/local directory path string

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
                clipboard_log_message = f"CLI: Copied output directory path to clipboard: [log.path]{path_str_for_clipboard}[/log.path]"

            text_to_copy = path_str_for_clipboard

        elif (
            not final_output_path
            and output_generation_succeeded
            and string_for_stdout_or_clipboard_content
        ):
            # Output was to stdout, copy the (potentially newline-adjusted) content
            text_to_copy = string_for_stdout_or_clipboard_content
            clipboard_log_message = (
                "CLI: Copied generated digest (from stdout) to clipboard."
            )

        elif not output_generation_succeeded:
            log.warning(
                "CLI: Output generation failed (see error above), not copying to clipboard."
            )
            # clipboard_log_message remains the default or previous state, not critical here
        else:  # Output succeeded but content was empty (e.g. for stdout) or other edge case
            log.debug(
                "CLI: Clipboard enabled, but output was empty or not suitable for copying (e.g. empty stdout)."
            )
            # clipboard_log_message remains the default or previous state

        # Perform the copy operation
        if text_to_copy:
            # Added explicit debug before copying
            log.debug(
                f"CLI_Clipboard_DEBUG: Attempting to copy. Text: '{text_to_copy}'"
            )
            if dirdigest_clipboard.copy_to_clipboard(text_to_copy):
                # Log the specific message determined above only on successful copy
                if (
                    clipboard_log_message
                    and clipboard_log_message != "CLI: Clipboard processing initiated."
                ):  # Ensure it was updated
                    log.info(clipboard_log_message)
                else:  # Should not happen if text_to_copy was set
                    log.info(
                        "CLI: Content/path copied to clipboard successfully (generic message)."
                    )
            # else: copy_to_clipboard already logs its own failure
        elif final_clipboard and output_generation_succeeded and not text_to_copy:
            # This case handles if output_generation_succeeded but text_to_copy ended up empty
            # (e.g. empty digest from stdout, or if final_output_path was somehow root '/')
            log.debug(
                "CLI: Clipboard copy enabled, but there was nothing to copy (e.g., empty digest or root path)."
            )

    else:  # final_clipboard is False
        log.debug("CLI: Clipboard copy disabled by user.")
    # --- Clipboard --- END ---

    execution_time = time.monotonic() - start_time
    # Use metadata_for_output_with_sort_info for summary logging
    inc_count = metadata_for_output_with_sort_info.get("included_files_count", 0)
    exc_count = metadata_for_output_with_sort_info.get("excluded_items_count", 0)
    total_size = metadata_for_output_with_sort_info.get("total_content_size_kb", 0.0)
    sort_options_display = metadata_for_output_with_sort_info.get("sort_options_used", "N/A")

    approx_tokens = 0
    if (
        output_generation_succeeded and generated_digest_content
    ):  # Use original content for tokens
        approx_tokens = approximate_token_count(generated_digest_content)

    log.info("-" * 30 + " SUMMARY " + "-" * 30)
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
        f"[log.summary_key]Sort options used:[/log.summary_key] [log.summary_value_neutral]{sort_options_display}[/log.summary_value_neutral]"
    )
    log.info(
        f"[log.summary_key]Approx. Token Count:[/log.summary_key] [log.summary_value_neutral]{approx_tokens:,}[/log.summary_value_neutral]"
    )
    log.info(
        f"[log.summary_key]Execution time:[/log.summary_key] [log.summary_value_neutral]{execution_time:.2f} seconds[/log.summary_value_neutral]"
    )
    log.info("-" * (60 + len(" SUMMARY ")))

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
            json_tree_str = json_debugger.dumps(
                root_node, indent=2, default=json_default_serializer
            )
            escaped_json_string = escape(json_tree_str)
            log.debug(escaped_json_string, extra={"markup": False})
        except TypeError as e:
            log.debug(
                f"CLI: Error serializing data tree to JSON for debug: {escape(str(e))}"
            )
        log.debug("CLI: --- End Generated Data Tree ---")


if __name__ == "__main__":
    main_cli()
