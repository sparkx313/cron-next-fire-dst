# cron-next-fire-dst

Cron expressions are written once and mis-read forever. This repo measures three
of those mis-readings with a stdlib-only parser and a brute-force scanner. The
shipped fast path agreed with the scanner on **0 mismatches over 967,904
audited minutes** (224 expression-window pairs) - after the first version
disagreed 13 times (8 in `America/New_York`, 5 in `Australia/Lord_Howe`, 0 in UTC).
What the data says:

- Vixie's day-of-month OR day-of-week rule is not a detail: 2084 firings a year
  over the 12 ambiguous expressions against 203 under AND (10.27x).
- A wall-clock job in a DST zone really loses runs: `0 2 * * *` fires on 3 of
  the 4 `02:00`s across the New York spring-forward night; in UTC, on all 4.
- `0 0 29 2 *` matches 10 days of 480 month slots in 40 years (worst wait 48
  months); `0 0 30 2 *` is legal syntax that matches 0 days.
- Sparseness is what you pay for: 16.2x per query, and parsing costs 3.2x a
  query - cache the schedule, not the string.

## What it does / does not do

Does: 5-field parsing (ranges, lists, steps, `*/n`, month and weekday names,
`7` = Sunday), `next_fire` / `fire_times` / `fires_in`, Vixie OR semantics for
the two day fields, DST handling through `zoneinfo` against `datetime` wall
arithmetic, an explicit `zoneinfo` availability check with a documented
fallback, and a brute-force scanner that audits the fast path.

Does not: no seconds field (6 fields are rejected, not truncated), no `@daily`
or `@reboot` macros, no `?`/`L`/`W`, no crontab file IO, no job execution, no
retry or catch-up after a missed run.

## Install

```bash
git clone <your-fork-url>/cron-next-fire-dst.git
cd cron-next-fire-dst
python -u -m unittest discover -s tests -p 'test_*.py' -t tests
```

`dependencies = []` and `requires-python >=3.9` come from `pyproject.toml`. If
the IANA database is missing (typical on Windows) install `tzdata` or use
`tz=None` mode.
## Quick start

```python
from datetime import datetime
from cronlib import CronSchedule, CronParseError, dst, parse

sched = CronSchedule("0 0 13 * 5")             # the 13th OR any Friday
print(str(sched))                              # 0 0 13 * 5
print(sched.next_fire(datetime(2026, 2, 1)))   # 2026-02-06 00:00:00
print([t.day for t in sched.fires_in(
    datetime(2026, 2, 1), datetime(2026, 3, 1))])   # [6, 13, 20, 27]

ny = dst.get_zone("America/New_York")
print(dst.minute_status(datetime(2025, 3, 9, 2, 30), ny),
      dst.minute_status(datetime(2025, 11, 2, 1, 30), ny))  # gap overlap
print([t.strftime("%m-%d %H:%M %Z") for t in
      CronSchedule("0 2 * * *", ny).fires_in(
          datetime(2025, 3, 8), datetime(2025, 3, 11))])
# ['03-08 02:00 EST', '03-10 02:00 EDT']      03-09 02:00 never existed
print([t.strftime("%m-%d %H:%M %Z") for t in
      CronSchedule("30 1 * * *", ny).fires_in(
          datetime(2025, 11, 1), datetime(2025, 11, 3))])
# ['11-01 01:30 EDT', '11-02 01:30 EDT']      the repeated hour fires once

leap = CronSchedule("0 0 29 2 *")
first = leap.next_fire(datetime(2023, 1, 1))
print(first, leap.next_fire(first), len(leap.fields))
# 2024-02-29 00:00:00 2028-02-29 00:00:00 5
try:
    parse("0 0 32 * *")
except CronParseError as error:
    print(error)
# day_of_month: value out of range 32, field day_of_month accepts 1-31 (got '32')
try:
    CronSchedule("0 0 30 2 *").next_fire(datetime(2026, 1, 1))
except Exception as error:
    print(type(error).__name__)               # CronSearchLimitError
```

