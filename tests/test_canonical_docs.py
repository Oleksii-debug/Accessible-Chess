import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISION = ROOT / "docs" / "CANONICAL_PRODUCT_VISION_UA.md"
ROADMAP = ROOT / "docs" / "TECHNICAL_ROADMAP.md"
README = ROOT / "README.md"


class CanonicalDocumentationContractTests(unittest.TestCase):
    def test_issue45_canonical_documents_are_present_and_substantive(self):
        self.assertTrue(VISION.is_file())
        self.assertTrue(ROADMAP.is_file())

        vision = VISION.read_text(encoding="utf-8")
        roadmap = ROADMAP.read_text(encoding="utf-8")

        self.assertTrue(vision.startswith("ПОВНА КОНЦЕПЦІЯ ACCESSIBLE CHESS"))
        self.assertGreater(len(vision), 30_000)
        self.assertGreater(len(roadmap), 8_000)

    def test_product_vision_keeps_the_teacher_classroom_pillar(self):
        vision = VISION.read_text(encoding="utf-8")

        for requirement in (
            "TEACHER MODE.",
            "Незрячий тренер → зрячі учні.",
            "Keyboard Visual Pointer.",
            "Student hover/click → coordinate feedback through NVDA.",
            "Student pointer history.",
            "Keyboard visual arrows.",
            "Legal-move highlighting.",
            "ChessBase compatibility.",
            "Online lessons.",
            "Тільки Олексій має право сказати, що ці функції більше не потрібні.",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, vision)

    def test_roadmap_preserves_domain_boundaries_and_release_gate(self):
        roadmap = ROADMAP.read_text(encoding="utf-8")

        for invariant in (
            "one professional accessibility-first chess platform",
            "MoveCommand: `e4` means make a chess move only in Move Input mode",
            "TeacherPointerCommand: `e4` means point at square e4 only in Teacher Pointer mode",
            "AnnotationCommand: highlight/arrow/marker does not mutate Position",
            "Visual presentation is not a second source of chess truth",
            "No human-rejected ZIP is reused.",
            "`NVDA_VERIFIED=NO` until Oleksii personally tests the exact fresh candidate.",
            "Stage 1 release lineage stays narrow",
            "Teacher / Classroom mode — central product pillar",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, roadmap)

    def test_readme_links_both_canonical_documents_without_claiming_activation(self):
        readme = README.read_text(encoding="utf-8")

        self.assertIn("docs/CANONICAL_PRODUCT_VISION_UA.md", readme)
        self.assertIn("docs/TECHNICAL_ROADMAP.md", readme)
        self.assertIn("They do not activate post-Stage-1 features", readme)


if __name__ == "__main__":
    unittest.main()
