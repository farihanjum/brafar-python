"""BRAFAR on the class_* problems, keeping them as classes: class -> plain functions -> BRAFAR -> back into the class.

BRAFAR deletes everything at the top level that is not a function (program_builder.py:45), so it cannot read a class.
Every answer has the same given methods (shopping_cart: __init__, add_price, total; scoreboard: __init__,
add_player); only foo is the student's. So:
    1. to_functions: every method except __init__/add_* becomes a function; self.<label> -> <label> (an extra last
       parameter, <label>_ if a method already has a parameter with that name), self.<method>(..) -> <method>(.., <label>)
       check_shape (class code that cannot be turned into working functions, or no def foo) and check_helpers (a
       method other than foo whose number of inputs no pool program has) stop an answer as "not converted", with
       the reason.
    2. BRAFAR's own pick, as in run_brafar.py: one try per parameter choice, all tries in one process
       (brafar_worker.py, a try/except per try; BRAFAR's Searcher picks the program per function). Pool, as BRAFAR's
       S_Brafar builds it: every correct attempt, converted (so it keeps the given methods, e.g. total) + reference.py
       + the wrong first attempts whose class already passes the tests, converted. Parameter choices as in
       run_brafar.py (against reference.py's foo), but the label stays last.
    3. to_class: each repair goes back into the student's class in place of the old methods
    4. each repaired CLASS is tested in real Python: obj = Cls(); obj.<label> = value; obj.foo(args);
       of those that pass, the one with the smallest patch size (BRAFAR's tree edit distance) is kept
<label> and the tests come from the grader test names, e.g. "Checking foo(50) with prices [100]".
Unlike run_class.py this also handles methods that call self.total(), so no answer is skipped.
A file with no passing repair is run up to 3 times: BRAFAR gives each test 0.01 s (fault_locator.py:16), so a slow
run can time out on a correct test and give no repair.

Usage (from eipl_pilot/brafar_pilot/):
    ../../venv/bin/python class_wrapper.py vt_class_shopping_cart
Writes data_class/<problem>/, runs_class/<problem>/<file>/ (student_class.py, one .py per try, repaired_class.py) and
brafar_class_<problem>.json. Nothing in work_class/ (CLARA's copy), brafar/ or clara/ is changed.
"""
import ast, collections, itertools, json, os, re, shutil, subprocess, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).parent
ROOT = Path("/Users/farihas_mac/Research/clara-work")
CSV = "/Users/farihas_mac/Research/EiPL data/notebooks/files/cleaned.csv"
BPY, PY = str(ROOT / "venv_brafar/bin/python"), str(ROOT / "venv/bin/python")

def tests_of(d, q):
    """"Checking foo(50) with prices [100]" -> label 'prices', [("50", "[100]"), ...]"""
    seen, label = collections.OrderedDict(), None
    for fb in d[d.Question == q].Feedback:
        try: tests = json.loads(fb)["results"]["tests"]
        except Exception: continue
        for t in tests:
            m = re.fullmatch(r"Checking foo\((.*?)\) with (\w+) (.*)", t["name"])
            if m: seen[(m[1], m[3])] = None; label = m[2]
        if seen: break
    return label, list(seen)

SHADOW = "_shadow"  # suffix for a local variable named like a method (see to_functions)

def the_class(tree):
    return next(n for n in tree.body if isinstance(n, ast.ClassDef))

def own_methods(cls):
    return [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name != "__init__" and not m.name.startswith("add_")]

def state_name(cls, label):
    """label, or label_ when a method already has a parameter with that name (as run_class.py does)."""
    clash = any(label in [a.arg for a in m.args.args[1:]] for m in own_methods(cls))
    return label + "_" if clash else label

def check_shape(tree):
    """Stop (ValueError -> "not converted") on class code that to_functions would turn into broken functions without
    saying so. None of the 144 class answers in cleaned.csv (2026-11-03) has any of these."""
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if len(classes) != 1: raise ValueError("more than one class" if classes else "no class")
    docstring = lambda n: isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    if any(n is not classes[0] and not docstring(n) for n in tree.body): raise ValueError("code outside the class")
    foos = [m for m in own_methods(classes[0]) if m.name == "foo"]
    if len(foos) != 1: raise ValueError("foo defined more than once" if foos else "no def foo in the class")
    for m in own_methods(classes[0]):
        a = m.args
        if m.decorator_list: raise ValueError(f"decorated method {m.name}")
        if a.defaults or a.kw_defaults or a.vararg or a.kwarg or a.kwonlyargs or a.posonlyargs:
            raise ValueError(f"default values or *args in {m.name}")
        if not a.args or a.args[0].arg != "self": raise ValueError(f"first parameter of {m.name} is not self")
        attr_selfs = {id(x.value) for x in ast.walk(m) if isinstance(x, ast.Attribute)}
        if any(isinstance(x, ast.Name) and x.id == "self" and id(x) not in attr_selfs for x in ast.walk(m)):
            raise ValueError(f"uses self directly in {m.name}")

