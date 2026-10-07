from __future__ import annotations

"""Public product boundary for the private R00-R14 protection runtime.

This module intentionally contains no signing keys, issuer logic, device-anchor
implementation, build-verifier internals, or protection configuration. The public
product knows only the narrow integration contract and fails closed in packaged
releases when the private runtime is missing or malformed.
"""

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import stat
import sys
from types import ModuleType
from typing import Callable

PRIVATE_RUNTIME_MODULE = "accessible_chess_protection_runtime"
EXPECTED_RUNTIME_API_VERSION = 1
_SAFE_OPERATIONS = frozenset({
    "recovery", "login", "update", "help", "own-data-read", "own-data-export"
})


class ProtectionBoundaryError(RuntimeError):
    pass


class ProtectedStartupLocked(ProtectionBoundaryError):
    def __init__(self, decision: "ProtectionDecision", client: "ProtectionRuntimeClient"):
        super().__init__(f"Accessible Chess premium startup is locked: {decision.reason}")
        self.decision = decision
        self.client = client


@dataclass(frozen=True)
class ProtectionDecision:
    state: str
    reason: str
    safe_operations: frozenset[str]
    capabilities: frozenset[str]
    build_id: str | None

    @property
    def authorized(self) -> bool:
        return self.state == "authorized"


def _regular_release_manifest(application_dir: Path) -> bool:
    candidates = (
        application_dir / "RELEASE_MANIFEST.json",
        application_dir.parent / "RELEASE_MANIFEST.json",
    )
    for path in candidates:
        try:
            if stat.S_ISREG(path.lstat().st_mode):
                return True
        except OSError:
            continue
    return False


def protection_required(application_dir: str | Path, *, frozen: bool | None = None) -> bool:
    """Require protection for frozen or assembled release execution, not source tests."""
    root = Path(application_dir)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    return is_frozen or _regular_release_manifest(root)


def _locked(reason: str) -> ProtectionDecision:
    return ProtectionDecision(
        state="locked",
        reason=reason,
        safe_operations=_SAFE_OPERATIONS,
        capabilities=frozenset(),
        build_id=None,
    )


