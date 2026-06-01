@echo off
rem After uv sync, if .venv\pyvenv.cfg is missing, generate it pointing to Python 3.13
if not exist ".venv\pyvenv.cfg" (
    echo home = C:\Users\User\AppData\Local\Programs\Python\Python313 > .venv\pyvenv.cfg
    echo include-system-site-packages = false >> .venv\pyvenv.cfg
    echo version = 3.13.13 >> .venv\pyvenv.cfg
    echo Created .venv\pyvenv.cfg
) else (
    echo .venv\pyvenv.cfg already exists.
)
