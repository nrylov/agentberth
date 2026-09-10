"""Deployment-wide execution limits; API and worker must use the same settings."""

import os


def positive_integer(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a positive integer.") from None
    if value < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return value


MAX_CONCURRENT_RUNS = positive_integer("MAX_CONCURRENT_RUNS", 3)
MAX_QUEUED_RUNS = positive_integer("MAX_QUEUED_RUNS", 50)
