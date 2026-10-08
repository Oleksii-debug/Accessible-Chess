from __future__ import annotations

"""Product-side names for the 48 canonical R28/R29 enforcement boundaries.

This module intentionally contains no security class, lease rule, server rule,
or private capability description.  Those remain private-runtime authority.
"""

CANONICAL_PRODUCT_BOUNDARY_IDS: tuple[str, ...] = (
    "BND.AC-S00-DATA",
    "BND.AC-S01-POSITION",
    "BND.AC-S02-GAMETREE",
    "BND.AC-S03-LIBRARY",
    "BND.AC-S04-CHESSBASE",
    "BND.AC-S05-BOOKDOC",
    "BND.AC-S06-TRAINING",
    "BND.AC-S07-FORMAT-QUAL",
    "BND.AC-S08-TACTILE-CORE",
    "BND.AC-S09-TACTILE-HW",
    "BND.AC-S10-TACTILE-SYNC",
    "BND.AC-S11-TACTILE-INPUT",
    "BND.AC-S12-LOCAL-CHESS",
    "BND.AC-S13-ENGINE",
    "BND.AC-S14-WINDOWS",
    "BND.AC-S15-VISUAL-BOARD",
    "BND.AC-S16-MEDIA-CORE",
    "BND.AC-S17-RECORDED-MEDIA",
    "BND.AC-S18-LIVE-BROADCAST",
    "BND.AC-S19-BOARD-VISION",
    "BND.AC-S19-MEDIA-INTEL",
    "BND.AC-S20-MEDIA-LOCAL-WF",
    "BND.AC-S20-MEDIA-SERVER-WF",
    "BND.AC-S21-AGENT-RUNTIME",
    "BND.AC-S22-AGENT-TOOLS",
    "BND.AC-S23-AI-COACH",
    "BND.AC-S24-AGENT-VOICE",
    "BND.AC-S24-AGENT-SAFETY",
    "BND.AC-S25-POINTER",
    "BND.AC-S26-LOCAL-CLASSROOM",
    "BND.AC-S27-TEACHING-INPUT",
    "BND.AC-S28-LOCAL-COURSES",
    "BND.AC-S29-PRIVACY-FOUNDATION",
    "BND.AC-S30-SERVER-API",
    "BND.AC-S31-LOGIN",
    "BND.AC-S31-CLOUD-SYNC",
    "BND.AC-S32-REMOTE-CLASSROOM",
    "BND.AC-S33-ONLINE-GAME",
    "BND.AC-S34-WEB-PREMIUM",
    "BND.AC-S34-WEB-SAFETY",
    "BND.AC-S35-COMMERCIAL",
    "BND.AC-S36-LOCAL-INTEGRATION",
    "BND.AC-S36-SERVER-INTEGRATION",
    "BND.AC-S36-SAFETY-INTEGRATION",
    "BND.AC-S37-PERSISTENCE",
    "BND.AC-S37-PORTABILITY",
    "BND.AC-S38-LOCAL-LICENSING",
    "BND.AC-S38-UPDATE-REPAIR",
)

if len(CANONICAL_PRODUCT_BOUNDARY_IDS) != 48 or len(set(CANONICAL_PRODUCT_BOUNDARY_IDS)) != 48:
    raise RuntimeError("canonical product security-boundary inventory is invalid")

BOUNDARIES_BY_SURFACE: dict[str, tuple[str, ...]] = {
    "formats.core": (
        "BND.AC-S00-DATA",
        "BND.AC-S01-POSITION",
        "BND.AC-S02-GAMETREE",
        "BND.AC-S04-CHESSBASE",
        "BND.AC-S07-FORMAT-QUAL",
    ),
    "library.local": ("BND.AC-S03-LIBRARY",),
    "books.training": ("BND.AC-S05-BOOKDOC", "BND.AC-S06-TRAINING"),
    "tactile.local": (
        "BND.AC-S08-TACTILE-CORE",
        "BND.AC-S09-TACTILE-HW",
        "BND.AC-S10-TACTILE-SYNC",
        "BND.AC-S11-TACTILE-INPUT",
    ),
    "chess.local": (
        "BND.AC-S12-LOCAL-CHESS",
        "BND.AC-S14-WINDOWS",
        "BND.AC-S15-VISUAL-BOARD",
    ),
    "engine.local": ("BND.AC-S13-ENGINE",),
    "media.local": (
        "BND.AC-S16-MEDIA-CORE",
        "BND.AC-S17-RECORDED-MEDIA",
        "BND.AC-S19-BOARD-VISION",
        "BND.AC-S20-MEDIA-LOCAL-WF",
    ),
    "media.server": (
        "BND.AC-S18-LIVE-BROADCAST",
        "BND.AC-S19-MEDIA-INTEL",
        "BND.AC-S20-MEDIA-SERVER-WF",
    ),
    "agent.server": (
        "BND.AC-S21-AGENT-RUNTIME",
        "BND.AC-S22-AGENT-TOOLS",
        "BND.AC-S23-AI-COACH",
        "BND.AC-S24-AGENT-VOICE",
    ),
    "agent.safety": ("BND.AC-S24-AGENT-SAFETY",),
    "pointer.local": ("BND.AC-S25-POINTER",),
    "classroom.local": (
        "BND.AC-S26-LOCAL-CLASSROOM",
        "BND.AC-S27-TEACHING-INPUT",
        "BND.AC-S28-LOCAL-COURSES",
    ),
    "privacy.safety": ("BND.AC-S29-PRIVACY-FOUNDATION",),
    "server.api": ("BND.AC-S30-SERVER-API",),
    "account.login": ("BND.AC-S31-LOGIN",),
    "cloud.server": ("BND.AC-S31-CLOUD-SYNC",),
    "classroom.remote": ("BND.AC-S32-REMOTE-CLASSROOM",),
    "online.game": ("BND.AC-S33-ONLINE-GAME",),
    "web.premium": ("BND.AC-S34-WEB-PREMIUM",),
    "web.safety": ("BND.AC-S34-WEB-SAFETY",),
    "commercial.server": ("BND.AC-S35-COMMERCIAL",),
    "integration.local": ("BND.AC-S36-LOCAL-INTEGRATION",),
    "integration.server": ("BND.AC-S36-SERVER-INTEGRATION",),
    "integration.safety": ("BND.AC-S36-SAFETY-INTEGRATION",),
    "persistence.local": ("BND.AC-S37-PERSISTENCE",),
    "portability.safety": ("BND.AC-S37-PORTABILITY",),
    "licensing.local": ("BND.AC-S38-LOCAL-LICENSING",),
    "update.repair": ("BND.AC-S38-UPDATE-REPAIR",),
}

