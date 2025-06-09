import pytest
from typing import List, Tuple, Any

from dirdigest.constants import OperationalMode

# This helper function directly mirrors the mode determination logic from cli.py
# It takes sys_argv_like (a list of strings), include_patterns (resolved), and exclude_patterns (raw user/config)
def determine_mode_for_test(
    sys_argv_like: List[str],
    final_include_list: List[str],
    raw_user_config_exclude_list: List[str] # Corresponds to raw_exclude_patterns in cli.py
) -> OperationalMode:
    first_i_idx = float('inf')
    first_x_idx = float('inf')

    for idx, arg in enumerate(sys_argv_like):
        if arg == "-i" or arg == "--include":
            if idx < first_i_idx:
                first_i_idx = idx
        elif arg == "-x" or arg == "--exclude":
            if idx < first_x_idx:
                first_x_idx = idx

    operational_mode: OperationalMode

    has_final_includes = bool(final_include_list)
    has_user_excludes = bool(raw_user_config_exclude_list)

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
            # No direct logging here as this is a test helper.
            operational_mode = OperationalMode.MODE_EXCLUDE_FIRST
    return operational_mode

@pytest.mark.parametrize(
    "argv, includes, excludes, expected_mode",
    [
        # Only include
        (["dirdigest", "-i", "foo"], ["foo"], [], OperationalMode.MODE_ONLY_INCLUDE),
        (["dirdigest", "--include", "foo"], ["foo"], [], OperationalMode.MODE_ONLY_INCLUDE),
        # Only exclude
        (["dirdigest", "-x", "bar"], [], ["bar"], OperationalMode.MODE_ONLY_EXCLUDE),
        (["dirdigest", "--exclude", "bar"], [], ["bar"], OperationalMode.MODE_ONLY_EXCLUDE),
        # Neither (default)
        (["dirdigest"], [], [], OperationalMode.MODE_INCLUDE_ALL_DEFAULT),
        # Include then Exclude
        (["dirdigest", "-i", "foo", "-x", "bar"], ["foo"], ["bar"], OperationalMode.MODE_INCLUDE_FIRST),
        (["dirdigest", "--include", "foo", "--exclude", "bar"], ["foo"], ["bar"], OperationalMode.MODE_INCLUDE_FIRST),
        (["dirdigest", "-i", "foo", "-i", "baz", "-x", "bar"], ["foo", "baz"], ["bar"], OperationalMode.MODE_INCLUDE_FIRST),
        # Exclude then Include
        (["dirdigest", "-x", "bar", "-i", "foo"], ["foo"], ["bar"], OperationalMode.MODE_EXCLUDE_FIRST),
        (["dirdigest", "--exclude", "bar", "--include", "foo"], ["foo"], ["bar"], OperationalMode.MODE_EXCLUDE_FIRST),
        # Config-only scenarios (flags not in argv, but patterns are present)
        # Both present, no flags -> default to EXCLUDE_FIRST
        (["dirdigest", "--config", "my.toml"], ["conf_inc"], ["conf_exc"], OperationalMode.MODE_EXCLUDE_FIRST),
        # Only includes from config
        (["dirdigest", "--config", "my.toml"], ["conf_inc"], [], OperationalMode.MODE_ONLY_INCLUDE),
        # Only excludes from config
        (["dirdigest", "--config", "my.toml"], [], ["conf_exc"], OperationalMode.MODE_ONLY_EXCLUDE),
        # No includes/excludes from config (same as no flags at all)
        (["dirdigest", "--config", "my.toml"], [], [], OperationalMode.MODE_INCLUDE_ALL_DEFAULT),
        # Mixed: includes from config, exclude from CLI (exclude flag is present and first)
        (["dirdigest", "-x", "cli_exc", "--config", "my.toml"], ["conf_inc"], ["conf_exc", "cli_exc"], OperationalMode.MODE_EXCLUDE_FIRST),
        # Mixed: excludes from config, include from CLI (include flag is present and first)
        (["dirdigest", "-i", "cli_inc", "--config", "my.toml"], ["conf_inc", "cli_inc"], ["conf_exc"], OperationalMode.MODE_INCLUDE_FIRST),
        # Mixed: includes from CLI (first), exclude from config (no -x flag in argv)
        (["dirdigest", "-i", "cli_inc", "--config", "my.toml"], ["cli_inc", "conf_inc"], ["conf_exc"], OperationalMode.MODE_INCLUDE_FIRST),
         # Mixed: excludes from CLI (first), include from config (no -i flag in argv)
        (["dirdigest", "-x", "cli_exc", "--config", "my.toml"], ["conf_inc"], ["cli_exc", "conf_exc"], OperationalMode.MODE_EXCLUDE_FIRST),
    ]
)
def test_operational_mode_determination(
    argv: List[str],
    includes: List[str], # Represents final_include from CLI (merged CLI+config)
    excludes: List[str], # Represents raw_exclude_patterns from CLI (merged CLI+config, before auto-output-exclude)
    expected_mode: OperationalMode
):
    assert determine_mode_for_test(argv, includes, excludes) == expected_mode
