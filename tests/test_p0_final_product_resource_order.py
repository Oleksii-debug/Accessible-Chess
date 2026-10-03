from __future__ import annotations

from acs.version2_education_mutation_release import final_product_resource_sources


def test_p0_accessibility_runtime_loads_after_final_product_workspace_bootstrap() -> None:
    """The P0 runtime must discover the real V2 workspace/navigation at install time."""

    resources = final_product_resource_sources()
    labels = tuple(label for label, _source in resources)

    bootstrap_index = labels.index("V2 final-product bootstrap")
    runtime_index = labels.index("P0 accessibility runtime")

    assert bootstrap_index < runtime_index
    assert labels[runtime_index - 1] == "V2 final-product bootstrap"

    bootstrap_source = resources[bootstrap_index][1]
    runtime_source = resources[runtime_index][1]

    assert 'workspace.id = "v2-workspace"' in bootstrap_source
    assert 'nav.id = "v2-navigation"' in bootstrap_source
    assert 'documentRef.getElementById("v2-workspace")' in runtime_source
    assert 'documentRef.getElementById("v2-navigation")' in runtime_source
    assert "__accessibleChessP0AccessibilityRuntimeInstalled" in runtime_source
