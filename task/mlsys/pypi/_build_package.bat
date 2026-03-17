IF EXIST build rd /s /q build
IF EXIST dist rd /s /q dist
IF EXIST dist rd /s /q cmeta.egg-info

uv venv
uv pip install build
uv pip install twine

uv run python -m build
