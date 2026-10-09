from .main import App
from .chesscore import parse_sq


def run():
    app=App();app.withdraw();app.update()
    for s in ('f3','e5','g4','Qh4#'):
        app.move_entry.insert(0,s);app.on_move_input()
    assert app.tags.get('Result')=='0-1' and app.result_source=='checkmate'
    app.takeback(); assert app.tags.get('Result')=='*' and app.result_source is None
    app.new_game()
    for sq in ('g1','f3'):
        i=parse_sq(sq);app.board_list.selection_clear(0,'end');app.board_list.selection_set(i);app.board_list.activate(i);app.board_activate()
    assert app.sans[-1]=='Nf3'
    e4=parse_sq('e4')
    desc=app.square_description(app.board,e4)
    assert desc=='e 4', desc
    app.move_entry.insert(0,'u');app.on_move_input();assert not app.sans
    app.move_entry.insert(0,'y');app.on_move_input();assert app.sans[-1]=='Nf3'
    app.move_entry.insert(0,'w');app.on_move_input();assert app.board.turn=='w'
    app.move_entry.insert(0,'v');app.on_move_input();assert app.preserve_turn is True
    app.quick_nav('h'); assert app.heading_widgets
    app.quick_nav('b'); assert app.button_widgets
    app.quick_nav('i'); assert app.input_widgets
    latest=app.board.fen(); app.review_index=len(app.snapshots)-1
    if len(app.snapshots)>1:
        app.review_step(-1); assert app.review_index==len(app.snapshots)-2; assert app.board.fen()==latest
        app.review_step(1); assert app.review_index==len(app.snapshots)-1; assert app.board.fen()==latest
    app.engine_lines=[(20,('cp',10),['e2e4'])];app.analysis_fen=app.board.fen();app.invalidate_analysis();assert app.engine_lines==[] and app.analysis_fen is None
    app.destroy();print('STAGE1 INTERACTION SMOKE PASS')

if __name__=='__main__':run()
