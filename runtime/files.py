"""Shared bounded file transport for run inputs and output artifacts."""

import base64
import binascii
import re

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * MAX_FILE_BYTES
MAX_FILES = 8
MAX_BASE64 = 4 * ((MAX_FILE_BYTES + 2) // 3)


def validate_name(name):
    if not re.fullmatch(r"[a-zA-Z0-9_./ -]{1,150}", name) or any(
        not part or part in {".", ".."} or part.startswith(".") or part.endswith(" ")
        for part in name.split("/")
    ):
        raise ValueError(
            "Use a relative file path with letters, numbers, spaces, underscores, dots, or hyphens; no hidden or parent paths."
        )
    return name


def decode_file(value):
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("File content must be valid base64.") from None
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Each file must be at most 1 MiB.")
    return content


def validate_collection(files):
    names = [f.name for f in files]
    if len(set(names)) != len(names) or any(
        other.startswith(name + "/") for name in names for other in names if other != name
    ):
        raise ValueError("File names must be unique and cannot conflict with a directory path.")
    if sum(len(f.bytes_value()) for f in files) > MAX_TOTAL_BYTES:
        raise ValueError("Files must total at most 4 MiB.")
    return files
