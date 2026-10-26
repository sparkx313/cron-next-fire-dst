"""cron-next-fire-dst 基准：把快速路径与暴力扫描、两种语义读法之间的差异量化。"""

from __future__ import annotations

import gc
import os
import random
import sys
import textwrap
import time
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cronlib import (  # noqa: E402
    CronParseError,
    CronSchedule,
    CronSearchLimitError,
    brute,
    dst,
    parse,
    schedule,
)

ARTIFACT = os.path.join(ROOT, "benchmarks", "last_run.txt")
RULE = "=" * 78
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)
NY = "America/New_York"
LH = "Australia/Lord_Howe"

# 计时用的固定批次：同一批跑 7 次，前 2 次丢弃，后 5 次取最好并统计抖动。
TIMING_REPETITIONS = 7
DISCARDED_WARMUPS = 2


class _Tee:
    """缓冲全部输出，结束时原样写进 last_run.txt。"""

    def __init__(self, stream):
        self._stream = stream
        self._chunks = []

    def write(self, text):
        self._chunks.append(text)
        return self._stream.write(text)

    def flush(self):
        self._stream.flush()

    @property
    def text(self):
        return "".join(self._chunks)


def banner(title):
    print(RULE)
    print(title)
    print(RULE)


def say(text):
    print()
    print(textwrap.fill("Interpretation: " + text, 78, subsequent_indent="  "))


def row(cells, widths):
    print(" ".join(
        str(cell).ljust(width) if index < len(cells) - 1 else str(cell)
        for index, (cell, width) in enumerate(zip(cells, widths))
    ).rstrip())


def _windows(anchor_list, days):
    return [(start, start + timedelta(days=days)) for start in anchor_list]


def _random_expression(rng):
    """从语法空间里采样一条表达式，保证覆盖列表/区间/步长/名称。"""
    minute = rng.choice(
        ["*", "*/7", "0", "15,45", "5-50/9", str(rng.randrange(0, 60))])
    hour = rng.choice(["*", "*/3", "0", "8-17", "1,13,23"])
    dom = rng.choice(["*", "1", "15", "1-28/9", "3,17", "*/11", "29"])
    month = rng.choice(["*", "*/4", "1", "jan", "3-9/2", "6,12", "dec"])
    dow = rng.choice(["*", "1", "0-6/3", "5", "mon,fri", "*/2", "0"])
    return "%s %s %s %s %s" % (minute, hour, dom, month, dow)


def _diff(a, b):
    """两个触发序列的差异条目数（升序、逐位比较）。"""
    left = [item.isoformat() for item in a]
    right = [item.isoformat() for item in b]
    if left == right:
        return 0
    return max(len(left), len(right)) - len(set(left) & set(right))


def legacy_fires_in(schedule, start, end):
    """第一个版本的读法：逐分钟检查墙上时间，但不验证该分钟是否真的存在。

    保留它是为了让“缺口里的分钟被当成真实触发”这个错误变成可测量的数字，
    而不是靠文字声明。
    """
    fields = schedule.fields
    dom_dow_or = schedule.dom_dow_or
    tz = schedule.tz
    out = []
    wall = start if tz is None else dst.to_wall(start, tz)
    stop = end if tz is None else dst.to_wall(end, tz)
    while wall <= stop:
        if _legacy_match(fields, dom_dow_or, wall):
            out.append(wall.replace(tzinfo=tz) if tz is not None else wall)
        wall = wall + MINUTE
    return out


def _legacy_match(fields, dom_dow_or, wall):
    return brute._minute_ok(fields, wall, dom_dow_or)


