# dirdigest/dirdigest/formatter.py
import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List # Standard library imports

from dirdigest.constants import TOOL_VERSION, LogEvent, PathState  # Import LogEvent TypedDict and PathState
from dirdigest.core import DigestItemNode # Core data structures
from rich.markup import escape # For escaping patterns in log messages


# Define a common structure for metadata earlier if not already defined elsewhere
Metadata = Dict[str, Any] # Kept as Dict[str, Any] for broader compatibility here


# Regex to strip Rich console tags for length calculation
# This removes tags like "[log.status]" or "[/log.status]"
RICH_TAG_RE = re.compile(r"\[/?log\.[^\]]+\]")

# Define the target column for the colon to align
TARGET_COL = 53  # Choose a column wide enough to accommodate most log event descriptions


def format_log_event_for_cli(log_event: LogEvent) -> str:
    """
    Formats a single log event dictionary into a string for CLI display,
    with alignment based on the colon.
    """
    # path, item_type, status (overall included/excluded), size_kb are existing
    path = log_event.get("path", "")
    item_type = log_event.get("item_type", "item")
    status_summary = log_event.get("status", "unknown") # "included" or "excluded"

    # New fields from PathState logic
    state_name = log_event.get("state", PathState.PENDING_EVALUATION.name) # Get string name
    decision_reason = log_event.get("reason", "") # This is the detailed decision_reason
    msi_pattern = log_event.get("msi")
    mse_pattern = log_event.get("mse")
    default_rule_pattern = log_event.get("default_rule")

    size_kb = log_event.get("size_kb", 0.0)

    # Determine display status and symbol based on the summary status
    # (which should be derived from the final PathState in core.py)
    if status_summary == "included":
        status_symbol = "[bold green]✔[/bold green]"
        status_color_tag = "log.included"
        display_status_text = "Included"
    elif status_summary == "excluded":
        status_symbol = "[bold red]✘[/bold red]"
        status_color_tag = "log.excluded"
        display_status_text = "Excluded"
    else: # error, unknown, etc.
        status_symbol = "[bold yellow]![/bold yellow]"
        status_color_tag = "log.warning" # Or a new tag for unknown/error
        display_status_text = status_summary.capitalize()

    # Determine prefix for item_type based on its value
    item_type_prefix = "  " if item_type == "file" else ""

    # Prepare size string, formatted to two decimal places
    try:
        formatted_size = f"{float(size_kb):.2f}" if size_kb is not None else "N/A"
    except (ValueError, TypeError):
        formatted_size = "N/A"

    # Construct the size part to be inserted
    size_part = f" ([grey39]{formatted_size}KB[/grey39])" if status_summary == "included" or size_kb > 0 else ""


    # Construct the left part of the message (before the colon), including Rich tags
    # Example: [green]✔ Included file (12.34KB)[/green]
    left_part_with_markup = (
        f"[{status_color_tag}]{status_symbol} {display_status_text} {item_type_prefix}{item_type}{size_part}[/{status_color_tag}]"
    )

    # Calculate the visible length of the left part by stripping Rich tags
    visible_left_part_content = RICH_TAG_RE.sub("", left_part_with_markup)
    current_length = len(visible_left_part_content)

    # Calculate padding needed to align the colon
    padding = ""
    if current_length < TARGET_COL:
        padding_length = TARGET_COL - current_length
        padding = " " * padding_length

    # Main message part, now including padding before the colon
    message = f"{left_part_with_markup}{padding}: [log.path]{path}[/log.path]"

    # Detailed explanation part
    details_parts = []
    details_parts.append(f"State: {state_name}")
    if decision_reason: # decision_reason is the primary explanation from core logic
        details_parts.append(f"Reason: {decision_reason}")

    if msi_pattern:
        details_parts.append(f"MSI: '{escape(msi_pattern)}'")
    if mse_pattern:
        details_parts.append(f"MSE: '{escape(mse_pattern)}'")
    if default_rule_pattern:
        details_parts.append(f"DefaultRule: '{escape(default_rule_pattern)}'")

    if details_parts:
        message += f" ([log.details]{', '.join(details_parts)}[/log.details])"

    return message


