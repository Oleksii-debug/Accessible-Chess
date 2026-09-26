from __future__ import annotations

"""Write and revalidate an SPDX sidecar for one canonical V2 package tree."""

import argparse
import json
from pathlib import Path

from acs.version2_package_preflight import validate_version2_package_tree
from acs.version2_release_sbom import (
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
    document = validate_version2_release_sbom(
        args.package_root,
        target,
        integration_sha=report.integration_sha,
        inventory=report.inventory,
    )
    summary = {
        "result": "PASS",
        "integration_sha": report.integration_sha,
        "package_files": len(report.inventory),
        "sbom_files": len(document["files"]),
        "sbom_path": str(target),
        "nvda_verified": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
