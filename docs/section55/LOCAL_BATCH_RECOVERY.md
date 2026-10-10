# Section 55 — Bounded provisional local batch queue

**Status: PARTIAL / UNVERIFIED.** This is a local deterministic preparation queue. It is not a remote AI-agent scheduler, a PDF OCR system, an approved chess-Braille notation service, or a certified embosser. The queue itself never prints anything.

## Example queue input

Store a local UTF-8 file named queue.json with the following structure, updating absolute paths to owned books/tables. The sample is not an approval to print.

    {
      "schema_version": 1,
      "jobs": [
        {
          "id": "chess-book-01",
          "book_json": "/private/books/authorized-book.json",
          "table_file": "/private/liblouis/en-ueb-g1.ctb",
          "table_version": "locally-reviewed",
          "language": "en",
          "device_model": "UNQUALIFIED-PREVIEW",
          "cells_per_line": 32,
          "lines_per_page": 25,
          "rights_confirmed": true,
          "rights_basis": "Authorized reproduction",
          "emit_brf": true,
          "emit_html": true
        }
      ]
    }

For Markdown or TXT use source_file instead of book_json and optionally book_title. A job has one book input; both are forbidden together. All source and table paths refer to local files. The main table and every unambiguous locally included table are fingerprinted.

## Start one bounded local iteration

Ensure output root directory already exists, then run from repository root:

    python tools/section55_batch.py --queue-json /private/jobs/queue.json --output-root /private/output/section55-batch --max-per-run 1

Use --max-per-run 1 through 4. The queue allows at most 32 declared jobs per immutable revision. Each iteration prepares at most the selected number of NEW books and re-verifies existing packages. The worker saves a crash-recovery journal as:

    /private/output/section55-batch/.section55-batch-journal.json

Each book is published to a unique folder named after its safe job ID. Already-published packages are never overwritten. Journal entries record original-source, PEF, optional BRF and optional offline HTML preview digests, but not source text. The optional emit_html flag defaults to false. A generated HTML preview is reconstructed from the original source during validation and is never print-qualified.

## Recovery and refusal cases

- After a normal completion, rerunning the identical queue re-verifies all prior files, including optional BRF and live local Liblouis dependencies. It does not retranslate completed work.
- If a job was already published but the process stopped before its journal checkpoint, the next invocation independently verifies the existing files and resumes. It never blindly trusts the journal.
- A changed queue input, missing/changed original book or table, damaged package, unexpected file, or mismatched journal causes a fail-closed error. Keep the original unchanged; do not destroy an existing user package.
- Concurrent workers are refused through an exclusive lock. A crash can leave the lock file behind. For a stale lock, first verify the earlier worker has actually stopped; only then manually remove the lock file and rerun. The program does not steal another worker's lock.
- A partial output folder without a complete valid quality-report.json fails closed and requires inspection. The program does not delete a folder that may contain user work.
- The output parent must be selected in a private location. The user controls local paths and reproduction rights.

This local queue limits file and job counts, per-run work, source byte sizes and Braille cell/page budgets. It makes no external LLM requests, so a paid-model input/output token quota is not involved in this provisional implementation.

## Still open before Section 55 may be DONE

The technical queue is a small foundation for requirement 55.13. Specialist standard verification, real chess Braille and tactile notation, legal real corpus, eBraille and physical embosser validation, unrestricted large-book throughput, accessible user-facing production workflow, overall CI and product integration are still required. Every qualification output is labeled UNVERIFIED_REQUIRES_DECISION.