def to_functions(code, label):
    tree = ast.parse(code); check_shape(tree)
    cls = the_class(tree)
    methods = own_methods(cls)
    names = {m.name for m in methods}
    var = state_name(cls, label)
    class Flatten(ast.NodeTransformer):
        def visit_Call(self, n):                      # self.total(x) -> total(x, prices)
            f = n.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self" and f.attr in names:
                n = ast.copy_location(ast.Call(func=ast.Name(f.attr, ast.Load()), args=n.args + [ast.Name(var, ast.Load())],
                                               keywords=n.keywords), n)
            self.generic_visit(n)
            return n
        def visit_Attribute(self, n):                 # self.prices -> prices
            self.generic_visit(n)
            if isinstance(n.value, ast.Name) and n.value.id == "self":
                if n.attr != label: raise ValueError(f"uses self.{n.attr}")
                return ast.copy_location(ast.Name(var, n.ctx), n)
            return n
    class Unshadow(ast.NodeTransformer):           # total = self.total() -> total_shadow = total(prices), else the
        def visit_Name(self, n):                      # local total hides the function total (UnboundLocalError)
            if n.id in names: n.id += SHADOW
            return n
    out = []
    for m in methods:
        m.args.args = m.args.args[1:] + [ast.arg(var)]
        m.args.defaults = []
        out.append(ast.unparse(ast.fix_missing_locations(Flatten().visit(Unshadow().visit(m)))))
    return "\n\n".join(out) + "\n"

def to_class(student_code, repaired, label):
    """Put the repaired functions back into the student's class, as methods."""
    tree = ast.parse(student_code); cls = the_class(tree)
    var = state_name(cls, label)
    methods = {m.name for m in own_methods(cls)}
    funcs = {f.name: f for f in ast.parse(repaired).body if isinstance(f, ast.FunctionDef)}
    class Back(ast.NodeTransformer):
        def visit_Call(self, n):                      # total(x, prices) -> self.total(x)
            if isinstance(n.func, ast.Name) and n.func.id in funcs:  # drop the label argument before prices -> self.prices
                args = [a for a in n.args if not (isinstance(a, ast.Name) and a.id == var)]
                n = ast.copy_location(ast.Call(func=ast.Attribute(ast.Name("self", ast.Load()), n.func.id, ast.Load()),
                                               args=args, keywords=n.keywords), n)
            self.generic_visit(n)
            return n
        def visit_Name(self, n):                      # prices -> self.prices; total_shadow -> total
            if n.id == var: return ast.copy_location(ast.Attribute(ast.Name("self", ast.Load()), label, n.ctx), n)
            if n.id.endswith(SHADOW) and n.id[:-len(SHADOW)] in methods: n.id = n.id[:-len(SHADOW)]
            return n
    for i, m in enumerate(cls.body):
        if isinstance(m, ast.FunctionDef) and m.name in funcs:
            f = funcs[m.name]
            f.args.args = [ast.arg("self")] + [a for a in f.args.args if a.arg != var]
            cls.body[i] = Back().visit(f)
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"

def foo_def(tree):
    return next(f for f in tree.body if isinstance(f, ast.FunctionDef) and f.name == "foo")

def pool_programs(data, passing):
    """BRAFAR's own pool (core.py S_Brafar): converted correct files + reference.py + converted wrong files that pass."""
    correct = sorted((data / "code/correct").glob("*.py"))
    pool = correct + [data / "code/reference/reference.py"] + [data / "code/wrong" / f"{a}.py" for a in passing]
    return pool, f"{len(correct)} correct + reference + {len(passing)} wrong that pass the tests"

def input_counts(paths):
    """{function name: every number of inputs it has in these programs} (as in run_brafar.py)."""
    counts = collections.defaultdict(set)
    for p in paths:
        for n in ast.parse(Path(p).read_text()).body:
            if isinstance(n, ast.FunctionDef): counts[n.name].add(len(n.args.args))
    return counts

