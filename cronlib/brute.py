"""暴力参考扫描器：逐分钟枚举，用来审计快速路径的跳位逻辑。"""

from __future__ import annotations

from datetime import datetime

from . import dst
__all__ = ["brute_fires", "count_matching_minutes", "count_matching_days"]


def _day_ok(fields, wall, dom_dow_or):
    """独立实现一次匹配判断：审计基准必须能自己给出结论，而不是转调快速路径。"""
    _minute, _hour, dom, month, dow = fields
    if wall.month not in month.values:
        return False
    dom_ok = wall.day in dom.values
    dow_ok = (wall.isoweekday() % 7) in dow.values
    if dom_dow_or and dom.restricted and dow.restricted:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def _minute_ok(fields, wall, dom_dow_or):
    minute, hour, _dom, _month, _dow = fields
    return (
        wall.minute in minute.values
        and wall.hour in hour.values
        and _day_ok(fields, wall, dom_dow_or)
    )


def brute_fires(schedule, start, end, keep_every_pass=False):
    """逐分钟扫描 ``[start, end]``，返回触发时刻列表。

    带时区时按**绝对瞬间**逐分钟推进，因此缺口里的墙上分钟天然不会出现；重叠区
    的同一墙上分钟只保留最早的那个瞬间——这正是 ``next_fire`` 采用的“第一次经过”
    规则，``keep_every_pass=True`` 则改用“每次经过都触发”的另一种规则。
    """
    fields = schedule.fields
    dom_dow_or = schedule.dom_dow_or
    tz = schedule.tz
    out = []
    if tz is None:
        wall = dst.to_wall(start, None).replace(second=0, microsecond=0)
        stop = dst.to_wall(end, None).replace(second=0, microsecond=0)
        while wall <= stop:
            if _minute_ok(fields, wall, dom_dow_or):
                out.append(wall)
            wall = wall + dst.MINUTE
        return out

    first = dst.earliest_instant(dst.to_wall(start, tz), tz).astimezone(dst.UTC)
    end_wall = dst.to_wall(end, tz).replace(second=0, microsecond=0)
    # 游标必须贴在 UTC 上推进：给带 ZoneInfo 的瞬间加 timedelta 走的是墙上时间，
    # 那样拨慢后重复出现的分钟根本不会被第二次访问。
    instant = first
    seen = set()
    while True:
        wall = instant.astimezone(tz)
        key = wall.replace(tzinfo=None, second=0, microsecond=0)
        # 以墙上分钟为界收尾，避免上界偏移贴歪导致多扫或漏扫。
        if key > end_wall:
            break
        if key not in seen:
            seen.add(key)
            if _minute_ok(fields, key, dom_dow_or):
                out.append(wall)
        elif keep_every_pass and _minute_ok(fields, key, dom_dow_or):
            out.append(wall)
        instant = instant + dst.MINUTE
    return out


def count_matching_minutes(schedule, start, end):
    """暴力扫描 ``[start, end]`` 的分钟数与其中触发的分钟数。"""
    total = 0
    hits = 0
    fields = schedule.fields
    dom_dow_or = schedule.dom_dow_or
    wall = start.replace(second=0, microsecond=0)
    stop = end.replace(second=0, microsecond=0)
    while wall <= stop:
        total += 1
        if _minute_ok(fields, wall, dom_dow_or):
            hits += 1
        wall = wall + dst.MINUTE
    return total, hits


def count_matching_days(fields, start_date, end_date, dom_dow_or=True):
    """按天扫描日期区间，返回“月 + 日 + 星期”匹配的天数。"""
    hits = 0
    probe = start_date
    while probe <= end_date:
        if _day_ok(fields, datetime(probe.year, probe.month, probe.day),
                   dom_dow_or):
            hits += 1
        probe = probe + dst.DAY
    return hits
