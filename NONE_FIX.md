# None fix

One change to BRAFAR: 3 lines in basic_framework/fault_locator.py (commit 5349096). Made on 2026-10-28 while running BRAFAR on EiPL student answers.

## The problem

While BRAFAR repairs a program, it compares the values of variables in the wrong program and in the correct program, block by block. Before comparing, it asks "does this variable exist?".

It asked that with:

    values.get(var) is None

This is True in two different cases:

| Case | What BRAFAR should think | What BRAFAR thought |
|---|---|---|
| the variable does not exist | missing | missing |
| the variable exists and its value is None | present, value None | missing (wrong) |

So in a correct program like the one below, previous looks missing at the start of the loop. BRAFAR then blames a block it has already fixed, finds it already fixed, and gives up with no repair.

    def foo(string_list):
        result = ""
        previous = None          <- BRAFAR thought this variable was missing
        for string in string_list:
            if string != previous:
                result += string
            previous = string
        return result

## The fix

Ask whether the variable is really missing:

    var not in values

| Line | What the line checks | Before | After |
|---|---|---|---|
| 586 | input values of a block: is the correct program's variable there? | if correct_in_values.get(co_var) is None: | if co_var not in correct_in_values: |
| 623 | output values of a block: is the correct program's variable there? | if correct_out_values.get(co_var) is None: | if co_var not in correct_out_values: |
| 630 | output values of a block: is the wrong program's matching variable there? | if buggy_out_values.get(b_var) is None: | if b_var not in buggy_out_values: |

After the fix, None is compared like any other value (like 0 or ""). A variable that is really missing is still treated as missing. A program with no None values gives exactly the same result as before.

## Example (real student, consecutive_dupes)

The task: remove repeats that come right after each other. The grader test foo("hello") should give "helo".

Student af520a34aee1 (wrong: keeps every letter, so foo("hello") gives "hello"):

    def foo(strings):
        result = ""
        for string in strings:
            result += string
        return result

BRAFAR picks the correct program shown above (with previous = None).

Without the fix: no repair.

With the fix: repaired (11 edits), and the repair passes all the grader tests:

    def foo(strings):
        result = ''
        previous = None
        for string in strings:
            if string != previous:
                result += string
            previous = string
        return result

## What was checked

| Check | Result |
|---|---|
| EiPL data, 5 problems, every BRAFAR try (216 tries), with vs without the fix | 212 same repair, 4 had no repair and are now repaired, 0 worse |
| Tries where a None value appears (85 of the 216) | 81 same repair, 4 now repaired; in all 4 the correct program BRAFAR picked had a None |
| Made-up class problem (Playlist, previous = None), 3 wrong answers | with the fix 3 of 3 repaired, without it 0 of 3 |

Every repair was also run on the grader tests in real Python, so a wrong repair cannot be counted as a fix.

Not checked yet: BRAFAR's own benchmark (data.zip, 1,783 wrong programs) with vs without the fix.
