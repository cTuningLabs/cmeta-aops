import os
import platform
import sys
import struct
import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,              # cMeta context
            python_path: str = None
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if python_path and not os.path.isfile(python_path):
            return self.cm.error(f'path "{python_path}" not found')

        result = detect_python_environment(python_path)
        result['return'] = 0

        return result


def detect_python_environment(python_path = None):
    """
    Detect active Python environment across:
    - venv / virtualenv / uv
    - conda
    - poetry
    - pipenv
    - pyenv
    - system python

    Returns:
        dict with:
            type: environment type
            name: environment name
            env_path: root path of environment (or None)
            python_path: path to current python executable
            is_virtual: bool
            platform: OS name
    """

    import os
    import sys
    import platform
    from pathlib import Path

    def resolve_activate_script(env_root: Path, detected_env_type: str):
        """
        Resolve a portable activation script path for a virtual environment.
        Returns None when no known activation script is found.
        """

        if not env_root:
            return None

        env_root = Path(env_root)
        is_windows = platform.system() == "Windows"

        # Default portable activation scripts:
        # - Windows: activate.bat
        # - Linux/macOS: activate
        if is_windows:
            candidates = [
                env_root / "Scripts" / "activate.bat",
            ]
        else:
            candidates = [
                env_root / "bin" / "activate",
            ]

        # Tool-specific fallbacks where naming/location differs.
        if detected_env_type == "conda":
            if is_windows:
                candidates.extend([
                    env_root / "condabin" / "conda.bat",
                ])
            else:
                candidates.extend([
                    env_root / "condabin" / "conda",
                ])

        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()

        return None

    if python_path:
        python_path = Path(python_path)
    else:
        python_path = Path(sys.executable).resolve()

    platform_name = platform.system()

    env_type = "system"
    env_name = None
    env_path = None
    is_virtual = False

    # -------------------------------------------------
    # 1️⃣ Conda (highest priority because it sets vars)
    # -------------------------------------------------
    if "CONDA_PREFIX" in os.environ:
        env_type = "conda"
        env_path = Path(os.environ["CONDA_PREFIX"]).resolve()
        env_name = os.environ.get("CONDA_DEFAULT_ENV", env_path.name)
        is_virtual = True

    # -------------------------------------------------
    # 2️⃣ Pipenv
    # -------------------------------------------------
    elif "PIPENV_ACTIVE" in os.environ:
        env_type = "pipenv"
        env_path = Path(sys.prefix).resolve()
        env_name = env_path.name
        is_virtual = True

    # -------------------------------------------------
    # 3️⃣ Poetry
    # -------------------------------------------------
    elif "POETRY_ACTIVE" in os.environ:
        env_type = "poetry"
        env_path = Path(sys.prefix).resolve()
        env_name = env_path.name
        is_virtual = True

    # -------------------------------------------------
    # 4️⃣ pyenv (global version manager)
    # -------------------------------------------------
    elif "PYENV_VERSION" in os.environ:
        env_type = "pyenv"
        env_name = os.environ["PYENV_VERSION"]
        env_path = python_path.parent.parent
        is_virtual = True

    # -------------------------------------------------
    # 5️⃣ Standard venv / virtualenv / uv
    # -------------------------------------------------
    elif hasattr(sys, "real_prefix") or sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        env_type = "venv"
        env_path = Path(sys.prefix).resolve()
        env_name = env_path.name
        is_virtual = True

    # -------------------------------------------------
    # 6️⃣ Fallback detection from executable path
    # -------------------------------------------------
    else:
        # Sometimes tools don't expose env vars properly.
        # Detect from typical folder structure.
        if any(part in {"envs", ".venv", "venv"} for part in python_path.parts):
            env_type = "generic"
            env_path = python_path.parent.parent
            env_name = env_path.name
            is_virtual = True

    script_path = resolve_activate_script(env_path, env_type) if env_path else None

    return {
        "type": env_type,
        "name": env_name,
        "env_path": str(env_path) if env_path else None,
        "python_path": str(python_path),
        "script_path": str(script_path) if script_path else None,
        "is_virtual": is_virtual,
        "platform": platform_name,
    }