class BaseFormatter:
    """Base class for output formatters."""

    def __init__(self, base_dir_path: Path, cli_metadata: Metadata):
        """
        Initialize the formatter.
        cli_metadata contains stats collected by core.build_digest_tree
        """
        self.base_dir_path = base_dir_path
        self.core_metadata = cli_metadata  # Metadata from build_digest_tree
        self.final_metadata: Metadata = self._prepare_final_metadata()

    def _prepare_final_metadata(self) -> Metadata:
        """Prepares the full metadata object for the output."""
        # Start with metadata from core (counts, sizes)
        meta = dict(self.core_metadata)  # Make a copy
        meta["tool_version"] = TOOL_VERSION
        meta["created_at"] = datetime.datetime.now().isoformat()
        # base_directory is already in core_metadata
        return meta

    def format(self, data_tree: DigestItemNode) -> str:
        """
        Formats the data_tree into a string representation.
        data_tree is the root node from core.build_digest_tree.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def _get_file_extension(self, file_path: str) -> str:
        """Helper to get file extension for language hints."""
        return Path(file_path).suffix.lstrip(".").lower()

    def _generate_directory_structure_string(
        self, node: DigestItemNode, indent: str = ""
    ) -> List[str]:  # Removed base_path_len as it's not used
        """
        Helper to generate a text-based directory tree for Markdown.
        Adjusted to handle the structure from build_digest_tree.
        """
        lines = []
        node_display_name = Path(node["relative_path"]).name if node["relative_path"] != "." else "."

        # For the root, we don't add it with indent/prefix here, it's handled by the caller or initial line.
        # This function is more for rendering children of a node.
        # However, the current MarkdownFormatter calls it with the root node.
        # Let's adjust: if it's the root, just print its name.
        if indent == "" and node_display_name == ".":  # Special handling for the first call with root
            lines.append(node_display_name)
        # else: # This would be for rendering a node that's already prefixed by its parent
        #     lines.append(f"{indent}{node_display_name}") # This line is redundant if called as designed below

        if node["type"] == "folder" and "children" in node and node["children"]:
            children_sorted = node["children"]  # Already sorted by build_digest_tree

            for i, child_node in enumerate(children_sorted):
                is_last = i == len(children_sorted) - 1
                prefix = "└── " if is_last else "├── "
                # Corrected variable name:
                child_indent_continuation = "    " if is_last else "│   "

                child_display_name = Path(child_node["relative_path"]).name

                if child_node["type"] == "folder":
                    lines.append(f"{indent}{prefix}{child_display_name}/")
                    # Pass the indent for the children of this child_node
                    lines.extend(
                        self._generate_directory_structure_string(child_node, indent + child_indent_continuation)
                    )
                else:  # file
                    lines.append(f"{indent}{prefix}{child_display_name}")
        return lines

    def _collect_file_contents_for_markdown(self, node: DigestItemNode, files_list: List) -> None:
        """
        Recursively collects file paths and contents for Markdown output.
        Ensures files are collected in a sorted order (traversal order).
        """
        if node["type"] == "file" and "content" in node and node["content"] is not None:
            files_list.append(
                {
                    "relative_path": node["relative_path"],
                    "content": node["content"],
                    "lang_hint": self._get_file_extension(node["relative_path"]),
                }
            )
        elif node["type"] == "file" and node.get("read_error"):
            files_list.append(
                {
                    "relative_path": node["relative_path"],
                    "content": f"Error reading file: {node['read_error']}",
                    "lang_hint": "text",  # Or no hint
                }
            )

        if node["type"] == "folder" and "children" in node:
            # Children are already sorted by build_digest_tree
            for child in node["children"]:
                self._collect_file_contents_for_markdown(child, files_list)


class JsonFormatter(BaseFormatter):
    """Formats the directory digest as JSON."""

    def format(self, data_tree: DigestItemNode) -> str:
        """
        Generates a JSON string representation of the directory digest.
        data_tree is the root_node from core.build_digest_tree.
        """
        output_data = {"metadata": self.final_metadata, "root": data_tree}

        def default_serializer(obj):
            if isinstance(obj, Path):  # Should not be in data_tree, but good for metadata
                return str(obj)
            raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

        return json.dumps(output_data, indent=2, default=default_serializer)


class MarkdownFormatter(BaseFormatter):
    """Formats the directory digest as Markdown."""

    def format(self, data_tree: DigestItemNode) -> str:
        """
        Generates a Markdown string representation of the directory digest.
        data_tree is the root_node from core.build_digest_tree.
        """
        md_lines = []

        # 1. Header Section
        md_lines.append(f"# Directory Digest: {self.final_metadata['base_directory']}")
        md_lines.append(
            f"\n*Generated by dirdigest v{self.final_metadata['tool_version']} on {self.final_metadata['created_at']}*"
        )
        md_lines.append(
            f"*Included files: {self.final_metadata['included_files_count']}, Total content size: {self.final_metadata['total_content_size_kb']:.2f} KB*"
        )
        # Add excluded_files_count when available
        md_lines.append("\n---")

        # 2. Directory Structure Visualization
        md_lines.append("\n## Directory Structure")
        # The root node itself ('relative_path': '.') shouldn't have a prefix like '├──'
        # The _generate_directory_structure_string starts with the name of the node.
        # We need to pass the root node directly to the helper.
        structure_lines = self._generate_directory_structure_string(data_tree)
        md_lines.append("\n```text")  # Use text to avoid markdown interpreting it
        md_lines.extend(structure_lines)
        md_lines.append("```\n")
        md_lines.append("\n---")

        # 3. File Contents
        md_lines.append("\n## Contents")

        collected_files: List[Dict[str, Any]] = []
        self._collect_file_contents_for_markdown(data_tree, collected_files)

        if not collected_files:
            md_lines.append("\n*No files with content to display.*")
        else:
            for file_info in collected_files:
                md_lines.append(f"\n### `./{file_info['relative_path']}`")  # Ensure ./ prefix
                lang_hint = file_info["lang_hint"] if file_info["lang_hint"] else ""
                md_lines.append(f"```{lang_hint}")
                md_lines.append(file_info["content"])
                md_lines.append("```")

        md_lines.append("\n")  # Trailing newline for cleanliness
        return "\n".join(md_lines)
