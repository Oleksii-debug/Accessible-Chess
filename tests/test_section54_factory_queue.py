from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from acs.format_factory_policy import FactoryJobPolicy, FactorySelection
from acs.format_factory_queue import FactoryJobQueue, FactoryQueueError


def policy(source: str = "a") -> FactoryJobPolicy:
    return FactoryJobPolicy(source_sha256=sha256(source.encode()).hexdigest(),
                            source_id="book-1", selection=FactorySelection("all"),
                            output_formats=("txt",), output_language="uk")


class FactoryQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name).joinpath("factory.sqlite"))
        self.q = FactoryJobQueue(self.db)

    def test_durable_submission_recovery_and_stale_worker_fencing(self) -> None:
        q = self.q
        initial = q.submit("job-1", policy(), now=100)
        self.assertEqual(initial.state, "WAITING")
        leased = q.acquire(now=100, lease_seconds=10)
        self.assertIsNotNone(leased)
        self.assertEqual(leased.attempts, 1)
        self.assertEqual(FactoryJobQueue(self.db).snapshot("job-1").state, "RUNNING")
        self.assertIsNone(q.acquire(now=105))
        replacement = FactoryJobQueue(self.db).acquire(now=111)
        self.assertEqual(replacement.attempts, 2)
        with self.assertRaises(FactoryQueueError):
            q.heartbeat(leased, now=112)
        refreshed = q.heartbeat(replacement, now=112, lease_seconds=30)
        self.assertEqual(refreshed.deadline, 142)

    def test_concurrent_acquire_never_duplicates_active_job(self) -> None:
        self.q.submit("job-1", policy(), now=100)
        with ThreadPoolExecutor(max_workers=8) as workers:
            leases = list(workers.map(lambda _: FactoryJobQueue(self.db).acquire(now=101), range(8)))
        self.assertEqual(sum(item is not None for item in leases), 1)

    def test_idempotent_and_conflicting_policy_submission(self) -> None:
        a = self.q.submit("job-1", policy(), now=10)
        b = self.q.submit("job-1", policy(), now=11)
        self.assertEqual(a, b)
        with self.assertRaises(FactoryQueueError):
            self.q.submit("job-1", policy("different"), now=12)

    def test_fragment_checkpoint_idempotent_source_fenced_and_restart(self) -> None:
        p = policy()
        self.q.submit("job-1", p, now=10)
        lease = self.q.acquire(now=11)
        assert lease is not None
        digest = sha256(b"output").hexdigest()
        self.assertTrue(self.q.acknowledge_fragment(lease, "chapter1", source_sha256=p.source_sha256,
                         result_sha256=digest, verified=True, now=12))
        self.assertFalse(FactoryJobQueue(self.db).acknowledge_fragment(lease, "chapter1",
                         source_sha256=p.source_sha256, result_sha256=digest, verified=True, now=13))
        with self.assertRaises(FactoryQueueError):
            self.q.acknowledge_fragment(lease, "chapter1", source_sha256=p.source_sha256,
                                        result_sha256=sha256(b"drift").hexdigest(), verified=True, now=14)
        with self.assertRaises(FactoryQueueError):
            self.q.acknowledge_fragment(lease, "new", source_sha256=sha256(b"wrong").hexdigest(),
                                        result_sha256=digest, verified=True, now=15)
        self.assertEqual(FactoryJobQueue(self.db).snapshot("job-1").verified_fragment_count, 1)

    def test_done_requires_all_fragments_verified_and_coverage_attested(self) -> None:
        p = policy()
        self.q.submit("job-1", p, now=1)
        lease = self.q.acquire(now=2)
        assert lease is not None
        artifact = sha256(b"artifact").hexdigest()
        with self.assertRaises(FactoryQueueError):
            self.q.transition(lease, now=3, target="DONE", artifact_sha256=artifact, coverage_verified=True)
        self.q.acknowledge_fragment(lease, "page", source_sha256=p.source_sha256,
                                    result_sha256=artifact, verified=True, now=4)
        with self.assertRaises(FactoryQueueError):
            self.q.transition(lease, now=5, target="DONE", artifact_sha256=artifact)
        result = self.q.transition(lease, now=6, target="DONE", artifact_sha256=artifact,
                                    coverage_verified=True)
        self.assertEqual(result.state, "DONE")
        self.assertIsNone(FactoryJobQueue(self.db).acquire(now=7))

    def test_priority_selection_and_requeue(self) -> None:
        self.q.submit("low", policy("a"), now=2, priority=0)
        self.q.submit("high", policy("b"), now=3, priority=10)
        lease = self.q.acquire(now=4)
        assert lease is not None
        self.assertEqual(lease.job_id, "high")
        self.q.transition(lease, now=5, target="PAUSED")
        self.assertEqual(self.q.acquire(now=6).job_id, "low")

    def test_invalid_data_does_not_mutate_active_job(self) -> None:
        self.q.submit("job-1", policy(), now=20)
        lease = self.q.acquire(now=21)
        assert lease is not None
        with self.assertRaises(FactoryQueueError):
            self.q.transition(lease, now=22, target="DONE", artifact_sha256="wrong", coverage_verified=True)
        with self.assertRaises(FactoryQueueError):
            self.q.heartbeat(lease, now=9999999)
        self.assertEqual(self.q.snapshot("job-1").state, "RUNNING")


if __name__ == "__main__":
    unittest.main()