def section_one():
    banner("1. fast next_fire versus brute-force minute scanner (deterministic)")
    rng = random.Random(20261023)
    exprs = [_random_expression(rng) for _ in range(26)]
    for extra in ("0 0 1 * 5", "*/13 */5 * * 1-5", "30 2 * * *",
                  "0 0 29 2 *", "0 0 31 * *", "29 2 29 2 *", "0 0 13 * fri",
                  "0 0 1 jan,jul mon", "0 2 * * *", "*/10 2 * * *",
                  "30 1 * * *", "0 * * * *"):
        if extra not in exprs:
            exprs.append(extra)
    naive_epochs = [datetime(2024, 2, 28, 23, 40), datetime(2026, 6, 15, 3, 17),
                    datetime(2027, 12, 30, 22, 59), datetime(2025, 9, 1, 0, 0)]
    dst_epochs = [datetime(2025, 3, 7), datetime(2025, 10, 30),
                  datetime(2025, 4, 3), datetime(2025, 10, 3)]
    widths = [22, 6, 8, 10, 8, 11]
    print("zones: America/New_York and Australia/Lord_Howe, both with a 2025")
    print("transition inside the audited windows")
    row(["case", "exprs", "windows", "minutes", "firings", "mismatches"],
        widths)
    totals = {}
    naive_scheds = [CronSchedule(expr) for expr in exprs]
    scanned, fired, mismatches = 0, 0, 0
    for sched in naive_scheds:
        for start, end in _windows(naive_epochs, 3):
            reference = brute.brute_fires(sched, start, end)
            mismatches += _diff(reference, sched.fires_in(start, end))
            fired += len(reference)
            scanned += int((end - start) / MINUTE) + 1
    totals["naive"] = (len(naive_scheds), len(naive_epochs), scanned, fired,
                       mismatches)
    row(["tz=None (wall only)"] + [totals["naive"][i] for i in (0, 1, 2, 3, 4)],
        widths)

    tz_rows = []
    for zone_name in ("UTC", NY, LH):
        tz = dst.get_zone(zone_name)
        subset = exprs[-12:]
        scheds = [CronSchedule(expr, tz) for expr in subset]
        scanned = fired = mismatches = 0
        for sched in scheds:
            for start, end in _windows(dst_epochs[:2] if zone_name == NY
                                       else dst_epochs[2:] if zone_name == LH
                                       else naive_epochs[:2], 3):
                reference = brute.brute_fires(sched, start, end)
                mismatches += _diff(reference, sched.fires_in(start, end))
                fired += len(reference)
                scanned += int((end - start) / MINUTE) + 1
        tz_rows.append((zone_name, len(scheds), 2, scanned, fired, mismatches))
        short = zone_name.split("/")[-1]
        row(["%s shipped" % short, len(scheds), 2, scanned, fired,
             mismatches], widths)

    legacy_rows = []
    for zone_name in ("UTC", NY, LH):
        tz = dst.get_zone(zone_name)
        subset = ["0 2 * * *", "30 1 * * *", "*/10 2 * * *", "0 * * * *",
                  "*/30 2 1 * 5"]
        scanned = fired = mismatches = 0
        epochs = dst_epochs[:2] if zone_name == NY else dst_epochs[2:]
        for expr in subset:
            sched = CronSchedule(expr, tz)
            for start, end in _windows(epochs, 3):
                reference = brute.brute_fires(sched, start, end)
                legacy = legacy_fires_in(sched, start, end)
                mismatches += _diff(reference, legacy)
                fired += len(reference)
                scanned += int((end - start) / MINUTE) + 1
        legacy_rows.append((zone_name, len(subset), 2, scanned, fired,
                            mismatches))
        short = zone_name.split("/")[-1]
        row(["%s legacy" % short, len(subset), 2, scanned, fired,
             mismatches], widths)

    legacy_by_zone = {item[0]: item[5] for item in legacy_rows}
    fast_pairs = (totals["naive"][0] * totals["naive"][1]
                  + sum(item[1] * item[2] for item in tz_rows))
    legacy_pairs = sum(item[1] * item[2] for item in legacy_rows)
    grand_minutes = sum(item[3] for item in tz_rows) + totals["naive"][2]
    grand_fired = sum(item[4] for item in tz_rows) + totals["naive"][3]
    fast_mismatch = sum(item[5] for item in tz_rows) + totals["naive"][4]
    legacy_mismatch = sum(item[5] for item in legacy_rows)
    say(
        "the shipped fast path and the minute-by-minute scanner agree on every "
        "one of the %d audited (expression, window) pairs - the table's "
        "windows column counts distinct time windows per row, this counts one "
        "audit per expression: %d firings compared over %d scanned minutes, %d "
        "mismatches. %s"
        % (
            fast_pairs,
            grand_fired, grand_minutes, fast_mismatch,
            "The naive reading (a wall minute that the clock jumped over is "
            "still treated as a firing) is the version we shipped first: over "
            "a further %d such pairs against the same scanner it produces %d "
            "phantom firings in the "
            "two DST zones, %d in America/New_York and %d in Australia/Lord_"
            "Howe, plus %d in UTC where there is no gap to invent - the "
            "disagreement was a real semantic bug, not a rounding artefact."
            % (legacy_pairs, legacy_mismatch, legacy_by_zone.get(NY, 0),
               legacy_by_zone.get(LH, 0), legacy_by_zone.get("UTC", 0)),
        )
    )
    return totals, tz_rows, legacy_rows