The two day fields are the whole Vixie argument, and the switch is one keyword:

```python
from datetime import datetime
from cronlib import CronSchedule

or_read = CronSchedule("0 0 13 * 5")             # the 13th OR any Friday
and_read = CronSchedule("0 0 13 * 5", dom_dow_or=False)
span = (datetime(2026, 1, 1), datetime(2027, 1, 1))
print(len(or_read.fires_in(*span)), len(and_read.fires_in(*span)))
# 62 3
print([t.strftime("%m-%d") for t in and_read.fires_in(
    datetime(2026, 2, 1), datetime(2026, 3, 1))])
# ['02-13']    the AND reading keeps only Friday the 13th of the month
```

Rejections are typed and name the field that failed, which is what makes the
contract testable rather than a message-formatting exercise:

```python
from cronlib import parse, CronParseError

for bad in ("0 0 32 * *", "*/0 9 * * *", "0 0 * * 8", "0 0 1 *"):
    try:
        parse(bad)
        print("%-11s accepted" % bad)
    except CronParseError as error:
        print("%-11s %-16s %s" % (bad, error.code, error.field_name))
# 0 0 32 * *  OUT_OF_RANGE     day_of_month
# */0 9 * * * NON_POSITIVE_STEP minute
# 0 0 * * 8   OUT_OF_RANGE     day_of_week
# 0 0 1 *     WRONG_FIELD_COUNT expression
```

`minute_status` is the primitive the search leans on: it classifies a wall minute
as `ok`, `gap` (never existed) or `overlap` (happened twice), and the scheduler
skips a gap instead of emitting a firing for it.

```python
from datetime import datetime
from cronlib import CronSchedule, dst, minute_status

ny = dst.get_zone("America/New_York")
print([(d, minute_status(datetime(2025, 3, d, 2, 30), ny)) for d in (8, 9, 10)])
# [(8, 'ok'), (9, 'gap'), (10, 'ok')]
print([t.strftime("%m-%d %H:%M %Z") for t in
      CronSchedule("30 2 * * *", ny).fires_in(
          datetime(2025, 3, 7), datetime(2025, 3, 12))])
# ['03-07 02:30 EST', '03-08 02:30 EST', '03-10 02:30 EDT', '03-11 02:30 EDT']
```

## Measured results

Each block is copied line-for-line from `benchmarks/last_run.txt` (200 lines).

### 1. Fast path versus the brute-force scanner

```text
==============================================================================
zones: America/New_York and Australia/Lord_Howe, both with a 2025
transition inside the audited windows
case                   exprs  windows  minutes    firings  mismatches
tz=None (wall only)    38     4        656792     2237     0
UTC shipped            12     2        103704     327      0
New_York shipped       12     2        103704     273      0
Lord_Howe shipped      12     2        103704     275      0
UTC legacy             5      2        43210      198      0
New_York legacy        5      2        43210      192      8
Lord_Howe legacy       5      2        43210      193      5

Interpretation: the shipped fast path and the minute-by-minute scanner agree
```

All four `shipped` rows are `0`: the skipping search and the minute scanner
agreed over 3112 firings and 967,904 scanned minutes. The `legacy` rows are this
library's first version - same field matching, no DST existence check - with 8
phantom firings in New York and 5 in Lord Howe, each one a minute that does not
exist. `UTC legacy` is `0`: there the naive reading and brute force agree,
because UTC has no jumped minute to invent.

### 2. Vixie OR versus AND, firings per year (2026)

