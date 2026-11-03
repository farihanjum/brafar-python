# Class wrapper

Lets BRAFAR repair answers written as a class. Made on 2026-11-02 for the EiPL class problems (shopping_cart, scoreboard, grade_tracker). BRAFAR's own code is not changed: these scripts only call it.

| File | What it does |
|---|---|
| class_wrapper.py | turns the class into functions, runs BRAFAR, puts the repair back into the class, tests the class |
| brafar_worker.py | runs BRAFAR (its own Searcher and Brafar classes, imported) on one wrong file, once per input choice |

These are copies. The copies that are run live in the local project folder eipl_pilot/brafar_pilot/ (not on GitHub); copy them here again after a change.

## The problem

BRAFAR only reads plain functions. It deletes everything else at the top level of a file, classes too (basic_framework/program_builder.py, line 45). So a class answer reaches BRAFAR as an empty program.

## What the wrapper does

Example (made up, in the shape of the shopping_cart answers). The student's class:

    class ShoppingCart:
        def __init__(self):
            self.prices = []
        def add_price(self, price):
            self.prices.append(price)
        def total(self):
            return sum(self.prices)
        def foo(self, discount):
            total = self.total()
            if total > discount:
                return total - discount
            return 0

Step 1. Turn the class into functions (to_functions). __init__ and add_* are left out; every other method becomes a plain function:

    def total(prices):
        return sum(prices)

    def foo(discount, prices):
        total_shadow = total(prices)
        if total_shadow > discount:
            return total_shadow - discount
        return 0

| In the class | As a function | Why |
|---|---|---|
| self.prices | prices, an extra last input | a function has no self |
| self.total() | total(prices) | the method becomes a function and needs the list |
| total = self.total() | total_shadow = total(prices) | a variable named like a method would hide the function (UnboundLocalError), so it is renamed |

The name prices (the "label") comes from the grader's test names, e.g. "Checking foo(50) with prices [100]".

Step 2. Run BRAFAR on the functions, the same way as for the other problems: BRAFAR's own Searcher picks the correct program to repair from, one try per input choice (when the student's foo has a different number of inputs than the reference), and the smallest repair that passes is kept. The pool is every correct answer (also turned into functions) + the reference + the wrong answers that already pass.

Step 3. Put the repaired functions back into the student's class (to_class): prices becomes self.prices again, total(prices) becomes self.total(), total_shadow becomes total. __init__ and add_* stay as the student wrote them.

Step 4. Test the repaired class in real Python on the grader tests:

    obj = ShoppingCart()
    obj.prices = [100]
    obj.foo(50)          -> must give the same answer as a correct class

A repair counts only if the class passes every test. A file with no passing repair is run up to 3 times, because BRAFAR gives each test only 0.01 seconds (fault_locator.py, line 16) and a slow run can fail a correct test.

## What it does not convert

Class code that would turn into broken functions is stopped with "not converted" and the reason, instead of giving BRAFAR wrong code:

| Pattern | Reason shown |
|---|---|
| another attribute, e.g. self.count | uses self.count |
| a method used without calling it, e.g. f = self.total | uses self.total |
| more than one class in the file | more than one class |
| a helper function, import or variable outside the class | code outside the class |
| a method with a decorator (@staticmethod, @property) | decorated method |
| a method with default values, *args or **kwargs | default values or *args |
| a method whose first input is not named self | first parameter is not self |
| self used on its own, e.g. vars(self) | uses self directly |
| no class in the file | no class |
| no def foo in the class (also foo = lambda ...) | no def foo in the class |
| foo defined twice in the class | foo defined more than once |
| a method other than foo whose number of inputs no correct answer's method of that name has, e.g. total(self, tax) | method total has 1 input(s) besides self; no pool program's total has that many |
| code that does not parse | invalid syntax (<unknown>, line N) |

None of the 144 EiPL class answers has any of these. One bad answer never stops the whole run: a class that does not parse, has no class, or runs over 30 seconds fails its class tests with "RUN ERROR" and the reason, and the run goes on to the next answer.

## Known limits

| Limit | What happens | Seen in EiPL data? |
|---|---|---|
| test names worded differently from "Checking foo(...) with <label> <value>" | tests are not found; if only some are worded differently, those are dropped without a message | no: all 15 test names match |
| __init__ that needs inputs, e.g. def __init__(self, owner) | the class test calls ShoppingCart() with no inputs, so every test fails, even after a right repair | no |
| a bug inside __init__ or add_* | never repaired, and not seen by the test (it sets obj.prices directly) | no: every answer has the same, correct __init__ and add_* |

## Results on EiPL (2026-11-03)

| Problem | Correct answers converted | Wrong first attempts | Already pass | Really wrong | Fixed |
|---|---|---|---|---|---|
| grade_tracker | 26 of 26 | 0 | 0 | 0 | 0 |
| scoreboard | 40 of 40 | 17 | 1 | 16 | 16 |
| shopping_cart | 36 of 36 | 10 | 4 | 6 | 6 |

## How to run

Paths in class_wrapper.py are set for the author's machine (ROOT, CSV, the two Python environments BPY and PY); change them first. brafar_worker.py runs with BPY and finds BRAFAR's code through the BRAFAR_DIR setting, which class_wrapper.py sets to ROOT/brafar.

    python class_wrapper.py vt_class_shopping_cart

It writes data_class/<problem>/, runs_class/<problem>/ and brafar_class_<problem>.json next to the script. These hold student answers and are not committed (see .gitignore).
