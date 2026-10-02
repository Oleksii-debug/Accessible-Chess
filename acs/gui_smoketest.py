from .main import App
from .logging_setup import ROOT

def run():
    app=App(); app.withdraw(); app.update_idletasks()
    assert (ROOT/'data'/'library.acsdb').exists()
    assert len(app.heading_widgets)==10
    assert app.board_list.size()==64
    assert len(app.button_widgets)>=8
    assert len(app.input_widgets)>=8
    assert hasattr(app,'move_entry') and hasattr(app,'engine_list')
    app.destroy()
    print('GUI STARTUP SMOKE PASS')
if __name__=='__main__': run()
