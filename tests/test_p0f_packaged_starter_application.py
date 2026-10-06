"""Stable release-qualification alias for the canonical V2 packaged starter tests.

The implementation and assertions remain owned by
``tests.test_v2_packaged_starter_application``.  W4 release qualification uses
the P0-F acceptance name so candidate workflows do not need to encode the
historical V2 module naming detail.
"""

from tests.test_v2_packaged_starter_application import *  # noqa: F401,F403