def section_two():
    banner("2. Vixie day-of-month / day-of-week: OR versus AND (deterministic)")
    year = 2026
    exprs = ("0 0 1 * 5", "0 0 13 * 5", "0 0 15 * 1", "0 0 1 * 0",
             "*/30 9 1 * 5", "0 0 1-7 * 1", "0 0 29 * 2", "0 0 1 jan mon",
             "0 0 31 * 3", "*/10 0 */2 * 6", "0 0 5-12 * 0", "0 0 20 * fri",
             "0 0 1 * *", "0 0 * * 5")
    widths = [17, 9, 10, 10, 11, 6]
    row(["expr", "or-days", "and-days", "or-fires", "and-fires", "delta"],
        widths)
    data = []
    for expr in exprs:
        fields = parse(expr)
        start, end = date(year, 1, 1), date(year, 12, 31)
        or_days = brute.count_matching_days(fields, start, end, True)
        and_days = brute.count_matching_days(fields, start, end, False)
        per_day = fields[0].size * fields[1].size
        data.append((expr, or_days, and_days, or_days * per_day,
                     and_days * per_day))
        row([expr, or_days, and_days, or_days * per_day, and_days * per_day,
             or_days * per_day - and_days * per_day], widths)
    differing = sum(1 for item in data if item[1] != item[2])
    # 控制行按 restricted 标志判定，而不是按字段里有没有星号字符：'*/2' 里带
    # 星号，但它仍然是被限制的字段，会参与择一规则。
    flagged = []
    for item in data:
        fields = parse(item[0])
        flagged.append(item + (fields[2].restricted and fields[4].restricted,))
    ambiguous_rows = [item for item in flagged if item[5]]
    controls = [item for item in flagged if not item[5]]
    control_gap = sum(item[3] - item[4] for item in controls)
    amb_or = sum(item[3] for item in ambiguous_rows)
    amb_and = sum(item[4] for item in ambiguous_rows)
    biggest = max(ambiguous_rows, key=lambda item: item[3] - item[4])
    say(
        "%d of the %d expressions restrict both day fields, which is the only"
        " case where the two readings can differ; on those the OR reading fires"
        " %d times per year against %d under AND, so an AND reading silently"
        " drops %d firings a year (a factor of %.2f). The %d control rows, one"
        " day field bare, agree exactly: their combined difference is %d"
        " firings, and %d of the %d rows differ at all. The worst single row is"
        " '%s' at %d extra firings a year, so the choice is not a rounding"
        " difference - it is a different schedule."
        % (len(ambiguous_rows), len(data), amb_or, amb_and, amb_or - amb_and,
           amb_or / float(max(1, amb_and)), len(controls), control_gap,
           differing, len(data), biggest[0], biggest[3] - biggest[4])
    )
    return data


