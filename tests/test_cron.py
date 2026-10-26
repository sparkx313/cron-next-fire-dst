"""cronlib 的单元测试：字段语法、Vixie 择一语义、DST、闰日与解析契约。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from cronlib import (
    CronParseError,
    CronSchedule,
    CronSearchLimitError,
    brute,
    dst,
    parse,
)

NY = "America/New_York"
LH = "Australia/Lord_Howe"
# 2 月没有第 30 天：合法语法、永不触发，用来测试搜索上限。
NEVER = "0 0 30 2 *"


def _zone(name):
    """取时区，缺 IANA 数据库时跳过该用例而不是失败。"""
    try:
        return dst.get_zone(name)
    except dst.ZoneUnavailableError:
        raise unittest.SkipTest("zoneinfo tzdata unavailable for %s" % name)


class FieldSyntaxTests(unittest.TestCase):
    def test_minute_star_covers_whole_field(self):
        fields = parse("0 * * * *")
        self.assertEqual(fields[1].size, 24)
        self.assertFalse(fields[1].restricted)

    def test_minute_range(self):
        fields = parse("5-8 * * * *")
        self.assertEqual(fields[0].sorted_values(), [5, 6, 7, 8])

    def test_minute_list(self):
        fields = parse("0,15,30,45 * * * *")
        self.assertEqual(fields[0].sorted_values(), [0, 15, 30, 45])

    def test_minute_step_on_star(self):
        fields = parse("*/15 * * * *")
        self.assertEqual(fields[0].sorted_values(), [0, 15, 30, 45])
        self.assertTrue(fields[0].restricted)

    def test_minute_range_with_step(self):
        fields = parse("5-50/9 * * * *")
        self.assertEqual(fields[0].sorted_values(), [5, 14, 23, 32, 41, 50])

    def test_single_value_with_step_runs_to_max(self):
        fields = parse("5/10 * * * *")
        self.assertEqual(fields[0].sorted_values(), [5, 15, 25, 35, 45, 55])

    def test_hour_range_and_list(self):
        fields = parse("0 8-17 * * *")
        self.assertEqual(fields[1].sorted_values(), list(range(8, 18)))
        fields = parse("0 1,13,23 * * *")
        self.assertEqual(fields[1].sorted_values(), [1, 13, 23])

    def test_hour_step_is_bounded_field(self):
        fields = parse("0 */5 * * *")
        self.assertEqual(fields[1].sorted_values(), [0, 5, 10, 15, 20])

    def test_day_of_month_range_with_step(self):
        fields = parse("0 0 1-28/9 * *")
        self.assertEqual(fields[2].sorted_values(), [1, 10, 19, 28])

    def test_day_of_month_star_step(self):
        fields = parse("0 0 */11 * *")
        self.assertEqual(fields[2].sorted_values(), [1, 12, 23])

    def test_day_of_month_list(self):
        fields = parse("0 0 1,last * *".replace("last", "31"))
        self.assertEqual(fields[2].sorted_values(), [1, 31])

    def test_month_range(self):
        fields = parse("0 0 * 3-9 *")
        self.assertEqual(fields[3].sorted_values(), [3, 4, 5, 6, 7, 8, 9])

    def test_month_names_abbreviated(self):
        fields = parse("0 0 * jan,dec *")
        self.assertEqual(fields[3].sorted_values(), [1, 12])

    def test_month_names_full_and_mixed_case(self):
        fields = parse("0 0 * January,Feb *")
        self.assertEqual(fields[3].sorted_values(), [1, 2])

    def test_month_name_range(self):
        fields = parse("0 0 * mar-may *")
        self.assertEqual(fields[3].sorted_values(), [3, 4, 5])

    def test_month_star_step(self):
        fields = parse("0 0 * */4 *")
        self.assertEqual(fields[3].sorted_values(), [1, 5, 9])

    def test_day_of_week_names(self):
        fields = parse("0 0 * * mon,fri")
        self.assertEqual(fields[4].sorted_values(), [1, 5])

    def test_day_of_week_seven_is_sunday(self):
        fields = parse("0 0 * * 7")
        self.assertEqual(fields[4].sorted_values(), [0])

    def test_day_of_week_wrapping_range(self):
        fields = parse("0 0 * * 5-7")
        self.assertEqual(fields[4].sorted_values(), [0, 5, 6])

    def test_day_of_week_star_step(self):
        fields = parse("0 0 * * */3")
        self.assertEqual(fields[4].sorted_values(), [0, 3, 6])

    def test_lists_of_ranges_and_steps_mixed(self):
        fields = parse("1-3,50,*/20 0 1,15-16 1-6/2 0,6")
        self.assertEqual(fields[0].sorted_values(), [0, 1, 2, 3, 20, 40, 50])
        self.assertEqual(fields[2].sorted_values(), [1, 15, 16])
        self.assertEqual(fields[3].sorted_values(), [1, 3, 5])
        self.assertEqual(fields[4].sorted_values(), [0, 6])

    def test_extra_whitespace_is_tolerated(self):
        fields = parse("  0   0   1   *    *  ")
        self.assertEqual([f.spec for f in fields], ["0", "0", "1", "*", "*"])

    def test_star_slash_one_counts_as_restricted(self):
        # */1 覆盖整个值域，但写法上作者确实限制了字段，Vixie 仍按择一处理。
        fields = parse("*/1 */1 1-15 * *")
        self.assertTrue(fields[0].restricted)
        self.assertTrue(fields[1].restricted)
        self.assertTrue(fields[2].restricted)
        self.assertFalse(fields[4].restricted)


class RoundTripTests(unittest.TestCase):
    def test_expression_round_trips(self):
        for expr in (
            "*/15 0 1,15 * 1-5",
            "30 2 29 2 *",
            "5 4 * * sat",
            "0 0 1 jan,jul mon",
        ):
            self.assertEqual(str(CronSchedule(expr)), expr)

    def test_normalized_whitespace_round_trips(self):
        self.assertEqual(str(CronSchedule(" 0\t0   1 * * ")), "0 0 1 * *")

    def test_field_str_keeps_original_token(self):
        fields = parse("0 0 * * fri,mon")
        self.assertEqual(str(fields[4]), "fri,mon")
        self.assertEqual(fields[4].sorted_values(), [1, 5])

    def test_days_per_year_counts_matches(self):
        self.assertEqual(CronSchedule("0 0 29 2 *").days_per_year(2024), 1)
        self.assertEqual(CronSchedule("0 0 29 2 *").days_per_year(2025), 0)


class ParseContractTests(unittest.TestCase):
    def test_rejects_four_fields(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 1 *")
        self.assertEqual(ctx.exception.code, "WRONG_FIELD_COUNT")

    def test_rejects_six_field_seconds_form(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 0 1 * *")
        self.assertIn("seconds", str(ctx.exception))

    def test_rejects_empty_expression(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("   ")
        self.assertEqual(ctx.exception.code, "EMPTY_EXPRESSION")

    def test_rejects_non_string(self):
        with self.assertRaises(CronParseError):
            parse(None)

    def test_minute_out_of_range(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("60 * * * *")
        self.assertEqual(ctx.exception.field_name, "minute")
        self.assertEqual(ctx.exception.code, "OUT_OF_RANGE")

    def test_hour_out_of_range(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 24 * * *")
        self.assertEqual(ctx.exception.field_name, "hour")

    def test_day_of_month_zero_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 0 * *")
        self.assertEqual(ctx.exception.field_name, "day_of_month")
        self.assertIn("day_of_month", str(ctx.exception))

    def test_day_of_month_32_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 32 * *")
        self.assertEqual(ctx.exception.code, "OUT_OF_RANGE")

    def test_month_13_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 * 13 *")
        self.assertEqual(ctx.exception.field_name, "month")

    def test_day_of_week_8_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 * * 8")
        self.assertEqual(ctx.exception.field_name, "day_of_week")

    def test_reversed_range_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("50-10 * * * *")
        self.assertEqual(ctx.exception.code, "REVERSED_RANGE")

    def test_trailing_comma_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0, * * * *")
        self.assertEqual(ctx.exception.code, "EMPTY_ITEM")

    def test_zero_step_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("*/0 * * * *")
        self.assertEqual(ctx.exception.code, "NON_POSITIVE_STEP")

    def test_bare_step_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("/5 * * * *")
        self.assertEqual(ctx.exception.code, "STEP_WITHOUT_RANGE")

    def test_double_step_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("*/2/3 * * * *")
        self.assertEqual(ctx.exception.code, "TOO_MANY_STEPS")

    def test_non_numeric_step_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("*/x * * * *")
        self.assertEqual(ctx.exception.code, "NOT_AN_INTEGER")

    def test_unknown_name_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 * foo *")
        self.assertEqual(ctx.exception.code, "UNKNOWN_NAME")

    def test_weekday_name_in_month_field_rejected(self):
        with self.assertRaises(CronParseError) as ctx:
            parse("0 0 * mon *")
        self.assertEqual(ctx.exception.code, "UNKNOWN_NAME")

    def test_symbol_garbage_rejected(self):
        for expr in ("@daily * * * *", "0 0 * * $", "0 0 ? * *", "0 0 * * -5"):
            with self.assertRaises(CronParseError, msg=expr):
                parse(expr)

    def test_every_error_message_names_a_field(self):
        bad = (
            "", "0 0 1 *", "60 * * * *", "0 24 * * *", "0 0 0 * *",
            "0 0 * 13 *", "0 0 * * 8", "50-10 * * * *", "0, * * * *",
            "*/0 * * * *", "/5 * * * *", "*/2/3 * * * *", "0 0 * foo *",
        )
        for expr in bad:
            with self.assertRaises(CronParseError) as ctx:
                parse(expr)
            self.assertTrue(any(
                name in str(ctx.exception)
                for name in ("expression", "minute", "hour", "day_of_month",
                             "month", "day_of_week")
            ), expr)


class NextFireTests(unittest.TestCase):
    def test_next_minute_rollover(self):
        sched = CronSchedule("*/15 * * * *")
        self.assertEqual(sched.next_fire(datetime(2026, 1, 1, 9, 3)),
                         datetime(2026, 1, 1, 9, 15))

    def test_strictly_after_never_returns_start(self):
        sched = CronSchedule("0 * * * *")
        self.assertEqual(sched.next_fire(datetime(2026, 1, 1, 9, 0)),
                         datetime(2026, 1, 1, 10, 0))

    def test_chain_is_strictly_increasing(self):
        sched = CronSchedule("17,43 */5 * * *")
        cursor = datetime(2026, 3, 14, 7, 1)
        seen = []
        for _ in range(60):
            cursor = sched.next_fire(cursor)
            seen.append(cursor)
        self.assertTrue(all(b > a for a, b in zip(seen, seen[1:])))

    def test_wraps_over_short_months(self):
        sched = CronSchedule("0 0 31 * *")
        got = sched.next_fire(datetime(2026, 1, 31, 0, 0))
        self.assertEqual(got, datetime(2026, 3, 31, 0, 0))

    def test_fire_times_count_and_spacing(self):
        sched = CronSchedule("30 2 * * *")
        times = sched.fire_times(datetime(2026, 1, 1, 0, 0), 5)
        self.assertEqual(len(times), 5)
        self.assertTrue(all(b - a == timedelta(days=1)
                            for a, b in zip(times, times[1:])))

    def test_fires_in_is_inclusive_on_both_ends(self):
        sched = CronSchedule("0 * * * *")
        got = sched.fires_in(datetime(2026, 1, 1, 5, 0), datetime(2026, 1, 1, 8, 0))
        self.assertEqual([t.hour for t in got], [5, 6, 7, 8])

    def test_fires_in_empty_window(self):
        sched = CronSchedule("0 0 1 1 *")
        self.assertEqual(
            sched.fires_in(datetime(2026, 6, 1), datetime(2026, 6, 30)), [])

    def test_fires_in_reversed_window(self):
        sched = CronSchedule("0 * * * *")
        self.assertEqual(
            sched.fires_in(datetime(2026, 1, 5), datetime(2026, 1, 1)), [])

    def test_search_limit_raises_for_never_expression(self):
        sched = CronSchedule(NEVER)
        with self.assertRaises(CronSearchLimitError):
            sched.next_fire(datetime(2026, 1, 1))

    def test_next_fire_defaults_to_now(self):
        got = CronSchedule("* * * * *").next_fire()
        self.assertGreater(got, datetime.now() - timedelta(minutes=2))

    def test_sparse_expression_leap_chain(self):
        sched = CronSchedule("0 0 29 2 *")
        first = sched.next_fire(datetime(2023, 1, 1))
        second = sched.next_fire(first)
        self.assertEqual(first, datetime(2024, 2, 29, 0, 0))
        self.assertEqual(second, datetime(2028, 2, 29, 0, 0))


class VixieOrSemanticsTests(unittest.TestCase):
    def test_ambiguous_expression_uses_or(self):
        sched = CronSchedule("0 0 13 * 5")
        got = sched.fires_in(datetime(2026, 2, 1), datetime(2026, 3, 1))
        self.assertEqual(sorted(t.day for t in got), [6, 13, 20, 27])

    def test_and_reading_is_a_subset(self):
        sched_or = CronSchedule("0 0 13 * 5")
        sched_and = CronSchedule("0 0 13 * 5", dom_dow_or=False)
        or_days = {t.day for t in sched_or.fires_in(
            datetime(2026, 2, 1), datetime(2026, 3, 1))}
        and_days = {t.day for t in sched_and.fires_in(
            datetime(2026, 2, 1), datetime(2026, 3, 1))}
        self.assertTrue(and_days < or_days)
        self.assertEqual(and_days, {13})

    def test_day_of_week_star_makes_dom_effective(self):
        sched = CronSchedule("0 0 1 * *")
        self.assertEqual(sched.day_matches(datetime(2026, 4, 1)), True)
        self.assertEqual(sched.day_matches(datetime(2026, 4, 2)), False)

    def test_day_of_month_star_makes_dow_effective(self):
        sched = CronSchedule("0 0 * * 1")
        self.assertEqual(sched.day_matches(datetime(2026, 4, 6)), True)
        self.assertEqual(sched.day_matches(datetime(2026, 4, 7)), False)

    def test_sunday_agrees_for_zero_and_seven(self):
        a = CronSchedule("0 0 * * 0")
        b = CronSchedule("0 0 * * 7")
        start = datetime(2026, 5, 1)
        self.assertEqual(a.fires_in(start, start + timedelta(days=30)),
                         b.fires_in(start, start + timedelta(days=30)))

    def test_or_rule_needs_both_fields_restricted(self):
        # 一侧是 */1 时按 AND 处理，因此 1 号且周五的日期才触发。
        sched = CronSchedule("0 0 1 */1 *")
        self.assertTrue(sched.day_matches(datetime(2026, 1, 1)))


class DstTests(unittest.TestCase):
    def test_zone_status_reports_probe(self):
        status = dst.zone_status()
        self.assertTrue(status["module"])
        self.assertIn(NY, status["zones"])

    def test_ny_spring_forward_minute_is_gap(self):
        tz = _zone(NY)
        self.assertEqual(dst.minute_status(datetime(2025, 3, 9, 2, 30), tz),
                         "gap")
        self.assertEqual(dst.minute_status(datetime(2025, 3, 9, 1, 30), tz),
                         "ok")

    def test_ny_daily_two_am_job_skips_one_day(self):
        tz = _zone(NY)
        sched = CronSchedule("0 2 * * *", tz)
        got = sched.fires_in(datetime(2025, 3, 7), datetime(2025, 3, 12))
        self.assertEqual(len(got), 4)
        self.assertEqual([t.day for t in got], [7, 8, 10, 11])

    def test_ny_two_am_never_fires_at_instant_between_one_and_three(self):
        tz = _zone(NY)
        sched = CronSchedule("0 2 * * *", tz)
        after = sched.next_fire(datetime(2025, 3, 9, 1, 0))
        self.assertEqual(after.day, 10)

    def test_ny_fall_back_wall_job_fires_once(self):
        tz = _zone(NY)
        sched = CronSchedule("30 1 * * *", tz)
        got = sched.fires_in(datetime(2025, 11, 1), datetime(2025, 11, 4))
        self.assertEqual(len(got), 3)
        nov2 = [t for t in got if t.day == 2]
        self.assertEqual(len(nov2), 1)
        self.assertEqual(nov2[0].utcoffset(), timedelta(hours=-4))

    def test_ny_overlap_fires_twice_when_rule_keeps_every_pass(self):
        tz = _zone(NY)
        sched = CronSchedule("30 1 * * *", tz)
        every = brute.brute_fires(sched, datetime(2025, 11, 2),
                                  datetime(2025, 11, 2, 3), keep_every_pass=True)
        self.assertEqual(len(every), 2)
        self.assertEqual({t.utcoffset() for t in every},
                         {timedelta(hours=-4), timedelta(hours=-5)})

    def test_ny_hourly_instants_are_minute_spaced_across_gap(self):
        tz = _zone(NY)
        sched = CronSchedule("0 * * * *", tz)
        got = sched.fires_in(datetime(2025, 3, 9, 0), datetime(2025, 3, 9, 5))
        self.assertEqual(len(got), 5)
        utc = [t.astimezone(timezone.utc) for t in got]
        self.assertTrue(all((b - a) == timedelta(minutes=60)
                            for a, b in zip(utc, utc[1:])))
        # 墙上小时跳过了 2 点：01:00 之后直接是 03:00。
        self.assertEqual([t.hour for t in got], [0, 1, 3, 4, 5])

    def test_utc_control_loses_nothing(self):
        sched = CronSchedule("0 2 * * *", timezone.utc)
        got = sched.fires_in(datetime(2025, 3, 7, tzinfo=timezone.utc),
                             datetime(2025, 3, 11, tzinfo=timezone.utc))
        self.assertEqual(len(got), 4)
        self.assertEqual([t.day for t in got], [7, 8, 9, 10])

    def test_lord_howe_thirty_minute_gap(self):
        tz = _zone(LH)
        sched = CronSchedule("*/10 2 * * *", tz)
        got = sched.fires_in(datetime(2025, 10, 5), datetime(2025, 10, 5, 3))
        self.assertEqual(sorted(t.minute for t in got), [30, 40, 50])

    def test_lord_howe_overlap_minute_fires_once(self):
        tz = _zone(LH)
        # 主探针显示 Lord Howe 的拨慢是 02:00(+11:00) -> 01:30(+10:30)，
        # 所以被重复的是 01:30-01:59，而不是 02:30。
        sched = CronSchedule("30 1 * * *", tz)
        got = sched.fires_in(datetime(2025, 4, 5), datetime(2025, 4, 8))
        self.assertEqual([t.day for t in got], [5, 6, 7])
        apr6 = [t for t in got if t.day == 6][0]
        self.assertEqual(apr6.utcoffset(), timedelta(hours=11))
        every = brute.brute_fires(sched, datetime(2025, 4, 6),
                                  datetime(2025, 4, 6, 3), keep_every_pass=True)
        self.assertEqual(len(every), 2)
        self.assertEqual({t.utcoffset() for t in every},
                         {timedelta(hours=11), timedelta(hours=10, minutes=30)})

    def test_aware_after_is_accepted(self):
        tz = _zone(NY)
        sched = CronSchedule("0 * * * *", tz)
        naive = sched.next_fire(datetime(2025, 3, 9, 1, 30))
        aware = sched.next_fire(datetime(2025, 3, 9, 1, 30, tzinfo=tz))
        self.assertEqual(naive.astimezone(timezone.utc),
                         aware.astimezone(timezone.utc))

    def test_aware_input_rejected_in_naive_mode(self):
        sched = CronSchedule("0 * * * *")
        with self.assertRaises(dst.ZoneUnavailableError):
            sched.next_fire(datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_chain_across_transition_is_monotonic_in_utc(self):
        tz = _zone(NY)
        sched = CronSchedule("*/20 * * * *", tz)
        cursor = datetime(2025, 3, 9, 0, 0)
        previous = None
        for _ in range(20):
            cursor = sched.next_fire(cursor)
            instant = cursor.astimezone(timezone.utc)
            if previous is not None:
                self.assertGreater(instant, previous)
            previous = instant


class BruteForceAuditTests(unittest.TestCase):
    def _assert_paths_agree(self, sched, start, end):
        reference = brute.brute_fires(sched, start, end)
        fast = sched.fires_in(start, end)
        self.assertEqual([t.isoformat() for t in reference],
                         [t.isoformat() for t in fast],
                         "%s %s..%s" % (sched.expression, start, end))
        return len(reference)

    def test_naive_windows_match(self):
        total = 0
        for expr in ("*/13 * * * *", "0 0 13 * 5", "30 2 29 2 *", "0 0 * * 1",
                     "5-50/9 1,13 1-28/3 jan,dec 0-7/2"):
            start = datetime(2025, 6, 10, 3, 17)
            total += self._assert_paths_agree(
                CronSchedule(expr), start, start + timedelta(days=5))
        self.assertGreater(total, 0)

    def test_dst_windows_match(self):
        for zone in (NY, LH):
            tz = _zone(zone)
            for anchor in (datetime(2025, 3, 8), datetime(2025, 11, 1)):
                for expr in ("0 2 * * *", "30 1 * * *", "*/10 2 * * *"):
                    sched = CronSchedule(expr, tz)
                    self._assert_paths_agree(
                        sched, anchor, anchor + timedelta(days=4))

    def test_brute_counts_minutes_scanned(self):
        sched = CronSchedule("*/5 * * * *")
        total, hits = brute.count_matching_minutes(
            sched, datetime(2026, 1, 1), datetime(2026, 1, 1, 1, 0))
        self.assertEqual(total, 61)
        self.assertEqual(hits, 13)

    def test_brute_day_counts_for_or_and_and(self):
        fields = parse("0 0 13 * 5")
        start, end = date(2026, 1, 1), date(2026, 12, 31)
        or_days = brute.count_matching_days(fields, start, end, True)
        and_days = brute.count_matching_days(fields, start, end, False)
        # 期望值用独立的 date 迭代复算，而不是写死一个凭印象的数字。
        probe = start
        union = set()
        both = set()
        while probe <= end:
            if probe.day == 13:
                union.add(probe)
                if probe.weekday() == 4:
                    both.add(probe)
            if probe.weekday() == 4:
                union.add(probe)
            probe = probe + timedelta(days=1)
        self.assertEqual(or_days, len(union))
        self.assertEqual(and_days, len(both))
        self.assertGreater(or_days, and_days)

    def test_next_fire_matches_brute_step_by_step(self):
        sched = CronSchedule("17 3 * * mon")
        reference = brute.brute_fires(sched, datetime(2026, 4, 1),
                                      datetime(2026, 6, 1))
        chained = sched.fire_times(datetime(2026, 3, 31), len(reference))
        self.assertEqual([t.isoformat() for t in chained],
                         [t.isoformat() for t in reference])


if __name__ == "__main__":
    unittest.main()
