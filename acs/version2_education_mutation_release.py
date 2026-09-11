from __future__ import annotations

"""Post-#645 final-product composition with the first durable Education mutation."""

# Import the current final-product release first so its accepted profile/resource
# late bindings remain authoritative, then narrow only the application class used
# by the existing release composition root.
from . import version2_final_release as _final_release  # noqa: F401
from . import version2_release_app as _release_app
from .version2_education_mutation_application import Version2EducationMutationApplication

_release_app.Version2Application = Version2EducationMutationApplication

create_version2_release_application = _release_app.create_version2_release_application
main = _release_app.main

__all__ = ["create_version2_release_application", "main"]