```text
==============================================================================
2. Vixie day-of-month / day-of-week: OR versus AND (deterministic)
==============================================================================
expr              or-days   and-days   or-fires   and-fires   delta
0 0 1 * 5         63        1          63         1           62
0 0 13 * 5        61        3          61         3           58
0 0 15 * 1        63        1          63         1           62
0 0 1 * 0         61        3          61         3           58
*/30 9 1 * 5      63        1          126        2           124
0 0 1-7 * 1       124       12         124        12          112
0 0 29 * 2        61        2          61         2           59
0 0 1 jan mon     5         0          5          0           5
0 0 31 * 3        59        0          59         0           59
*/10 0 */2 * 6    211       27         1266       162         1104
0 0 5-12 * 0      134       14         134        14          120
0 0 20 * fri      61        3          61         3           58
0 0 1 * *         12        12         12         12          0
0 0 * * 5         52        52         52         52          0
```

Every row restricting both day fields has a positive `delta`; the two `delta 0`
rows each leave one day field a bare `*`, so the rule's precondition is visible
instead of asserted. Worst row `*/10 0 */2 * 6`: 1266 against 162 firings a
year. `0 0 1 jan mon` and `0 0 31 * 3` show `and-days 0` - read as AND, jobs
that never run.

### 3. DST transitions, with a UTC control

```text
==============================================================================
3. DST wall-clock jobs across transitions (deterministic)
==============================================================================
zone        window       expr            fires   every-pass   gap-min  ovl-min
New_York    03-08..03-12 0 2 * * *       3       3            60       0
New_York    03-08..03-12 30 1 * * *      4       4            60       0
New_York    10-31..11-04 30 1 * * *      4       5            0        60
New_York    10-31..11-04 */10 1 * * *    24      30           0        60
Lord_Howe   10-03..10-07 */10 2 * * *    21      21           30       0
Lord_Howe   04-04..04-08 30 1 * * *      4       5            0        30
Lord_Howe   04-04..04-08 */10 1 * * *    24      27           0        30

zone        expr            window       utc-fires  utc-gap-min
New_York    0 2 * * *       03-08..03-12 4          0
New_York    30 1 * * *      03-08..03-12 4          0
New_York    30 1 * * *      10-31..11-04 4          0
New_York    */10 1 * * *    10-31..11-04 24         0
Lord_Howe   */10 2 * * *    10-03..10-07 24         0
Lord_Howe   30 1 * * *      04-04..04-08 4          0
Lord_Howe   */10 1 * * *    04-04..04-08 24         0
```

`fires` is the shipped rule (jumped minute skipped, repeated minute fires once),
`every-pass` the rejected rule, `gap-min`/`ovl-min` the scanner's counts. The
first row is a job that does not run at all on the spring-forward day: 3 local
fires against `utc-fires 4`. The overlap rows carry the rejected rule's duplicate
risk (+11 firings over the table), and Lord Howe's 30-minute shift alone costs
`*/10 2 * * *` 3 of its 24 firings. In UTC every row matches the naive
fires-every-day reading, with `utc-gap-min 0`.

### 4. Leap day and end-of-month over 40 years (1986-2025)

```text
==============================================================================
4. leap day and end-of-month skips, 40 years (deterministic)
==============================================================================
expr             matched   month-slots   skipped   first gap (months)
0 0 29 2 *       10        480           470       48
0 0 31 * *       280       480           200       2
0 0 30 * *       440       480           40        2
29 2 29 2 *      10        480           470       48
0 0 30 2 *       0         480           480       none
0 0 29 * *       450       480           30        2
```

```text
search limit behaviour for '0 0 30 2 *': raised=True
```

`month-slots` is 40 x 12, so `skipped` counts months that produced no day: 470
for February 29 (worst wait 48 months, not 12), 200 for the 31st, 40 for the
30th. `0 0 30 2 *` parses without complaint and matches 0 days in 40 years, so
the fast path raises instead of fabricating a date: "valid syntax" versus
"never fires" is a fact about cron, not about this library.

### 5. Parse and next-fire cost