def check_helpers(funcs, pool_inputs):
    """Stop (ValueError -> "not converted") on a method other than foo whose number of inputs no pool program's
    method of that name has: BRAFAR would crash or give no repair, as the input-count step only changes foo
    (as check_inputs in run_brafar.py). None of the 27 wrong class answers (2026-11-03) has one."""
    for f in ast.parse(funcs).body:
        if f.name != "foo" and f.name in pool_inputs and len(f.args.args) not in pool_inputs[f.name]:
            raise ValueError(f"method {f.name} has {len(f.args.args) - 1} input(s) besides self; "
                             f"no pool program's {f.name} has that many")

def param_options(src, params):
    """run_brafar.py's param_options for foo, but the label parameter stays last and is never removed."""
    sp = [a.arg for a in foo_def(ast.parse(src)).args.args]
    if len(sp) == len(params): return [("same", src)]
    own, n, opts = sp[:-1], len(params) - 1, []
    if len(own) > n:
        for keep in itertools.combinations(range(len(own)), n):
            tree = ast.parse(src); f = foo_def(tree)
            f.body = [ast.parse(f"{own[i]} = None").body[0] for i in range(len(own)) if i not in keep] + f.body
            f.args.args = [f.args.args[i] for i in keep] + [f.args.args[-1]]
            opts.append(("keep " + ", ".join(own[i] for i in keep), ast.unparse(tree) + "\n"))
    else:
        f = foo_def(ast.parse(src))
        used = {x.id for x in ast.walk(f) if isinstance(x, ast.Name)} | set(sp)
        for pos in itertools.combinations(range(n), len(own)):
            new = [x if x not in used else x + "_param" for x in params[:-1]]
            for i, j in enumerate(pos): new[j] = own[i]
            tree = ast.parse(src); f = foo_def(tree)
            f.args.args = [ast.arg(x) for x in new] + [f.args.args[-1]]
            opts.append(("params " + ", ".join(new + [sp[-1]]), ast.unparse(tree) + "\n"))
    return opts

CLASS_TEST = r'''
import json, sys
ns = {}
exec(open(sys.argv[1]).read(), ns)
Cls = next(v for k, v in ns.items() if isinstance(v, type))
out = []
for args, state, exp in json.loads(sys.argv[2]):
    try:
        obj = Cls(); setattr(obj, sys.argv[3], eval(state)); got = eval("obj.foo(%s)" % args, {"obj": obj})
        out.append([args, state, repr(got), exp, got == eval(exp)])
    except Exception as e: out.append([args, state, type(e).__name__ + ": " + str(e)[:60], exp, False])
print(json.dumps(out))
'''

