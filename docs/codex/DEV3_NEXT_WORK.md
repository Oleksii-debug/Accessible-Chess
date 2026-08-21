# AUTO-CHESS DEV3 next work

1. Re-read live PR #65 and exact head before any new edit.
2. If CI appears, inspect exact workflow/job/log result and fix root causes without weakening tests.
3. If no CI is configured for this future-work base, validate the patch in the first available repository checkout or integration runner before marking READY_FOR_INTEGRATION.
4. After paging is verified, continue the same ACSDB/Library/Search critical path with stable user-facing paging contracts: exact-position paging, provenance-aware library result surfaces, and atomic import/search behavior under large datasets.
5. Do not merge into frozen Stage1 release refs. DEV5 may integrate only after exact evidence is terminal.

Current integration readiness: `READY_FOR_INTEGRATION=NO` pending executable test/CI evidence.
