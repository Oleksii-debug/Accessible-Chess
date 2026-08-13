import sys

if '--diagnostic' in sys.argv:
    from acs.selftest import run as core_run
    from acs.gui_smoketest import run as gui_run
    from acs.stage1_smoketest import run as stage1_run
    core_run(); gui_run(); stage1_run()
    print('ACCESSIBLE CHESS EXE DIAGNOSTIC PASS')
else:
    from acs.main import main
    main()