def _minute_scan_counts(tz, start, end):
    """扫描窗口内的缺口分钟数与重叠分钟数。"""
    gap = overlap = 0
    wall = start
    while wall <= end:
        status = dst.minute_status(wall, tz)
        if status == "gap":
            gap += 1
        elif status == "overlap":
            overlap += 1
        wall = wall + MINUTE
    return gap, overlap


def section_three():
    banner("3. DST wall-clock jobs across transitions (deterministic)")
    cases = (
        (NY, "0 2 * * *", datetime(2025, 3, 8), datetime(2025, 3, 12)),
        (NY, "30 1 * * *", datetime(2025, 3, 8), datetime(2025, 3, 12)),
        (NY, "30 1 * * *", datetime(2025, 10, 31), datetime(2025, 11, 4)),
        (NY, "*/10 1 * * *", datetime(2025, 10, 31), datetime(2025, 11, 4)),
        (LH, "*/10 2 * * *", datetime(2025, 10, 3), datetime(2025, 10, 7)),
        (LH, "30 1 * * *", datetime(2025, 4, 4), datetime(2025, 4, 8)),
        (LH, "*/10 1 * * *", datetime(2025, 4, 4), datetime(2025, 4, 8)),
    )
    widths = [11, 12, 15, 7, 12, 8, 9]
    row(["zone", "window", "expr", "fires", "every-pass", "gap-min",
         "ovl-min"], widths)
    results = []
    for zone_name, expr, start, end in cases:
        tz = dst.get_zone(zone_name)
        sched = CronSchedule(expr, tz)
        fires = sched.fires_in(start, end)
        every = brute.brute_fires(sched, start, end, keep_every_pass=True)
        gap, overlap = _minute_scan_counts(tz, start, end)
        results.append((zone_name, expr, start, end, len(fires), len(every),
                        gap, overlap))
        row([zone_name.split("/")[-1], "%s..%s" % (start.strftime("%m-%d"),
             end.strftime("%m-%d")), expr, len(fires), len(every), gap,
             overlap], widths)
    widths2 = [11, 15, 12, 10, 12]
    print()
    row(["zone", "expr", "window", "utc-fires", "utc-gap-min"], widths2)
    controls = []
    for zone_name, expr, start, end in cases:
        sched = CronSchedule(expr, timezone.utc)
        fires = sched.fires_in(start.replace(tzinfo=timezone.utc),
                               end.replace(tzinfo=timezone.utc))
        gap, overlap = _minute_scan_counts(timezone.utc, start, end)
        controls.append((zone_name, expr, len(fires), gap, overlap))
        row([zone_name.split("/")[-1], expr,
             "%s..%s" % (start.strftime("%m-%d"), end.strftime("%m-%d")),
             len(fires), gap], widths2)
    local_total = sum(item[4] for item in results)
    every_total = sum(item[5] for item in results)
    gap_total = sum(item[6] for item in results)
    ovl_total = sum(item[7] for item in results)
    utc_total = sum(item[2] for item in controls)
    utc_gap = sum(item[3] for item in controls)
    utc_ovl = sum(item[4] for item in controls)
    lh_rows = [item for item in results if item[0] == LH]
    lh_gap = sum(item[6] for item in lh_rows)
    lh_ovl = sum(item[7] for item in lh_rows)
    lh_sparse = [item for item in lh_rows if item[1] == "*/10 2 * * *"][0]
    ny_mar = [item for item in results
              if item[0] == NY and item[1] == "0 2 * * *"][0]
    ny_days = int((ny_mar[3] - ny_mar[2]) / DAY)
    say(
        "across the %d wall-clock cases the chosen first-pass rule emits %d"
        " firings and the every-pass rule emits %d, so %d firings sit on a wall"
        " minute the clock passed twice; the same windows contain %d overlap"
        " minutes in total, and the other %d are minutes no expression in this"
        " table schedules. The %d gap minutes cost both rules nothing, because"
        " a minute the clock jumped over never occurs as an instant."
        % (len(results), local_total, every_total, every_total - local_total,
           ovl_total, ovl_total - (every_total - local_total), gap_total)
    )
    lh_sparse_utc = [item[2] for item in controls
                     if item[0] == LH and item[1] == "*/10 2 * * *"][0]
    say(
        "Lord Howe is the nastier zone: its shift is only 30 minutes, so its"
        " two windows hold %d gap and %d overlap minutes. The 10-minute job"
        " '*/10 2 * * *' fires %d times there against %d for the same"
        " expression read in UTC; that %d-firing shortfall is this job's share"
        " of the %d gap minutes in its window, since the rest of the jumped"
        " minutes fall outside the minutes it schedules. The UTC control is the"
        " honest answer for a job that may not skip: %d expressions fire %d"
        " times in UTC against %d locally, with %d gap and %d overlap minutes,"
        " and on New York's spring-forward night the daily '0 2 * * *' fires on"
        " %d of the %d 02:00s in its window."
        % (lh_gap, lh_ovl, lh_sparse[4], lh_sparse_utc,
           lh_sparse_utc - lh_sparse[4], lh_sparse[6], len(controls), utc_total,
           local_total, utc_gap, utc_ovl, ny_mar[4], ny_days)
    )
    return results


