"""Safety checks for generated EOS configlets.

The builder must only emit additive, valid EOS configuration and must never
reset interfaces, strip existing config, or alter management connectivity.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

# Destructive / reset patterns that must never appear in generated output.
_BANNED_LINE_PATTERNS: Sequence[Tuple[re.Pattern[str], str]] = (
    (re.compile(r"^\s*default\s+interface\b", re.I), "resets an interface"),
    (re.compile(r"^\s*default\s+", re.I), "uses a destructive default command"),
    (re.compile(r"^\s*write\s+erase\b", re.I), "erases startup configuration"),
    (re.compile(r"^\s*reload\b", re.I), "reloads the device"),
    (re.compile(r"^\s*delete\s+", re.I), "deletes files or configuration"),
    (
        re.compile(r"^\s*no\s+interface\b", re.I),
        "removes an interface configuration block",
    ),
    (re.compile(r"^\s*no\s+vlan\b", re.I), "removes VLAN configuration"),
    (re.compile(r"^\s*no\s+mlag\b", re.I), "removes MLAG configuration"),
    (
        re.compile(r"^\s*no\s+channel-group\b", re.I),
        "removes an existing channel-group",
    ),
    (
        re.compile(r"^\s*interface\s+management\d*\b", re.I),
        "modifies management connectivity",
    ),
    (
        re.compile(r"^\s*interface\s+ma\d+\b", re.I),
        "modifies management connectivity",
    ),
    (
        re.compile(r"^\s*management\s+(api|console|ssh|telnet)\b", re.I),
        "modifies management connectivity",
    ),
    (
        re.compile(r"^\s*ip\s+route\s+0\.0\.0\.0/0\b", re.I),
        "changes default routing / management path",
    ),
)

# "no shutdown" and similar enabling forms are allowed; other bare "no" lines
# at interface-context depth are rejected by the banned patterns above plus this
# catch-all for unexpected removals.
_ALLOWED_NO_COMMANDS = frozenset(
    {
        "no shutdown",
        "no switchport",  # not emitted by this builder, but not a management wipe
    }
)

_CATCHALL_NO = re.compile(r"^\s*no\s+", re.I)

# Lines that look like valid EOS config for this builder's scope.
_ALLOWED_LINE = re.compile(
    r"^(?:"
    r"!.*"  # comments
    r"|vlan\s+\d+"
    r"|name\s+\S+"
    r"|trunk\s+group\s+\S+"
    r"|interface\s+(?:Port-Channel|Ethernet|Vlan)\S*"
    r"|description\s+.+"
    r"|switchport(?:\s+.*)?"
    r"|channel-group\s+\d+\s+mode\s+(?:active|passive|on)"
    r"|ip\s+address\s+\S+"
    r"|mlag\s+configuration"
    r"|domain-id\s+\S+"
    r"|local-interface\s+Vlan\d+"
    r"|peer-address\s+\S+"
    r"|peer-link\s+Port-Channel\d+"
    r"|mlag\s+\d+"
    r"|no\s+shutdown"
    r")$"
    ,
    re.I,
)


class SafetyError(ValueError):
    """Raised when generated configuration violates safety rules."""


def _normalized_lines(config: str) -> List[str]:
    return [line.rstrip() for line in config.splitlines()]


def assert_safe_eos_config(config: str) -> None:
    """Validate that *config* is additive EOS and does not touch management."""
    if not config or not config.strip():
        raise SafetyError("configuration is empty")

    lines = _normalized_lines(config)
    problems: List[str] = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        for pattern, reason in _BANNED_LINE_PATTERNS:
            if pattern.search(stripped):
                problems.append(f"line {lineno}: banned ({reason}): {stripped}")
                break
        else:
            if _CATCHALL_NO.match(stripped):
                # Allow only known enabling forms.
                if stripped.lower() not in _ALLOWED_NO_COMMANDS:
                    problems.append(
                        f"line {lineno}: unexpected removal command: {stripped}"
                    )
                    continue

            if not _ALLOWED_LINE.match(stripped):
                problems.append(
                    f"line {lineno}: not a recognized additive EOS statement: {stripped}"
                )

    if problems:
        joined = "\n".join(problems)
        raise SafetyError(f"unsafe or invalid EOS configuration:\n{joined}")


def collect_banned_matches(config: str) -> List[str]:
    """Return human-readable banned-line matches (for tests / diagnostics)."""
    matches: List[str] = []
    for line in _normalized_lines(config):
        stripped = line.strip()
        if not stripped:
            continue
        for pattern, reason in _BANNED_LINE_PATTERNS:
            if pattern.search(stripped):
                matches.append(f"{reason}: {stripped}")
                break
    return matches


def ensure_no_management_interfaces(interfaces: Iterable[str]) -> None:
    """Reject management interface names in builder inputs."""
    for name in interfaces:
        lowered = name.strip().lower()
        if lowered.startswith("management") or re.fullmatch(r"ma\d+", lowered):
            raise SafetyError(
                f"management interface {name!r} cannot be used in MLAG configlets"
            )