def class_tests(path, tests, label):
    """[args, state, got, expected, pass] per test. When the class cannot be run at all (does not parse, no class,
    over 30 s), every test fails with the reason, instead of the whole run stopping."""
    try:
        p = subprocess.run([PY, "-I", "-c", CLASS_TEST, str(path), json.dumps(tests), label], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return [[a, s, "RUN ERROR: over 30 s", x, False] for a, s, x in tests]
    try: return json.loads(p.stdout)
    except ValueError:
        why = (p.stderr.strip().splitlines() or ["no output"])[-1][:60]
        return [[a, s, "RUN ERROR: " + why, x, False] for a, s, x in tests]

if __name__ == "__main__":
    short = sys.argv[1]; q = "eipl/" + short
    d = pd.read_csv(CSV, parse_dates=["Submission date"]).sort_values("Submission date", kind="stable")
    d["attempt"] = d.groupby(["anon_id", "Question"]).cumcount() + 1
    label, raw = tests_of(d, q)
    data = HERE / "data_class" / short; shutil.rmtree(data, ignore_errors=True)
    for sub in ("ans", "code/correct", "code/reference", "code/wrong"): (data / sub).mkdir(parents=True)
    pool = d[(d.Question == q) & d.Correct]
    wrong = d[(d.Question == q) & ~d.Correct & (d.attempt == 1)]
    bad = collections.Counter()
    for _, r in pool.iterrows():
        try: (data / "code/correct" / f"{r.anon_id}_a{r.attempt}.py").write_text(to_functions(r.derived_gpt_code, label))
        except Exception as e: bad["correct: " + str(e)] += 1
    # expected answers: run one correct CLASS answer; reference = its function form
    ref_row = pool.iloc[0]
    tmp = data / "reference_class.py"; tmp.write_text(ref_row.derived_gpt_code)
    exp = [x[2] for x in class_tests(tmp, [[a, s, "None"] for a, s in raw], label)]
    tests = [[a, s, e] for (a, s), e in zip(raw, exp)]
    shutil.copy(data / "code/correct" / f"{ref_row.anon_id}_a{ref_row.attempt}.py", data / "code/reference/reference.py")
    for i, (a, s, e) in enumerate(tests, 1):
        (data / "ans" / f"input_{i:03d}.txt").write_text("foo(%s)\n" % ", ".join(x for x in (a, s) if x))
        (data / "ans" / f"output_{i:03d}.txt").write_text(e + "\n")
    print(f"{short}: label {label}, {len(pool)} correct ({len(list((data / 'code/correct').iterdir()))} converted), {len(wrong)} wrong")
    for k, n in bad.items(): print("   not converted x%d: %s" % (n, k))
    for t in tests: print("   foo(%s) with %s %s -> %s" % (t[0], label, t[1], t[2]))

    passing = []  # wrong first attempts whose class already passes; converted ones go to code/wrong/
    chk = data / "check_class.py"
    for _, r in wrong.iterrows():
        chk.write_text(r.derived_gpt_code)
        try: (data / "code/wrong" / f"{r.anon_id}.py").write_text(to_functions(r.derived_gpt_code, label))
        except Exception: continue
        if all(t[4] for t in class_tests(chk, tests, label)): passing.append(r.anon_id)
    pool, kind = pool_programs(data, passing)
    pool_inputs = input_counts(pool)
    print(f"   pool = {kind}")
    runs = HERE / "runs_class" / short; shutil.rmtree(runs, ignore_errors=True); runs.mkdir(parents=True)
    pool_json = runs / "pool.json"; pool_json.write_text(json.dumps([str(p) for p in pool]))
    rparams = [x.arg for x in foo_def(ast.parse((data / "code/reference/reference.py").read_text())).args.args]
    summary, recs = collections.Counter(), []
    def note(a, kind, orig_ok, **more):
        """kind: not converted / no repair / no change (code already passes) / fixed"""
        summary[kind] += 1; recs.append(dict(file=a, kind=kind, orig_passes=orig_ok, **more))
        print(f"== {a}: {kind}" + (f" ({more['error']})" if "error" in more else ""))
    for _, r in wrong.iterrows():
        a = r.anon_id; sq = runs / a; sq.mkdir(parents=True)
        orig = sq / "student_class.py"; orig.write_text(r.derived_gpt_code)
        orig_ok = all(t[4] for t in class_tests(orig, tests, label))
        try: funcs = to_functions(r.derived_gpt_code, label); check_helpers(funcs, pool_inputs)
        except Exception as e:
            note(a, "not converted", orig_ok, error=str(e)); continue
        jobs = []
        for k, (plabel, src) in enumerate(param_options(funcs, rparams)):
            b = sq / f"choice_{k}.py"; b.write_text(src)
            jobs.append({"choice": k, "params": plabel, "buggy": str(b)})
        (sq / "jobs.json").write_text(json.dumps(jobs))
        for runs_n in (1, 2, 3):  # a slow run can hit BRAFAR's 0.01 s test limit and give no repair: run again
            try:
                subprocess.run([BPY, str(HERE / "brafar_worker.py"), str(sq / "jobs.json"), str(pool_json), str(data / "ans"),
                                str(sq / "out.jsonl")],
                               cwd=sq, capture_output=True, text=True, timeout=900, env={**os.environ, "BRAFAR_DIR": str(ROOT / "brafar")})
            except subprocess.TimeoutExpired:
                pass
            outs = [json.loads(l) for l in open(sq / "out.jsonl")] if (sq / "out.jsonl").exists() else []
            for t in outs:  # every repair BRAFAR reports goes back into the class and is tested as a class
                if t.get("status") and t.get("repair"):
                    back = Path(t["buggy"]).with_suffix(".repaired_class.py")
                    back.write_text(to_class(r.derived_gpt_code, t["repair"], label))
                    t["class_ok"] = all(x[4] for x in class_tests(back, tests, label))
            ok = [t for t in outs if t.get("class_ok")]
            if ok: break
        more = dict(tries=len(jobs), runs=runs_n, ran=len(outs), crashed=sum("error" in t for t in outs), repaired=len(ok))
        if not ok: note(a, "no change" if orig_ok else "no repair", orig_ok, **more); continue
        best = min(ok, key=lambda t: (t["patch_size"], t["choice"]))
        back = sq / "repaired_class.py"; back.write_text(Path(best["buggy"]).with_suffix(".repaired_class.py").read_text())
        note(a, "no change" if orig_ok else "fixed", orig_ok, **more, pname=Path(best["picked"].get("foo", "")).stem,
             picked=best["picked"], params=best["params"], patch_size=best["patch_size"], rps=best["rps"],
             repaired_class=back.read_text())
    json.dump(recs, open(HERE / f"brafar_class_{short}.json", "w"), indent=1)
    print(dict(summary))
