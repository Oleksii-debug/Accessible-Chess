from __future__ import annotations

"""Deterministic SLSA Provenance v1 statements for GitHub Actions release builds."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from urllib.parse import urlparse

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
BUILD_TYPE = "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^refs/(heads|tags)/[^\x00-\x1f\x7f]+$")
_WORKFLOW_PATH_RE = re.compile(r"^\.github/workflows/[^/\\]+\.(yml|yaml)$")
_ALLOWED_EVENTS = frozenset({"create", "release", "push", "workflow_dispatch"})


class ProvenanceError(ValueError):
    """Raised for ambiguous or non-canonical provenance inputs."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GithubWorkflowBuild:
    repository: str
    ref: str
    workflow_path: str
    source_sha: str
    builder_id: str
    invocation_id: str
    event_name: str
    actor_id: str
    repository_id: str
    repository_owner_id: str
    triggering_actor_id: str | None = None

    def __post_init__(self) -> None:
        repository = _github_repository(self.repository)
        ref = _ref(self.ref)
        workflow_path = _workflow_path(self.workflow_path)
        source_sha = _sha40(self.source_sha, "source sha")
        builder_id = _builder_id(self.builder_id)
        invocation_id = _invocation_id(self.invocation_id, repository)
        event_name = _text(self.event_name, "event name", 64)
        if event_name not in _ALLOWED_EVENTS:
            raise ProvenanceError(
                "event is unsupported by GitHub Actions workflow/v1 buildType"
            )
        actor_id = _numeric_id(self.actor_id, "actor id")
        repository_id = _numeric_id(self.repository_id, "repository id")
        repository_owner_id = _numeric_id(
            self.repository_owner_id, "repository owner id"
        )
        triggering = self.triggering_actor_id
        if triggering is not None:
            triggering = _numeric_id(triggering, "triggering actor id")
            if triggering == actor_id:
                triggering = None

        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "ref", ref)
        object.__setattr__(self, "workflow_path", workflow_path)
        object.__setattr__(self, "source_sha", source_sha)
        object.__setattr__(self, "builder_id", builder_id)
        object.__setattr__(self, "invocation_id", invocation_id)
        object.__setattr__(self, "event_name", event_name)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "repository_id", repository_id)
        object.__setattr__(self, "repository_owner_id", repository_owner_id)
        object.__setattr__(self, "triggering_actor_id", triggering)