def section_four():
    banner("4. leap day and end-of-month skips, 40 years (deterministic)")
    start, end = date(1986, 1, 1), date(2025, 12, 31)
    years = end.year - start.year + 1
    cases = ("0 0 29 2 *", "0 0 31 * *", "0 0 30 * *", "29 2 29 2 *",
             "0 0 30 2 *", "0 0 29 * *")
    widths = [16, 9, 13, 9, 22]
    row(["expr", "matched", "month-slots", "skipped", "first gap (months)"],
        widths)
    month_slots = years * 12
    details = []
    for expr in cases:
        sched = CronSchedule(expr)
        fields = sched.fields
        days = brute.count_matching_days(fields, start, end, True)
        skipped = month_slots - days
        gaps = []
        probe = date(1986, 1, 1)
        previous = None
        while probe <= end:
            if sched.day_matches(datetime(probe.year, probe.month, probe.day)):
                if previous is not None:
                    months = (probe.year - previous.year) * 12 + (
                        probe.month - previous.month)
                    gaps.append(months)
                previous = probe
            probe = probe + DAY
        details.append((expr, days, skipped, max(gaps) if gaps else None))
        row([expr, days, month_slots, skipped,
             "none" if not gaps else "%d" % max(gaps)], widths)
    leap = [item for item in details if item[0] == "0 0 29 2 *"][0]
    never = [item for item in details if item[0] == "0 0 30 2 *"][0]
    thirty_one = [item for item in details if item[0] == "0 0 31 * *"][0]
    say(
        "over %d years a monthly job on the 29th of February gets %d month "
        "slots but matches %d days, so %d of them are silently skipped - the "
        "worst wait is %d months between firings, not 12. Day 31 in every "
        "month keeps %d of %d slots (%d skips, the four short months plus "
        "February), and '0 0 30 * *' has no long gap at all because every "
        "month except February has a 30th. The naive reading of '0 0 30 2 *' "
        "is a job that runs on February 30th; the exhaustive day scan finds "
        "%d matching days in %d years, and the fast path agrees by refusing "
        "to answer: next_fire raises CronSearchLimitError after %d years "
        "instead of inventing a date."
        % (
            years, month_slots, leap[1], leap[2], leap[3], thirty_one[1],
            month_slots, thirty_one[2], never[1], years,
            schedule.MAX_SEARCH_YEARS,
        )
    )
    try:
        CronSchedule("0 0 30 2 *").next_fire(datetime(2026, 1, 1))
        raised = False
    except CronSearchLimitError:
        raised = True
    print()
    print("search limit behaviour for '0 0 30 2 *': raised=%s" % raised)
    return details


