# V6 exact-head CI dispatch regression

The V6 heavy runner must not wait for a recursive push-triggered Windows workflow after a github-actions[bot] checkpoint commit.

Required mechanism:
- verify `worddeck-bootstrap` live HEAD equals the checkpoint SHA;
- explicitly dispatch `.github/workflows/worddeck-windows.yml` on `worddeck-bootstrap`;
- accept only a `workflow_dispatch` run whose `head_sha` equals the checkpoint SHA and whose `head_branch` is `worddeck-bootstrap`;
- decode the full job log and reject hidden traceback/native-command failures;
- require at least eight nonexpired exact-run artifacts before marking the orchestration checkpoint CI_GREEN.

`run_oxford5000_v6_completion.py --self-test-dispatch` verifies that the V6 runner contains the explicit-dispatch contract and contains no push-only lookup.
