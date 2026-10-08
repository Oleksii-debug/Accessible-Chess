"""Section 42: one immutable annotation projection for ordinary/teacher/online/book/media."""
from __future__ import annotations
import unittest
from acs.visual_board_contract import BoardSurface, VisualBoardCell, VisualBoardPreferences, VisualBoardSnapshot
from acs.teacher_presentation import TeacherPresentationState
from acs.teacher_webview_projection import TeacherWebViewProjection
from acs.chesscore import Board

def cells():
    return tuple(VisualBoardCell(file+rank,"",file+rank)
                 for rank in "12345678" for file in "abcdefgh")

class Section42OverlayContractTests(unittest.TestCase):
    def test_all_six_surfaces_share_visual_only_validated_shapes(self):
        self.assertEqual({x.value for x in BoardSurface},
            {"ordinary_play","teacher","online","spectator","book","media"})
        for surface in BoardSurface:
            with self.subTest(surface=surface):
                v=VisualBoardSnapshot(surface,VisualBoardPreferences(),cells(),
                    highlights=(("e4","attack","#EF5350"),),
                    arrows=(("e2","e4","idea","#ffa726"),)).as_dict()
                self.assertEqual(v["surface"],surface.value)
                self.assertEqual(v["highlights"],[{"square":"e4","purpose":"attack","color":"#ef5350"}])
                self.assertEqual(v["arrows"],[{"from":"e2","to":"e4","purpose":"idea","color":"#ffa726"}])
                self.assertEqual(len(v["cells"]),64)

    def test_refuses_spoofing_untrusted_svg_css_urls_and_duplicate_attack_squares(self):
        bad_highlights=((("z0","attack","#ff0000"),),
            (("e4","<script>","#ff0000"),),
            (("e4","attack","red;url(https://example.com)"),),
            (("e4","attack","#abcd"),),
            (("e4","attack","#ff0000"),)*65,
        )
        for bad in bad_highlights:
            with self.subTest(highlight=str(bad)[:50]):
                with self.assertRaises(ValueError):
                    VisualBoardSnapshot(BoardSurface.TEACHER,VisualBoardPreferences(),
                        cells(),highlights=bad)
        bad_arrows=((("e2","e2","idea","#ffa726"),),
            (("e2","z9","idea","#ffa726"),),
            (("e2","e4","<script>","#ffa726"),),
            (("e2","e4","idea","url(http://bad)"),),
            (("e2","e4","idea","#ffa726"),)*49,
        )
        for bad in bad_arrows:
            with self.subTest(arrow=str(bad)[:50]):
                with self.assertRaises(ValueError):
                    VisualBoardSnapshot(BoardSurface.TEACHER,VisualBoardPreferences(),
                        cells(),arrows=bad)

    def test_teacher_existing_authority_projects_same_annotated_board(self):
        state={"pointer_square":"e4",
            "highlights":({"square":"e4","purpose":"attack"},),
            "arrows":({"start_square":"e2","end_square":"e4","purpose":"idea"},),
            "coordinates_visible":True,
            "board_permission":"locked","engine_visibility":"hidden"}
        teacher=TeacherPresentationState(lambda *_args: None,lambda:state)
        board=TeacherWebViewProjection(teacher,position_fen_provider=lambda:Board().fen())
        data=board.snapshot(language="en")
        v=data["visualBoard"]
        self.assertEqual(v["surface"],"teacher")
        self.assertEqual(v["highlights"][0]["square"],"e4")
        self.assertEqual(v["highlights"][0]["purpose"],"attack")
        self.assertEqual(v["arrows"][0]["from"],"e2")
        self.assertEqual(v["arrows"][0]["to"],"e4")
        self.assertEqual(v["arrows"][0]["purpose"],"idea")
        self.assertEqual(len(v["cells"]),64)

if __name__=="__main__":
    unittest.main()