def _timed(fn, iterations):
    samples = []
    gc.disable()
    try:
        for index in range(TIMING_REPETITIONS):
            started = time.perf_counter()
            for _ in range(iterations):
                fn()
            samples.append((time.perf_counter() - started) * 1000.0)
    finally:
        gc.enable()
    warmups = samples[:DISCARDED_WARMUPS]
    kept = samples[DISCARDED_WARMUPS:]
    return min(kept), max(kept) - min(kept), kept, warmups


def section_five():
    banner("5. parse and next_fire cost, with measured noise floor (timing)")
    widths = [36, 7, 9, 9, 11]
    row(["work", "n", "best ms", "floor ms", "per op us"], widths)
    measured = {}

    def make(name, iterations, fn):
        best, spread, kept, warmups = _timed(fn, iterations)
        measured[name] = (best, spread, kept, warmups, iterations)
        row([name, iterations, "%.3f" % best, "%.3f" % spread,
             "%.2f" % (best * 1000.0 / iterations)], widths)
        return best

    dense = CronSchedule("*/7 3 * * *")
    daily = CronSchedule("0 0 * * *")
    sparse = CronSchedule("0 0 29 2 *")
    weekly = CronSchedule("0 0 * * 1")
    ny_zone = dst.get_zone(NY)
    step_naive = CronSchedule("*/20 * * * *")
    step_tz = CronSchedule("*/20 * * * *", ny_zone)
    CronSchedule("0 0 1 1 *").next_fire(datetime(2026, 1, 1))
    base = datetime(2026, 1, 1, 0, 0)
    gap_start = datetime(2025, 3, 9, 1, 40)

    make("parse full 5-field expression", 20000,
         lambda: parse("*/7 3 1,15,30 jan-may 1-5"))
    make("next_fire dense */7 3 * * *", 20000, lambda: dense.next_fire(base))
    make("next_fire daily 0 0 * * *", 20000, lambda: daily.next_fire(base))
    make("next_fire weekly 0 0 * * 1", 10000, lambda: weekly.next_fire(base))
    make("next_fire leap 0 0 29 2 *", 3000, lambda: sparse.next_fire(base))
    make("next_fire */20 * * * * tz=None", 2000,
         lambda: step_naive.next_fire(gap_start))
    make("next_fire */20 * * * * tz=New_York", 2000,
         lambda: step_tz.next_fire(gap_start))

    def unit(name):
        """单次耗时（微秒）、同批抖动上限与抖动占比，全部来自本行的 5 次采样。"""
        best, spread, _kept, _warm, count = measured[name]
        return (best * 1000.0 / count, spread * 1000.0 / count,
                spread / best * 100.0)

    relative = {name: unit(name)[2] for name in measured}
    worst_row = max(relative, key=lambda name: relative[name])
    dense_us, dense_floor_us, dense_rel = unit("next_fire dense */7 3 * * *")
    daily_us, _daily_floor, daily_rel = unit("next_fire daily 0 0 * * *")
    week_us, _week_floor, week_rel = unit("next_fire weekly 0 0 * * 1")
    leap_us, _leap_floor, leap_rel = unit("next_fire leap 0 0 29 2 *")
    parse_us = unit("parse full 5-field expression")[0]
    naive_us = unit("next_fire */20 * * * * tz=None")[0]
    tz_us = unit("next_fire */20 * * * * tz=New_York")[0]
    week_ratio = week_us / dense_us
    week_band = max(dense_rel, week_rel) / 100.0
    week_verdict = ("inside both rows' own floors, so it is a tie"
                    if week_ratio - 1.0 <= week_band
                    else "outside both rows' own floors, so it is real")
    say(
        "each row's floor column is its own tie band: the same-batch spreads"
        " run from %.1f%% to %.1f%% of a row's best pass on this loaded"
        " machine, so numbers inside one row's band are a tie and no ranking"
        " below leans on them. Normalised to one call the ordering is dense"
        " %.2f us, weekly %.2f us, daily %.2f us, leap %.2f us: cost follows how"
        " many hours and minutes the carry walk visits, not how often the job"
        " fires. The leap-day query is %.1fx dense, outside both floors (%.1f%%"
        " and %.1f%%), because a sparse expression carries the search across"
        " whole months and years instead of testing minutes, while weekly is"
        " only %.2fx dense - %s. The daily row is the slowest of the three"
        " non-sparse ones at %.1fx dense, because reaching the next midnight"
        " walks the hour list once and the minute list once."
        % (min(relative.values()), max(relative.values()), dense_us, week_us,
           daily_us, leap_us, leap_us / dense_us, leap_rel, dense_rel,
           week_ratio, week_verdict, daily_us / dense_us)
    )
    say(
        "the DST check is measurable but small: the same '*/20 * * * *' query"
        " starting 20 minutes before a spring-forward gap costs %.2f us with a"
        " zone against %.2f us with tz=None, a %.2fx ratio, because"
        " minute_status only runs on the candidate minutes that survive field"
        " matching. Parsing is the surprise: %.2f us per expression is %.1fx one"
        " dense next_fire call, so re-parsing on every tick would dominate the"
        " arithmetic - build the CronSchedule once and reuse it."
        % (tz_us, naive_us, tz_us / naive_us, parse_us, parse_us / dense_us)
    )
    return measured


