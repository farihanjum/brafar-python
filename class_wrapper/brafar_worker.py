"""Runs inside venv_brafar, started by run_brafar.py / class_wrapper.py once per wrong file. BRAFAR's own Searcher and
Brafar class (brafar/basic_framework/searcher.py and core.py, imported, not changed) once per try = one parameter choice.
As in core.py S_Brafar.run: for each function of the wrong program, the Searcher picks the closest program in the pool
(same loop/if order, else the closest; then the fewest token edits), that function is repaired against its pick, the
repaired functions are joined, and the patch size is the sum of BRAFAR's tree edit distances (repaired function vs the
one given to BRAFAR). A try counts as repaired only when every picked function is.
Each try is in its own try/except, so one crash does not stop the other tries.

Usage: brafar_worker.py JOBS.json POOL.json ANS_DIR OUT.jsonl
       (run with cwd = the file's runs/ folder: BRAFAR writes log.txt there)
"""
import json, os, sys
sys.path.insert(0, os.environ["BRAFAR_DIR"])
from basic_framework.core import Brafar
from basic_framework.searcher import Searcher
from basic_framework.distance import ProgramTree

jobs, pool = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
with open(sys.argv[4], "w") as out:
    for j in jobs:
        rec = dict(j)
        try:
            picks = Searcher([j["buggy"]], pool).get_program_map()[j["buggy"]]  # {function: picked pool file}
            t = ProgramTree(j["buggy"])
            rec["status"], rec["repair"], rec["patch_size"], rec["picked"] = True, "", 0, {}
            for name, cpath in picks.items():
                if cpath is None: continue  # no program in the pool has this function: S_Brafar.run skips it too
                rec["picked"][name] = os.path.basename(cpath)
                b = Brafar(j["buggy"], cpath, name, sys.argv[3], None)
                if not b.get_repair_result(): rec["status"] = False; break
                rec["repair"] += b.get_repaired_code() + "\n"
                rec["patch_size"] += t.calculate_distance_func(name, b.get_repaired_code())
            if rec["status"]: rec["rps"] = rec["patch_size"] / max(t.get_ast_size(), 1)
        except BaseException as e:
            rec["status"], rec["error"] = False, (type(e).__name__ + ": " + str(e))[:120]
        out.write(json.dumps(rec) + "\n"); out.flush()
