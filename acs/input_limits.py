"""Shared resource ceilings for untrusted textual product input.

These limits are representation budgets, not chess rules.  They are kept in a
small dependency-neutral module so canonical core and editor adapters can
enforce the same boundary before allocating split/token structures.
"""

MAX_FEN_CHARS = 4096