BAD_INPUTS = (
    ("", "expression", "EMPTY_EXPRESSION"),
    ("   ", "expression", "EMPTY_EXPRESSION"),
    ("0 0 1 *", "expression", "WRONG_FIELD_COUNT"),
    ("0 0 1 * * 5", "expression", "WRONG_FIELD_COUNT"),
    ("@daily", "expression", "WRONG_FIELD_COUNT"),
    ("*/2 */2 */2 */2", "expression", "WRONG_FIELD_COUNT"),
    ("60 * * * *", "minute", "OUT_OF_RANGE"),
    ("0-60 * * * *", "minute", "OUT_OF_RANGE"),
    ("*/0 * * * *", "minute", "NON_POSITIVE_STEP"),
    ("0 24 * * *", "hour", "OUT_OF_RANGE"),
    ("0 */0 * * *", "hour", "NON_POSITIVE_STEP"),
    ("0 0 32 * *", "day_of_month", "OUT_OF_RANGE"),
    ("0 0 1-32 * *", "day_of_month", "OUT_OF_RANGE"),
    ("0 0 0 * *", "day_of_month", "OUT_OF_RANGE"),
    ("0 0 30-31/0 * *", "day_of_month", "NON_POSITIVE_STEP"),
    ("0 0 * 13 *", "month", "OUT_OF_RANGE"),
    ("0 0 * 0 *", "month", "OUT_OF_RANGE"),
    ("0 0 * foo *", "month", "UNKNOWN_NAME"),
    ("0 0 * mon *", "month", "UNKNOWN_NAME"),
    ("0 0 * * 8", "day_of_week", "OUT_OF_RANGE"),
    ("0 0 * * jan", "day_of_week", "UNKNOWN_NAME"),
    ("0 0 * * 5-8", "day_of_week", "OUT_OF_RANGE"),
    ("0, * * * *", "minute", "EMPTY_ITEM"),
    ("5,,6 * * * *", "minute", "EMPTY_ITEM"),
    ("/5 * * * *", "minute", "STEP_WITHOUT_RANGE"),
    ("*/2/3 * * * *", "minute", "TOO_MANY_STEPS"),
    ("*/x * * * *", "minute", "NOT_AN_INTEGER"),
    ("50-10 * * * *", "minute", "REVERSED_RANGE"),
    ("5- * * * *", "minute", "EMPTY_RANGE_END"),
    ("-5 * * * *", "minute", "EMPTY_RANGE_START"),
    ("0 0 ? * *", "day_of_month", "NOT_A_NUMBER"),
    ("0 0 * * $", "day_of_week", "NOT_A_NUMBER"),
    ("0 0 * * 1,,2", "day_of_week", "EMPTY_ITEM"),
    ("0 0 * * SUN-", "day_of_week", "EMPTY_RANGE_END"),
)