def build_provenance_statement(
    *,
    artifact_name: str,
    artifact_sha256: str,
    workflow: GithubWorkflowBuild,
    started_on: datetime,
    finished_on: datetime,
    workflow_inputs: Mapping[str, Any] | None = None,
    repository_vars: Mapping[str, Any] | None = None,
    release_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one canonical in-toto Statement carrying SLSA Provenance v1.

    This records provenance facts only. It does not sign the statement and must
    not be used by itself to claim SLSA Build L2 or L3.
    """

    if type(workflow) is not GithubWorkflowBuild:
        raise ProvenanceError("workflow must be GithubWorkflowBuild")
    name = _artifact_name(artifact_name)
    digest = _sha256(artifact_sha256, "artifact sha256")
    started = _timestamp(started_on, "started_on")
    finished = _timestamp(finished_on, "finished_on")
    if finished_on.astimezone(timezone.utc) < started_on.astimezone(timezone.utc):
        raise ProvenanceError("finished_on must not precede started_on")

    inputs = _json_object(workflow_inputs, "workflow inputs")
    vars_ = _json_object(repository_vars, "repository vars")
    release = _json_object(release_parameters, "release parameters")
    if release and workflow.event_name != "release":
        raise ProvenanceError("release parameters require release event")
    if inputs and workflow.event_name != "workflow_dispatch":
        raise ProvenanceError("workflow inputs require workflow_dispatch event")
    if inputs and release:
        raise ProvenanceError("inputs and release parameters are mutually exclusive")

    external: dict[str, Any] = {
        "workflow": {
            "ref": workflow.ref,
            "repository": workflow.repository,
            "path": workflow.workflow_path,
        }
    }
    if inputs:
        external["inputs"] = inputs
    if release:
        external["release"] = release
    if vars_:
        external["vars"] = vars_

    github_internal: dict[str, str] = {
        "actor_id": workflow.actor_id,
        "event_name": workflow.event_name,
        "repository_id": workflow.repository_id,
        "repository_owner_id": workflow.repository_owner_id,
    }
    if workflow.triggering_actor_id is not None:
        github_internal["triggering_actor_id"] = workflow.triggering_actor_id

    statement = {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": name, "digest": {"sha256": digest}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": external,
                "internalParameters": {"github": github_internal},
                "resolvedDependencies": [
                    {
                        "uri": f"git+{workflow.repository}@{workflow.ref}",
                        "digest": {"gitCommit": workflow.source_sha},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": workflow.builder_id},
                "metadata": {
                    "invocationId": workflow.invocation_id,
                    "startedOn": started,
                    "finishedOn": finished,
                },
            },
        },
    }
    validate_provenance_statement(statement)
    return statement


def canonical_provenance_json(statement: Mapping[str, Any]) -> str:
    validate_provenance_statement(statement)
    return json.dumps(
        statement,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def provenance_sha256(statement: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_provenance_json(statement).encode("utf-8")
    ).hexdigest()


def load_provenance_manifest(path: str | Path) -> dict[str, Any]:
    raw = _regular_text(Path(path), "provenance manifest")
    if len(raw.encode("utf-8")) > 1024 * 1024:
        raise ProvenanceError("provenance manifest exceeds 1 MiB")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except _DuplicateKey as exc:
        raise ProvenanceError(f"duplicate JSON key: {exc.args[0]}") from exc
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"invalid provenance manifest JSON: {exc.msg}") from exc
    if type(value) is not dict or set(value) != {
        "artifact",
        "workflow",
        "started_on",
        "finished_on",
        "workflow_inputs",
        "repository_vars",
        "release_parameters",
    }:
        raise ProvenanceError("invalid provenance manifest root")
    return value


def build_from_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProvenanceError("manifest must be a plain object")
    artifact = value.get("artifact")
    workflow_data = value.get("workflow")
    if type(artifact) is not dict or set(artifact) != {"name", "sha256"}:
        raise ProvenanceError("invalid artifact manifest")
    workflow_keys = {
        "repository",
        "ref",
        "workflow_path",
        "source_sha",
        "builder_id",
        "invocation_id",
        "event_name",
        "actor_id",
        "repository_id",
        "repository_owner_id",
        "triggering_actor_id",
    }
    if type(workflow_data) is not dict or set(workflow_data) != workflow_keys:
        raise ProvenanceError("invalid workflow manifest")
    workflow = GithubWorkflowBuild(**workflow_data)
    started = _parse_timestamp(value.get("started_on"), "started_on")
    finished = _parse_timestamp(value.get("finished_on"), "finished_on")
    return build_provenance_statement(
        artifact_name=artifact["name"],
        artifact_sha256=artifact["sha256"],
        workflow=workflow,
        started_on=started,
        finished_on=finished,
        workflow_inputs=value.get("workflow_inputs"),
        repository_vars=value.get("repository_vars"),
        release_parameters=value.get("release_parameters"),
    )


def generate_provenance_file(
    input_path: str | Path,
    output_path: str | Path,
) -> str:
    encoded = canonical_provenance_json(
        build_from_manifest(load_provenance_manifest(input_path))
    )
    _atomic_text(Path(output_path), encoded)
    return encoded


def validate_provenance_statement(statement: Mapping[str, Any]) -> None:
    if type(statement) is not dict or set(statement) != {
        "_type",
        "subject",
        "predicateType",
        "predicate",
    }:
        raise ProvenanceError("invalid in-toto statement keys")
    if statement["_type"] != STATEMENT_TYPE:
        raise ProvenanceError("invalid in-toto statement type")
    if statement["predicateType"] != PREDICATE_TYPE:
        raise ProvenanceError("invalid SLSA predicate type")

    subjects = statement["subject"]
    if type(subjects) is not list or len(subjects) != 1:
        raise ProvenanceError("provenance must describe exactly one release artifact")
    subject = subjects[0]
    if type(subject) is not dict or set(subject) != {"name", "digest"}:
        raise ProvenanceError("invalid provenance subject")
    _artifact_name(subject["name"])
    digest = subject["digest"]
    if type(digest) is not dict or set(digest) != {"sha256"}:
        raise ProvenanceError("subject must have exactly one sha256 digest")
    _sha256(digest["sha256"], "subject sha256")

    predicate = statement["predicate"]
    if type(predicate) is not dict or set(predicate) != {
        "buildDefinition",
        "runDetails",
    }:
        raise ProvenanceError("invalid SLSA provenance predicate")
    definition = predicate["buildDefinition"]
    if type(definition) is not dict or set(definition) != {
        "buildType",
        "externalParameters",
        "internalParameters",
        "resolvedDependencies",
    }:
        raise ProvenanceError("invalid buildDefinition")
    if definition["buildType"] != BUILD_TYPE:
        raise ProvenanceError("unexpected GitHub Actions buildType")

    external = definition["externalParameters"]
    if type(external) is not dict or "workflow" not in external:
        raise ProvenanceError("externalParameters must contain workflow")
    if set(external) - {"workflow", "inputs", "release", "vars"}:
        raise ProvenanceError("unknown externalParameters field")
    workflow = external["workflow"]
    if type(workflow) is not dict or set(workflow) != {
        "ref",
        "repository",
        "path",
    }:
        raise ProvenanceError("invalid workflow external parameter")
    ref = _ref(workflow["ref"])
    repository = _github_repository(workflow["repository"])
    _workflow_path(workflow["path"])
    if "inputs" in external:
        _json_object(external["inputs"], "workflow inputs")
    if "release" in external:
        _json_object(external["release"], "release parameters")
    if "vars" in external:
        _json_object(external["vars"], "repository vars")
    if "inputs" in external and "release" in external:
        raise ProvenanceError("inputs and release are mutually exclusive")

    internal = definition["internalParameters"]
    if type(internal) is not dict or set(internal) != {"github"}:
        raise ProvenanceError("invalid internalParameters")
    gh = internal["github"]
    required_internal = {
        "actor_id",
        "event_name",
        "repository_id",
        "repository_owner_id",
    }
    if type(gh) is not dict or not required_internal.issubset(gh):
        raise ProvenanceError("invalid GitHub internalParameters")
    if set(gh) - required_internal - {"triggering_actor_id"}:
        raise ProvenanceError("unknown GitHub internal parameter")
    event = _text(gh["event_name"], "event name", 64)
    if event not in _ALLOWED_EVENTS:
        raise ProvenanceError("unsupported GitHub Actions event")
    for key in required_internal - {"event_name"}:
        _numeric_id(gh[key], key)
    if "triggering_actor_id" in gh:
        _numeric_id(gh["triggering_actor_id"], "triggering actor id")
    if "inputs" in external and event != "workflow_dispatch":
        raise ProvenanceError("inputs require workflow_dispatch")
    if "release" in external and event != "release":
        raise ProvenanceError("release parameters require release event")

    deps = definition["resolvedDependencies"]
    if type(deps) is not list or len(deps) != 1:
        raise ProvenanceError("exactly one resolved workflow dependency is required")
    dep = deps[0]
    if type(dep) is not dict or set(dep) != {"uri", "digest"}:
        raise ProvenanceError("invalid resolved workflow dependency")
    if dep["uri"] != f"git+{repository}@{ref}":
        raise ProvenanceError("resolved workflow dependency URI does not match workflow")
    dd = dep["digest"]
    if type(dd) is not dict or set(dd) != {"gitCommit"}:
        raise ProvenanceError("resolved workflow dependency requires gitCommit")
    _sha40(dd["gitCommit"], "resolved git commit")

    run = predicate["runDetails"]
    if type(run) is not dict or set(run) != {"builder", "metadata"}:
        raise ProvenanceError("invalid runDetails")
    builder = run["builder"]
    if type(builder) is not dict or set(builder) != {"id"}:
        raise ProvenanceError("invalid builder")
    _builder_id(builder["id"])
    metadata = run["metadata"]
    if type(metadata) is not dict or set(metadata) != {
        "invocationId",
        "startedOn",
        "finishedOn",
    }:
        raise ProvenanceError("invalid build metadata")
    _invocation_id(metadata["invocationId"], repository)
    started = _parse_timestamp(metadata["startedOn"], "startedOn")
    finished = _parse_timestamp(metadata["finishedOn"], "finishedOn")
    if finished < started:
        raise ProvenanceError("finishedOn precedes startedOn")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _regular_text(path: Path, label: str) -> str:
    try:
        meta = path.lstat()
    except OSError as exc:
        raise ProvenanceError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
        raise ProvenanceError(f"{label} must be a regular non-symlink file")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProvenanceError(f"cannot read {label} as UTF-8: {exc}") from exc


def _atomic_text(path: Path, content: str) -> None:
    parent = path.parent
    try:
        meta = parent.lstat()
    except OSError as exc:
        raise ProvenanceError(f"cannot inspect output directory: {exc}") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
        raise ProvenanceError("output parent must be a real directory")
    if path.exists() or path.is_symlink():
        current = path.lstat()
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise ProvenanceError("existing output must be a regular non-symlink file")
    temp = parent / f".{path.name}.tmp-{os.getpid()}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(content.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if fd != -1:
                os.close(fd)
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    except OSError as exc:
        raise ProvenanceError(f"cannot publish provenance atomically: {exc}") from exc


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if type(value) is not dict:
        raise ProvenanceError(f"{label} must be a plain object")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        result = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"{label} must contain canonical JSON values") from exc
    if type(result) is not dict:
        raise ProvenanceError(f"{label} must be a JSON object")
    return result


def _github_repository(value: Any) -> str:
    text = _text(value, "repository", 512)
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.params
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or parsed.path.endswith("/")
        or parsed.path.endswith(".git")
        or len([p for p in parsed.path.split("/") if p]) != 2
    ):
        raise ProvenanceError("repository must be canonical https://github.com/owner/repo")
    return text


def _ref(value: Any) -> str:
    text = _text(value, "workflow ref", 512)
    if not _REF_RE.fullmatch(text):
        raise ProvenanceError("workflow ref must be refs/heads/... or refs/tags/...")
    return text


def _workflow_path(value: Any) -> str:
    text = _text(value, "workflow path", 260)
    if not _WORKFLOW_PATH_RE.fullmatch(text):
        raise ProvenanceError("workflow path must be one file in .github/workflows")
    return text


def _builder_id(value: Any) -> str:
    text = _text(value, "builder id", 1024)
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise ProvenanceError("builder id must be an https GitHub workflow URI")
    if "/.github/workflows/" not in parsed.path or "@" not in text:
        raise ProvenanceError("builder id must identify a GitHub workflow and ref")
    return text


def _invocation_id(value: Any, repository: str) -> str:
    text = _text(value, "invocation id", 1024)
    prefix = repository + "/actions/runs/"
    if not text.startswith(prefix):
        raise ProvenanceError("invocation id must belong to the workflow repository")
    tail = text[len(prefix):]
    parts = tail.split("/")
    if len(parts) != 3 or parts[1] != "attempts":
        raise ProvenanceError("invocation id must end /actions/runs/<id>/attempts/<attempt>")
    _numeric_id(parts[0], "run id")
    _numeric_id(parts[2], "run attempt")
    return text


def _artifact_name(value: Any) -> str:
    text = _text(value, "artifact name", 512)
    if text.startswith(("/", "\\")) or "\\" in text or ".." in text.split("/"):
        raise ProvenanceError("artifact name must be a safe relative POSIX name")
    return text


def _numeric_id(value: Any, label: str) -> str:
    text = _text(value, label, 32)
    if not text.isascii() or not text.isdigit() or int(text) <= 0:
        raise ProvenanceError(f"{label} must be a positive decimal string")
    return text


def _sha40(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA40.fullmatch(value):
        raise ProvenanceError(f"{label} must be lowercase 40-hex")
    return value


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ProvenanceError(f"{label} must be lowercase 64-hex")
    return value


def _timestamp(value: datetime, label: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ProvenanceError(f"{label} must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    if utc.microsecond:
        raise ProvenanceError(f"{label} must have whole-second precision")
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if type(value) is not str:
        raise ProvenanceError(f"{label} must be text")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ProvenanceError(f"{label} must use canonical UTC format") from exc


def _text(value: Any, label: str, limit: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
    ):
        raise ProvenanceError(f"invalid {label}")
    return value


__all__ = [
    "BUILD_TYPE",
    "PREDICATE_TYPE",
    "STATEMENT_TYPE",
    "GithubWorkflowBuild",
    "ProvenanceError",
    "build_from_manifest",
    "build_provenance_statement",
    "canonical_provenance_json",
    "generate_provenance_file",
    "load_provenance_manifest",
    "provenance_sha256",
    "validate_provenance_statement",
]
