"""Standalone lab MLAG configlet builder for LAB01A / LAB01B.

This package is intentionally separate from the enterprise CloudVision library
and existing Studio / configlet examples.
"""

from .builder import MlagConfigletBuilder, build_configlets_from_file
from .models import MlagLabInputs, load_inputs

__all__ = [
    "MlagConfigletBuilder",
    "MlagLabInputs",
    "build_configlets_from_file",
    "load_inputs",
]

__version__ = "1.0.0"
