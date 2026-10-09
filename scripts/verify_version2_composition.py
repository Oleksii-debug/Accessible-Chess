"""Lineage proof for the composed V2 branch, distinct from owner-only deltas."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OWNERS = {
    "final_formats_windows_export": "9b8b45141126a0003b765ad8837534e5b1337150",
    "pgn_save": "3647b69ec53000a90d7053b1e11a7c8fa4281df5",
    "version2_profile": "f0ea4b1cd976f9289825eb92b15253d2f142c32d",
    "book_board_adapter": "5cb51f922d2d2a3a35b3e02d3ddc0ebce9fe48e0",
    "book_core": "7407d541fefdb971fce21c3b1f02bdcc0186e970",
    "html_books": "cc949235fba8a9c3f7cb36587a52cb23eed5546d",
    "text_books": "4e88c0a0bb9b125ee57ab4bc2d667876c00ffc92",
    "import_observer": "a4963a8ae932ff0064e46a7ba27e11546dcfb1f9",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main():
    for name, sha in OWNERS.items():
        git("merge-base", "--is-ancestor", sha, "HEAD")
        print(f"OWNER_ANCESTRY_{name}=PASS")
    base = OWNERS["final_formats_windows_export"]
    git("diff", "--check", base, "HEAD")
    # Composition cannot silently introduce a competing chess/parser/storage
    # core, engine provider, unsafe upgrader or legacy packaged launcher.
    git("diff", "--exit-code", base, "HEAD", "--",
        "acs/chesscore.py", "acs/gametree.py", "acs/pgn_roundtrip.py",
        "acs/pgn_service.py", "acs/pgn_workspace.py", "acs/pgn_document.py",
        "acs/pgn_streaming_import.py", "acs/acsdb.py", "acs/library_import_service.py",
        "acs/search_service.py", "acs/chessbase_decoder.py", "acs/cbv_extractor.py",
        "acs/stockfish_runtime.py", "acs/user_data_upgrade.py", "tools/qa",
        "run_accessible_chess.py", "acs/stage1_release_ui.py",
        "acs/stage1_release_ui_core.py", "acs/webapp_keymap_core.py")
    for owner, paths in (
        ("book_core", ("acs/bookdocument.py", "acs/book_index.py")),
        ("html_books", ("acs/book_html_import.py",)),
        ("text_books", ("acs/book_text_import.py",)),
        ("book_board_adapter", ("acs/book_board_workflow.py", "acs/book_game_content.py",
                                "acs/book_library_game_lookup.py", "acs/version2_windows_book_board_adapter.py")),
        ("version2_profile", ("acs/version2_profile.py",)),
    ):
        git("diff", "--exit-code", OWNERS[owner], "HEAD", "--", *paths)
    print("V2_COMPOSED_DOMAIN_BOUNDARIES=PASS")


if __name__ == "__main__":
    main()
