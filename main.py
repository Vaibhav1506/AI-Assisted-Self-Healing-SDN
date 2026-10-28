"""Start the SDN demonstration directly with sudo python3 main.py."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def main():
    python = ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        print("The project Python environment is missing: .venv/bin/python", file=sys.stderr)
        return 1
    if Path(sys.prefix).resolve() != python.parent.parent.resolve():
        os.execv(str(python), [str(python), str(ROOT / "main.py"), *sys.argv[1:]])
    os.chdir(ROOT)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / "src"))
    runtime = ROOT / ".runtime"
    (runtime / "tmp").mkdir(parents=True, exist_ok=True)
    os.environ.update(TMPDIR=str(runtime / "tmp"), XDG_CACHE_HOME=str(runtime / "cache"),
                      LC_ALL="C", OPENBLAS_NUM_THREADS="2", OMP_NUM_THREADS="2")
    from selfheal.cli import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
