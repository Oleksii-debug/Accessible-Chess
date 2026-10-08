"""Shared resource ceilings for untrusted textual product input.

These limits are representation budgets, not chess rules.  They are kept in a
small dependency-neutral module so canonical core and editor adapters can
enforce the same boundary before allocating split/token structures.
"""

MAX_FEN_CHARS = 4096
# Canonical square names are two characters; retain generous surrounding-space
# compatibility while bounding strip/lower work on direct UI/API input.
MAX_SQUARE_TEXT_CHARS = 256

# Canonical SAN and coordinate-move tokens are intrinsically tiny. Bound raw
# text before strip()/normalization in both notation and chess legality ingress.
# 64 keeps broad compatibility headroom while preventing unbounded direct-core work.
MAX_SAN_CHARS = 64