```text
==============================================================================
5. parse and next_fire cost, with measured noise floor (timing)
==============================================================================
work                                 n       best ms   floor ms  per op us
parse full 5-field expression        20000   279.879   8.254     13.99
next_fire dense */7 3 * * *          20000   86.639    5.277     4.33
next_fire daily 0 0 * * *            20000   967.719   84.539    48.39
next_fire weekly 0 0 * * 1           10000   50.249    1.643     5.02
next_fire leap 0 0 29 2 *            3000    210.888   6.249     70.30
next_fire */20 * * * * tz=None       2000    24.437    0.170     12.22
next_fire */20 * * * * tz=New_York   2000    111.870   33.339    55.93
```

`floor ms` is that batch's own pass-to-pass spread (best-of-5 after 2 discarded warm-ups,
`gc.disable()`), and each comparison is judged against the wider of the two rows' bands.
This run was quiet - bands of 0.7% to 29.8% of a row's best pass - so every separation the
benchmark states survives its own floor and is reported as real: sparseness 16.2x (70.30
against 4.33 us per call), a zone 4.58x (55.93 against 12.22 us), parsing 3.2x a dense
query (13.99 us). The one genuinely small separation is `weekly` at 1.16x `dense` (5.02
against 4.33 us): outside both bands here, but only 0.69 us per call, and on a loaded
machine - the same script reaches 51.3% bands - it falls inside the floor and reads as a
tie.

### 6. Malformed input contract

```text
==============================================================================
6. malformed input contract (deterministic)
==============================================================================
code                field         token          message tail
EMPTY_EXPRESSION    expression                   expression is empty (got '')
EMPTY_EXPRESSION    expression                   expression is empty (got ...
WRONG_FIELD_COUNT   expression    0 0 1 *        expression must have exac...
WRONG_FIELD_COUNT   expression    0 0 1 * * 5    expression must have exac...
WRONG_FIELD_COUNT   expression    @daily         expression must have exac...
WRONG_FIELD_COUNT   expression    */2 */2 */2 */2 expression must have exac...
OUT_OF_RANGE        minute        60             value out of range 60, fi...
OUT_OF_RANGE        minute        60             value out of range 60, fi...
NON_POSITIVE_STEP   minute        */0            step is zero or negative:...
OUT_OF_RANGE        hour          24             value out of range 24, fi...
```

The artifact's table runs to 34 rejection rows over 13 distinct codes
(`ERROR_CODES` declares 16; `EMPTY_RANGE`, `NO_VALUES` and `BAD_TYPE` never
triggered here): all 34 patterns rejected, 0 accepted, the offending field named
in 34 of 34 messages, nothing raised but `CronParseError` (a `ValueError`). Three
final artifact rows are `ACCEPTED-BORDERLINE` - `0 0 30-31/40 * *` and `5/70 * *
* *` keep the range start when the step exceeds the range, `0 0 * * 0-7` wraps 7
into Sunday - legal by design and listed so that is checkable.

## How it decides

**Field expansion.** Each field splits on `,`; a token is `*`, `a`, `a-b`,
`a/step`, `a-b/step` or `*/step`, resolved through a name table for month and
weekday before numeric parsing, then bounded per field (`day_of_month` 1-31,
`day_of_week` 0-7). `7` wraps to `0` *after* expansion, so `5-7` becomes
`{5, 6, 0}`. Output is a `frozenset` plus a `restricted` flag, false only for a
bare `*`.

**The OR rule.** The two day fields are ORed only when both are restricted,
otherwise ANDed, ignoring the bare-star field - Vixie/cronie behaviour.
Rejected: AND everywhere, measured above as dropping 1881 of 2084 firings a year
and making `0 0 1 jan mon` never run. Consequence: `*/1` in a day field is
restricted, so it joins the OR although it matches every value.

