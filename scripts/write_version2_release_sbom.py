from __future__ import annotations

"""Write and revalidate an SPDX sidecar for one canonical V2 package tree."""

import argparse
import hashlib
import json
from pathlib import Path

from acs.version2_package_preflight import validate_version2_package_tree
from acs.version2_release_sbom import (
    Version2ReleaseSbomError,
    validate_version2_release_sbom,
    write_version2_release_sbom,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a V2 package tree and write its exact SPDX 2.3 SBOM sidecar."
    )
    parser.add_argument("package_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--integration-sha", required=True)
    args = parser.parse_args()

    report = validate_version2_package_tree(
        args.package_root,
        expected_integration_sha=args.integration_sha,
    )
    target = write_version2_release_sbom(
        args.package_root,
        args.output,
        integration_sha=report.integration_sha,
        inventory=report.inventory,
    )

    # The package can change after the first canonical preflight but before the
    # SBOM hashes it. Re-run the canonical package authority before accepting
    # the sidecar, then validate the sidecar against that final validated tree.
    # This prevents a same-path payload mutation from being self-consistently
    # described by the SBOM without ever passing package checksum validation.
    final_report = validate_version2_package_tree(
        args.package_root,
        expected_integration_sha=args.integration_sha,
    )
    document = validate_version2_release_sbom(
        args.package_root,
        target,
        integration_sha=final_report.integration_sha,
        inventory=final_report.inventory,
    )
    try:
        sbom_bytes = target.read_bytes()
    except OSError as exc:
        raise Version2ReleaseSbomError(
            f"validated release SBOM cannot be read for receipt: {type(exc).__name__}"
        ) from exc
    summary = {
        "result": "PASS",
        "integration_sha": final_report.integration_sha,
        "package_files": len(final_report.inventory),
        "sbom_files": len(document["files"]),
        "sbom_path": str(target),
        "sbom_bytes": len(sbom_bytes),
        "sbom_sha256": hashlib.sha256(sbom_bytes).hexdigest(),
        "nvda_verified": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
