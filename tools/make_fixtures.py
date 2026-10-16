"""Generate the synthetic runtime-state schema examples without reading live records.

The default installs the declared paths. --out emits the flat verification copy
expected by fleet-guards tools/data_boundary.py.
"""
import argparse
from pathlib import Path

FILES = {
    "escalation_state.json.example": "{}\n",
    "escalation_state.json.lock.example": "escalation dispatch in progress\n",
    "escalation_state.json.tmp.example": "{}\n",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    for name, content in FILES.items():
        target = args.out / Path(name).name if args.out else Path(__file__).resolve().parents[1] / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