if set(item for values in BOUNDARIES_BY_SURFACE.values() for item in values) != set(CANONICAL_PRODUCT_BOUNDARY_IDS):
    raise RuntimeError("product security surfaces do not cover every canonical boundary")


def boundaries_for_surface(surface: str) -> tuple[str, ...]:
    if type(surface) is not str:
        raise TypeError("security surface must be text")
    try:
        return BOUNDARIES_BY_SURFACE[surface]
    except KeyError:
        raise KeyError("unknown product security surface") from None


def boundaries_for_action(action_id: str) -> tuple[str, ...]:
    if type(action_id) is not str or not action_id:
        raise ValueError("action id must be canonical text")

    if action_id.startswith("pgn."):
        return ("BND.AC-S02-GAMETREE", "BND.AC-S36-LOCAL-INTEGRATION")
    if action_id.startswith("position."):
        return ("BND.AC-S01-POSITION",)
    if action_id.startswith("library."):
        return ("BND.AC-S03-LIBRARY", "BND.AC-S37-PERSISTENCE")
    if action_id.startswith("book."):
        return ("BND.AC-S05-BOOKDOC",)
    if action_id.startswith("training."):
        return ("BND.AC-S06-TRAINING",)
    if action_id.startswith("teacher."):
        return (
            "BND.AC-S25-POINTER",
            "BND.AC-S26-LOCAL-CLASSROOM",
            "BND.AC-S27-TEACHING-INPUT",
        )
    if action_id.startswith("student."):
        return ("BND.AC-S27-TEACHING-INPUT",)
    if action_id.startswith(("education.", "classes.")):
        return ("BND.AC-S28-LOCAL-COURSES",)
    if action_id.startswith("classroom."):
        return ("BND.AC-S26-LOCAL-CLASSROOM",)
    if action_id.startswith("remote."):
        return (
            "BND.AC-S32-REMOTE-CLASSROOM",
            "BND.AC-S36-SERVER-INTEGRATION",
        )
    if action_id.startswith("profile."):
        return ("BND.AC-S14-WINDOWS", "BND.AC-S37-PERSISTENCE")
    if action_id.startswith("data."):
        return ("BND.AC-S37-PORTABILITY", "BND.AC-S36-SAFETY-INTEGRATION")
    if action_id.startswith("release."):
        return ("BND.AC-S38-UPDATE-REPAIR",)
    if action_id == "screen.help":
        return ("BND.AC-S38-UPDATE-REPAIR",)
    if action_id == "screen.analysis":
        return ("BND.AC-S13-ENGINE",)
    if action_id == "screen.board":
        return ("BND.AC-S12-LOCAL-CHESS", "BND.AC-S15-VISUAL-BOARD")
    if action_id == "screen.pgn":
        return ("BND.AC-S02-GAMETREE",)
    if action_id == "screen.library":
        return ("BND.AC-S03-LIBRARY",)
    if action_id == "screen.books":
        return ("BND.AC-S05-BOOKDOC",)
    if action_id == "screen.training":
        return ("BND.AC-S06-TRAINING",)
    if action_id == "screen.settings":
        return ("BND.AC-S14-WINDOWS",)
    return ()


__all__ = [
    "BOUNDARIES_BY_SURFACE",
    "CANONICAL_PRODUCT_BOUNDARY_IDS",
    "boundaries_for_action",
    "boundaries_for_surface",
]
