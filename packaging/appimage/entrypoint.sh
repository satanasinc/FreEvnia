#! /bin/bash
# No arguments -> GUI; with arguments -> command line ("FreEvnia.AppImage mode pip --loc 1 ...").
if [ $# -eq 0 ]; then
    exec {{ python-executable }} -m freevnia.gui
fi
exec {{ python-executable }} -c 'import sys; from freevnia.cli import main; sys.exit(main())' "$@"
