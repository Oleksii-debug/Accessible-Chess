# DEV2 full-product snapshot record validation

Validation-only marker for exact canonical DEV2 Product head `4dd706838881c0e328c7578eada17227de43cf60`.

Validation PR: #85 (DRAFT / DO NOT MERGE).

Scope under test:
- strict closed-world GameTree snapshot record exchange;
- deterministic JSON exchange;
- duplicate-key / non-finite / malformed / oversized input rejection;
- exact schema/scalar/container boundaries;
- no mutation of caller-owned containers on failure;
- existing GameTree/PGN/core regressions.

This file is evidence-only. Do not merge this validation branch into Product or Stage1 release refs.
