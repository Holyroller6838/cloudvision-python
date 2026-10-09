#!/usr/bin/env python3
"""CLI for the lab MLAG configlet builder.

Prints valid EOS configuration only. Does not push to CloudVision or devices.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import MlagConfigletBuilder
from .models import InputError, load_inputs
from .safety import SafetyError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate additive EOS MLAG configlets for lab switches "
            "(LAB01A / LAB01B by default)."
        )
    )
    parser.add_argument(
        "--inputs",
        "-i",
        required=True,
        type=Path,
        help="YAML file with shared domain, peer-link, VLAN, and device parameters",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--device",
        "-d",
        help="Hostname to generate (e.g. LAB01A)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Generate configlets for every device in the inputs file",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        help="If set, write <hostname>.cfg files instead of printing to stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        inputs = load_inputs(args.inputs)
        builder = MlagConfigletBuilder(inputs)
        if args.all:
            configlets = builder.build_all()
        else:
            configlets = {args.device: builder.build(args.device)}
    except (InputError, SafetyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for hostname, config in configlets.items():
            out_path = args.output_dir / f"{hostname}.cfg"
            out_path.write_text(config, encoding="utf-8")
            print(f"wrote {out_path}", file=sys.stderr)
        return 0

    # When generating multiple devices to stdout, separate with a clear marker
    # comment so operators can split them; each block remains valid EOS.
    blocks = []
    for hostname, config in configlets.items():
        if args.all and len(configlets) > 1:
            blocks.append(f"! ===== begin {hostname} =====\n{config.rstrip()}\n! ===== end {hostname} =====")
        else:
            blocks.append(config.rstrip())
    sys.stdout.write("\n".join(blocks) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
