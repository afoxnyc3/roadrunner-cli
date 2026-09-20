"""Build a wheel and exercise it outside the source tree without PYTHONPATH."""

import os
from pathlib import Path
import subprocess
import sys

from qualify_installed import qualify


def test_wheel_external_workflow(tmp_path):
    source = Path(__file__).resolve().parents[1]
    wheels = tmp_path / "wheels"
    build = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(wheels), str(source)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    environment = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, timeout=30)
    python = environment / "bin/python"
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--force-reinstall", str(next(wheels.glob("*.whl")))],
        env=clean_env,
        capture_output=True,
        check=True,
        timeout=30,
    )
    # Ensure an editable installation in inherited site-packages cannot mask the wheel.
    origin = subprocess.run(
        [str(python), "-c", "import roadrunner; print(roadrunner.__file__)"],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(environment) in origin.stdout
    result = qualify(environment / "bin/roadrunner", tmp_path / "demonstration")
    assert result["operator_preserved"]
    assert result["report"]["outcome"] == "finished_with_blockers"