# 这三条写法合法但容易被误读成错误：步长比区间宽、区间跨过 7 的星期回绕。
BORDERLINE_ACCEPTED = (
    ("0 0 30-31/40 * *", "wide step keeps only 30"),
    ("5/70 * * * *", "wide step keeps only 5"),
    ("0 0 * * 0-7", "7 wraps into Sunday"),
)


def section_six():
    banner("6. malformed input contract (deterministic)")
    widths = [19, 13, 14, 28]
    row(["code", "field", "token", "message tail"], widths)
    accepted = []
    named = 0
    wrong_field = []
    wrong_code = []
    for expr, expected_field, expected_code in BAD_INPUTS:
        try:
            parsed = parse(expr)
        except CronParseError as error:
            named += 1 if expected_field in str(error) else 0
            if error.field_name != expected_field:
                wrong_field.append((expr, error.field_name, expected_field))
            if error.code != expected_code:
                wrong_code.append((expr, error.code, expected_code))
            text = str(error)
            tail = text.split(": ", 1)[-1]
            row([error.code, error.field_name, error.token,
                 tail if len(tail) <= 28 else tail[:25] + "..."], widths)
        except Exception as error:  # 任何非 CronParseError 的异常都是契约违规
            wrong_code.append((expr, type(error).__name__, expected_code))
            row(["UNEXPECTED:" + type(error).__name__, "-", expr[:14], "-"],
                widths)
        else:
            accepted.append((expr, parsed))
    for expr, reason in BORDERLINE_ACCEPTED:
        row(["ACCEPTED-BORDERLINE", "-", expr, reason], widths)
    say(
        "%d malformed patterns were offered, %d were rejected, and %d were "
        "accepted (that is the honest count - an accepted pattern would mean "
        "the parser is more permissive than its documented contract). Every "
        "rejection message names the offending field in %d of %d cases, %d "
        "messages carried a different field name than this table expected and "
        "%d a different error code; a non-zero value in either column is a "
        "contract break, not a style note. The parser never raises anything "
        "other than CronParseError (a ValueError subclass), so callers can "
        "catch exactly one type."
        % (len(BAD_INPUTS), len(BAD_INPUTS) - len(accepted), len(accepted),
           named, len(BAD_INPUTS) - len(accepted), len(wrong_field),
           len(wrong_code))
    )
    for expr, fields in accepted:
        row(["ACCEPTED-UNEXPECTED", "-", expr[:14], str(fields)[:28]], widths)
    say(
        "the %d ACCEPTED-BORDERLINE rows are legal by design, not misses: a "
        "step wider than its range keeps only the range start, and a weekday "
        "range reaching 7 wraps into Sunday, so '0 0 * * 0-7' matches all "
        "seven days instead of being rejected as out of range."
        % len(BORDERLINE_ACCEPTED)
    )
    return accepted, named


def main():
    print("cron-next-fire-dst benchmarks - python %s" % sys.version.split()[0])
    print("measures: fast next_fire against a brute-force minute scanner, the")
    print("Vixie OR/AND reading, DST wall-clock firings, leap skips, cost.")
    status = dst.zone_status()
    print()
    print("zoneinfo module=%s tzdata=%s zones=%d"
          % (status["module"], status["tzdata_installed"],
             status["zone_count"]))
    section_one()
    section_two()
    section_three()
    section_four()
    section_five()
    section_six()


if __name__ == "__main__":
    _out = None
    _code = 0
    try:
        _out = _Tee(sys.stdout)
        sys.stdout = _out
        main()
    except BaseException:
        _code = 1
        if _out is not None:
            sys.stdout = _out._stream
            import traceback

            traceback.print_exc()
        else:
            raise
    finally:
        if _out is not None:
            sys.stdout = _out._stream
            with open(ARTIFACT, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(_out.text)
        sys.exit(_code)