def _validate_string_list(value: object, *, name: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ProtectionBoundaryError(f"private protection {name} is invalid")
    if len(value) != len(set(value)):
        raise ProtectionBoundaryError(f"private protection {name} contains duplicates")
    return frozenset(value)


def _validate_decision(value: object) -> ProtectionDecision:
    if not isinstance(value, dict) or set(value) != {
        "api_version", "state", "reason", "safe_operations", "capabilities", "build_id"
    }:
        raise ProtectionBoundaryError("private protection decision schema is invalid")
    if value.get("api_version") != EXPECTED_RUNTIME_API_VERSION:
        raise ProtectionBoundaryError("private protection API version is unsupported")
    state = value.get("state")
    reason = value.get("reason")
    build_id = value.get("build_id")
    if state not in {"authorized", "locked"}:
        raise ProtectionBoundaryError("private protection state is invalid")
    if not isinstance(reason, str) or not reason:
        raise ProtectionBoundaryError("private protection reason is invalid")
    if build_id is not None and (not isinstance(build_id, str) or not build_id):
        raise ProtectionBoundaryError("private protection build identity is invalid")
    safe = _validate_string_list(value.get("safe_operations"), name="safe operations")
    capabilities = _validate_string_list(value.get("capabilities"), name="capabilities")
    if safe != _SAFE_OPERATIONS:
        raise ProtectionBoundaryError("private protection safe-operation contract drifted")
    if state == "authorized":
        if reason != "none" or build_id is None:
            raise ProtectionBoundaryError("authorized protection decision is inconsistent")
    else:
        if reason == "none" or capabilities:
            raise ProtectionBoundaryError("locked protection decision is inconsistent")
    return ProtectionDecision(
        state=state,
        reason=reason,
        safe_operations=safe,
        capabilities=capabilities,
        build_id=build_id,
    )


class ProtectionRuntimeClient:
    def __init__(
        self,
        *,
        application_dir: str | Path,
        state_root: str | Path,
        module_loader: Callable[[str], ModuleType] = importlib.import_module,
    ) -> None:
        if not callable(module_loader):
            raise TypeError("module_loader must be callable")
        self.application_dir = Path(application_dir)
        self.state_root = Path(state_root)
        self._module_loader = module_loader
        self._module: ModuleType | None = None

    def _runtime(self) -> ModuleType:
        if self._module is not None:
            return self._module
        try:
            module = self._module_loader(PRIVATE_RUNTIME_MODULE)
        except Exception as exc:
            raise ProtectionBoundaryError("private protection runtime is unavailable") from exc
        if getattr(module, "RUNTIME_API_VERSION", None) != EXPECTED_RUNTIME_API_VERSION:
            raise ProtectionBoundaryError("private protection runtime API version is unsupported")
        self._module = module
        return module

    def evaluate(self) -> ProtectionDecision:
        try:
            runtime = self._runtime()
            evaluate = getattr(runtime, "evaluate_startup", None)
            if not callable(evaluate):
                raise ProtectionBoundaryError("private protection evaluator is unavailable")
            return _validate_decision(
                evaluate(package_root=self.application_dir, state_root=self.state_root)
            )
        except ProtectionBoundaryError:
            raise
        except Exception as exc:
            raise ProtectionBoundaryError("private protection evaluation failed") from exc

    def create_activation_request(self) -> dict[str, object]:
        runtime = self._runtime()
        create = getattr(runtime, "create_activation_request", None)
        if not callable(create):
            raise ProtectionBoundaryError("private activation request operation is unavailable")
        try:
            value = create(package_root=self.application_dir, state_root=self.state_root)
        except Exception as exc:
            raise ProtectionBoundaryError("private activation request failed") from exc
        if not isinstance(value, dict):
            raise ProtectionBoundaryError("private activation request is invalid")
        return dict(value)

    def import_entitlement_json(self, raw_json: str) -> None:
        if not isinstance(raw_json, str) or not raw_json.strip():
            raise ProtectionBoundaryError("entitlement JSON is required")
        try:
            envelope = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ProtectionBoundaryError("entitlement JSON is invalid") from exc
        runtime = self._runtime()
        importer = getattr(runtime, "import_entitlement", None)
        if not callable(importer):
            raise ProtectionBoundaryError("private entitlement import operation is unavailable")
        try:
            importer(
                package_root=self.application_dir,
                state_root=self.state_root,
                envelope=envelope,
            )
        except Exception as exc:
            raise ProtectionBoundaryError("entitlement import was rejected") from exc


def authorize_release_startup(
    *,
    application_dir: str | Path,
    state_root: str | Path,
    required: bool | None = None,
    module_loader: Callable[[str], ModuleType] = importlib.import_module,
) -> ProtectionDecision:
    must_protect = protection_required(application_dir) if required is None else bool(required)
    if not must_protect:
        return ProtectionDecision(
            state="authorized",
            reason="source-development",
            safe_operations=_SAFE_OPERATIONS,
            capabilities=frozenset(),
            build_id="source-development",
        )
    client = ProtectionRuntimeClient(
        application_dir=application_dir,
        state_root=state_root,
        module_loader=module_loader,
    )
    try:
        decision = client.evaluate()
    except ProtectionBoundaryError:
        decision = _locked("runtime_unavailable_or_invalid")
    if not decision.authorized:
        raise ProtectedStartupLocked(decision, client)
    return decision


__all__ = [
    "EXPECTED_RUNTIME_API_VERSION",
    "PRIVATE_RUNTIME_MODULE",
    "ProtectionBoundaryError",
    "ProtectionDecision",
    "ProtectedStartupLocked",
    "ProtectionRuntimeClient",
    "authorize_release_startup",
    "protection_required",
]
