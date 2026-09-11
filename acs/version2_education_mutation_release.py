from __future__ import annotations

"""Post-#645 final-product composition with the first durable Education mutation.

The parent final-product release intentionally owns the accepted profile/resource
late bindings.  This child must not permanently replace its application-class
binding merely by being imported: broad release tests and other composition
owners share that module in one Python process.  Bind the child class only while
this composition root is constructing/running its application, then restore the
parent owner exactly.
"""

from contextlib import contextmanager
from typing import Any, Iterator

# Import the current final-product release first so its accepted profile/resource
# late bindings remain authoritative.
from . import version2_final_release as _final_release  # noqa: F401
from . import version2_release_app as _release_app
from .version2_education_mutation_application import Version2EducationMutationApplication


@contextmanager
def _mutation_application_binding() -> Iterator[None]:
    previous = _release_app.Version2Application
    _release_app.Version2Application = Version2EducationMutationApplication
    try:
        yield
    finally:
        _release_app.Version2Application = previous


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Compose through the existing release root without leaking global ownership.

    ``version2_release_app`` defers application construction onto the native UI
    thread when ``defer_ui=True``.  In that mode the returned one-shot builder
    must reacquire this bounded binding at invocation time as well; otherwise it
    would silently fall back to the parent application after this wrapper exits.
    """

    defer_ui = kwargs.get("defer_ui", False) is True
    with _mutation_application_binding():
        composed = _release_app.create_version2_release_application(*args, **kwargs)

    if not defer_ui:
        return composed

    api, application_factory, runtime, native_runtime_factory = composed
    if not callable(application_factory):
        raise TypeError("deferred Version 2 application factory must be callable")

    def build_mutation_application():
        with _mutation_application_binding():
            return application_factory()

    return api, build_mutation_application, runtime, native_runtime_factory


def main() -> None:
    # The existing main() owns the full synchronous UI lifetime.  Keep the child
    # class bound for that lifetime so its deferred UI-thread builder sees the
    # intended class, then restore the parent release owner on exit/failure.
    with _mutation_application_binding():
        _release_app.main()


__all__ = ["create_version2_release_application", "main"]
