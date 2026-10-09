"""Ask the real iTunes whether it accepts a candidate .itl (Windows, iTunes 12.13 Store build).

    python tools/itunes_probe.py CANDIDATE.itl [CANDIDATE2.itl ...] [--lib-dir DIR] [--wait 25] [--exe PATH]

iTunes reopens the library it used last, so point it at --lib-dir once by hand first
(hold Shift while starting iTunes -> "Choose Library..."). The Microsoft Store build is launched
by its AUMID; a desktop install in Program Files is preferred when present, or pass --exe.

For each candidate:
  1. close iTunes (graceful, then forced),
  2. move every *.itl in --lib-dir into out/lab/backups/<ts>/ (nothing is deleted),
  3. copy the candidate to <lib-dir>/iTunes Library.itl,
  4. launch iTunes (it reopens the library it used last, so --lib-dir must be that folder),
  5. poll: "(Damaged)" file appears -> REJECTED; otherwise iTunes touched the folder -> ACCEPTED,
  6. close iTunes, copy the folder's resulting *.itl to out/lab/results/<candidate>/.

Safety: refuses any lib-dir under ~/Music/iTunes. If nothing in lib-dir changed (iTunes may have
opened another library), iTunes is only asked to close gracefully, never force-killed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUMID = r"AppleInc.iTunes_nzyj5cx40ttqa!iTunes"  # Microsoft Store build (same on every PC)
DESKTOP_EXES = [Path(r"C:\Program Files\iTunes\iTunes.exe"),
                Path(r"C:\Program Files (x86)\iTunes\iTunes.exe")]
DEFAULT_LIB = ROOT / "out" / "validate" / "lib_fixture"
LAB = ROOT / "out" / "lab"
LIVE = Path.home() / "Music" / "iTunes"


def ps(cmd: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                       capture_output=True, text=True)
    return r.stdout.strip()


def itunes_pids() -> list[int]:
    out = ps("Get-Process iTunes -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }")
    return [int(x) for x in out.split() if x.isdigit()]


def window_titles() -> list[str]:
    out = ps("Get-Process iTunes,iTunesHelper -ErrorAction SilentlyContinue | "
             "Where-Object { $_.MainWindowTitle } | ForEach-Object { $_.MainWindowTitle }")
    return [x for x in out.splitlines() if x]


def close_itunes(force_ok: bool, timeout: float = 20) -> str:
    if not itunes_pids():
        return "not running"
    ps("Get-Process iTunes -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }")
    end = time.time() + timeout
    while time.time() < end:
        if not itunes_pids():
            return "closed gracefully"
        time.sleep(1)
    if not force_ok:
        return "STILL RUNNING (not force-killed: library in use may not be the lab one)"
    subprocess.run(["taskkill", "/IM", "iTunes.exe", "/F"], capture_output=True)
    time.sleep(2)
    return "force-killed" if not itunes_pids() else "KILL FAILED"


def snapshot(d: Path) -> dict[str, tuple[float, int]]:
    return {p.name: (p.stat().st_mtime, p.stat().st_size) for p in d.iterdir() if p.is_file()}


def launch_cmd(exe: Path | None) -> list[str]:
    exe = exe or next((p for p in DESKTOP_EXES if p.exists()), None)
    return [str(exe)] if exe else ["explorer.exe", f"shell:AppsFolder\\{AUMID}"]


def probe(candidate: Path, lib_dir: Path, wait: float, exe: Path | None = None) -> dict:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    res: dict = {"candidate": str(candidate), "time": ts}
    res["pre_close"] = close_itunes(force_ok=True)
    if itunes_pids():
        res["verdict"] = "ABORT: iTunes still running"
        return res

    backup = LAB / "backups" / ts
    backup.mkdir(parents=True, exist_ok=True)
    for p in lib_dir.glob("*.itl"):
        shutil.move(str(p), str(backup / p.name))
    target = lib_dir / "iTunes Library.itl"
    shutil.copy2(candidate, target)
    before = snapshot(lib_dir)
    t0 = time.time()

    subprocess.Popen(launch_cmd(exe))
    verdict = None
    titles: list[str] = []
    while time.time() - t0 < wait:
        time.sleep(1)
        names = [p.name for p in lib_dir.glob("*.itl")]
        if any("Damaged" in n for n in names):
            verdict = "REJECTED"
            break
    titles = window_titles()
    after = snapshot(lib_dir)
    changed = sorted(n for n in after if before.get(n) != after[n])
    touched = bool(changed) or verdict == "REJECTED"
    if verdict is None:
        verdict = "ACCEPTED" if touched and itunes_pids() else (
            "UNKNOWN (lab folder untouched - iTunes may have opened another library)")
    res.update(verdict=verdict, seconds=round(time.time() - t0, 1), windows=titles, changed=changed,
               itl_files=[p.name for p in lib_dir.glob("*.itl")])
    res["post_close"] = close_itunes(force_ok=touched)
    final = snapshot(lib_dir)
    res["changed_after_close"] = sorted(n for n in final if before.get(n) != final[n])
    if res["verdict"].startswith("UNKNOWN") and res["changed_after_close"]:
        res["verdict"] = "ACCEPTED (lab folder written on close)"

    out = LAB / "results" / f"{ts}_{candidate.stem}"
    out.mkdir(parents=True, exist_ok=True)
    for p in [*lib_dir.glob("*.itl"), *lib_dir.glob("*.xml")]:
        shutil.copy2(p, out / p.name)
    (out / "result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    res["results_dir"] = str(out)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", nargs="+", type=Path)
    ap.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB)
    ap.add_argument("--wait", type=float, default=25)
    ap.add_argument("--exe", type=Path, help="iTunes.exe (default: auto; Store build via AUMID)")
    a = ap.parse_args()
    lib_dir = a.lib_dir.resolve()
    if lib_dir == LIVE.resolve() or LIVE.resolve() in lib_dir.parents:
        print("refusing: lib-dir is the live iTunes library", file=sys.stderr)
        return 2
    if not lib_dir.is_dir():
        print(f"lib-dir not found: {lib_dir}", file=sys.stderr)
        return 2
    for c in a.candidates:
        r = probe(c.resolve(), lib_dir, a.wait, a.exe)
        print(json.dumps(r, ensure_ascii=False))
        if r["verdict"].startswith(("ABORT", "UNKNOWN")):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