**The DST rule.** The search runs on wall-clock minutes in the zone and
classifies candidates from PEP 495 offsets. Two traps, both found by
measurement: "the two fold offsets differ" is not a gap test (a gap differs too;
the *direction* separates them - a larger `fold=0` offset means the minute
occurs twice), and `w.replace(tzinfo=tz).astimezone(tz)` detects nothing because
CPython short-circuits conversion to the same `tzinfo` object. Shipped: gaps
skipped, overlaps firing once, results returned as zone-aware instants so a chain
cannot repeat or reverse. Rejected: every-pass firing, +11 firings on the same
windows - a backup job running twice in one night. So `0 2 * * *` in New York is
a 364-run year; if that is unacceptable, pin the schedule to UTC.

**No `zoneinfo`, or no database.** `zoneinfo_available()` checks the import;
`zone_status()` probes `UTC`, `America/New_York` and `Australia/Lord_Howe` and
reports `tzdata_installed` and `zone_count`; `get_zone()` raises
`ZoneUnavailableError` naming the fix. Fallback: `tz=None`, pure `datetime` wall
arithmetic where every minute exists - the `tz=None (wall only)` row above.

## Limitations

- 5 fields only: no seconds, no macros, no `?`/`L`/`W`.
- `MAX_SEARCH_YEARS = 8` bounds the hunt, so ultra-sparse expressions raise
  `CronSearchLimitError` instead of searching forever; 8 covers the worst real
  leap-day wait (`2096-02-29` to `2104-02-29`).
- The scanner is the slow reference: 40-year spans are counted by day, minute
  scans limited to small windows.
- Timings are one loaded machine at one moment; only ratios against `floor ms`
  are defensible.

## API

| Callable | Returns | Notes |
| --- | --- | --- |
| `parse(expression)` | `tuple[Field, ...]` | raises `CronParseError` |
| `Field.matches(v)`, `.values`, `.restricted`, `.size` | `bool`, set, `bool`, `int` | expanded field |
| `CronSchedule(expr, tz=None, dom_dow_or=True)` | schedule | `tz` = a `zoneinfo` zone |
| `.next_fire(after=None)` | `datetime` | strictly after; aware when `tz` |
| `.fire_times(after, count)` / `.fires_in(start, end)` | `list[datetime]` | chain / inclusive window |
| `.matches(wall)`, `.day_matches(wall)`, `.days_per_year(y)` | `bool`, `bool`, `int` | no DST check |
| `str(schedule)` / `.expression` | `str` | round-trips the 5 specs |
| `brute.brute_fires(s, start, end, keep_every_pass=False)` | `list[datetime]` | audit scanner |
| `brute.count_matching_minutes(s, start, end)` / `count_matching_days(f, s, e, dom_dow_or=True)` | `(int, int)` / `int` | wall and day scans |
| `dst.zoneinfo_available()` / `dst.zone_status()` | `bool` / `dict` | availability |
| `dst.get_zone(name)` / `dst.minute_status(wall, tz)` | `tzinfo` / `str` | `"ok"`, `"gap"`, `"overlap"` |

## Directory tree

```tree
cron-next-fire-dst/
|-- .gitattributes          |-- cronlib/__init__.py
|-- .gitignore              |-- cronlib/brute.py
|-- LICENSE                 |-- cronlib/dst.py
|-- README.md               |-- cronlib/field.py
|-- pyproject.toml          |-- cronlib/parse.py
|-- benchmarks/last_run.txt |-- cronlib/schedule.py
`-- benchmarks/run_benchmarks.py
                            `-- tests/test_cron.py
```

## Reproduce

```bash
cd cron-next-fire-dst
python -u -m unittest discover -s tests -p 'test_*.py' -t tests   # 82 tests, OK
python -u benchmarks/run_benchmarks.py                            # rewrites last_run.txt
```

Sections 1-4 and 6 are deterministic (fixed `random.Random` seeds, fixed dates);
section 5 re-measures, so compare ratios against its own `floor ms` column.

## License

MIT, see `LICENSE`. Copyright (c) 2026 sparkx313.
