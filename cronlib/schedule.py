"""触发时刻计算：按墙上时间跳位搜索的快速路径。"""

from __future__ import annotations

import calendar
from datetime import datetime

from . import dst
from .parse import parse

# 搜索上限按年计：2 月 29 日在最坏情况下要跨 8 年（2096 -> 2104 的世纪年规则），
# 再小就会把合法表达式误判成永不触发。
MAX_SEARCH_YEARS = 8


class CronSearchLimitError(RuntimeError):
    """在 ``MAX_SEARCH_YEARS`` 年内没有找到触发时刻。"""


def _start_of_next_day(wall):
    return datetime(wall.year, wall.month, wall.day) + dst.DAY


def _start_of_next_month(wall):
    if wall.month == 12:
        return datetime(wall.year + 1, 1, 1)
    return datetime(wall.year, wall.month + 1, 1)


class CronSchedule:
    """一条 cron 表达式的触发时刻计算器。

    ``tz`` 为 ``None`` 时进入无时区模式：表达式直接被当作墙上时间读写，永不跳过，
    这是 ``zoneinfo`` 不可用时的文档化回退。给定 ``tz`` 时，搜索在 ``tz`` 的墙上
    分钟上进行，但返回值是带偏移的瞬间，因此跨 DST 也不会重复或倒流。
    """

    def __init__(self, expression, tz=None, dom_dow_or=True):
        self._fields = parse(expression)
        self._tz = tz
        self._dom_dow_or = dom_dow_or
        self._minute, self._hour, self._dom, self._month, self._dow = (
            self._fields
        )

    @property
    def expression(self):
        return " ".join(field.spec for field in self._fields)

    @property
    def tz(self):
        return self._tz

    @property
    def dom_dow_or(self):
        return self._dom_dow_or

    @property
    def fields(self):
        return self._fields

    def __str__(self):
        return self.expression

    def __repr__(self):
        return "CronSchedule(%r, tz=%s, dom_dow_or=%s)" % (
            self.expression,
            self._tz,
            self._dom_dow_or,
        )

    def day_matches(self, wall):
        """日与星期的组合判断：只有两者都被限制时才用 Vixie 的择一规则。"""
        if wall.month not in self._month.values:
            return False
        dom_ok = wall.day in self._dom.values
        dow_ok = (wall.isoweekday() % 7) in self._dow.values
        if self._dom_dow_or and self._dom.restricted and self._dow.restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def matches(self, wall):
        """判断一个墙上分钟是否触发（不做 DST 存在性检查）。"""
        return (
            wall.minute in self._minute.values
            and wall.hour in self._hour.values
            and self.day_matches(wall)
        )

    def _search_limit(self, wall):
        try:
            return wall.replace(year=wall.year + MAX_SEARCH_YEARS)
        except ValueError:
            # 2 月 29 日起搜时没有对应的 8 年后同日，退一天即可。
            return wall.replace(
                year=wall.year + MAX_SEARCH_YEARS, month=2, day=28
            )

    def next_fire(self, after=None):
        """返回严格晚于 ``after`` 的下一次触发瞬间。

        ``after`` 可以是墙上时间（按 ``tz`` 解释）也可以是带时区的时间；省略时取
        当前时间。找不到时抛 :class:`CronSearchLimitError`。
        """
        if after is None:
            if self._tz is None:
                after = datetime.now()
            else:
                after = datetime.now(self._tz)
        wall = dst.to_wall(after, self._tz)
        limit = self._search_limit(wall)
        candidate = wall + dst.MINUTE
        minutes = self._minute.values
        hours = self._hour.values
        while candidate <= limit:
            if candidate.month not in self._month.values:
                candidate = _start_of_next_month(candidate)
                continue
            if not self.day_matches(candidate):
                candidate = _start_of_next_day(candidate)
                continue
            if candidate.hour not in hours:
                # 跳到下一个整点：小时集合很小，逐分钟试探不划算。
                candidate = datetime(
                    candidate.year, candidate.month, candidate.day,
                    candidate.hour
                ) + dst.HOUR
                continue
            if candidate.minute not in minutes:
                candidate = candidate + dst.MINUTE
                continue
            status = dst.minute_status(candidate, self._tz)
            if status == "gap":
                # 墙上分钟被拨快跳过：本库的规则是这一次不触发，不做补偿。
                candidate = candidate + dst.MINUTE
                continue
            return dst.earliest_instant(candidate, self._tz)
        raise CronSearchLimitError(
            "no fire time for %r within %d years after %s"
            % (self.expression, MAX_SEARCH_YEARS, wall)
        )

    def fire_times(self, after, count):
        """返回严格晚于 ``after`` 的 ``count`` 个触发瞬间（升序）。"""
        out = []
        cursor = after
        for _ in range(count):
            found = self.next_fire(cursor)
            out.append(found)
            cursor = found
        return out

    def fires_in(self, start, end):
        """返回 ``[start, end]`` 闭区间内的全部触发瞬间（升序）。"""
        if start is None or end is None:
            raise ValueError("fires_in needs both start and end")
        start_wall = dst.to_wall(start, self._tz)
        end_wall = dst.to_wall(end, self._tz)
        if end_wall < start_wall:
            return []
        # 闭区间要把 start 本身也算进来，而 next_fire 是严格晚于。
        limit = dst.earliest_instant(end_wall, self._tz)
        out = []
        if self.matches(start_wall) and dst.minute_status(
            start_wall, self._tz
        ) != "gap":
            head = dst.earliest_instant(start_wall, self._tz)
            if head <= limit:
                out.append(head)
        cursor = start_wall
        while True:
            try:
                nxt = self.next_fire(cursor)
            except CronSearchLimitError:
                break
            if nxt > limit:
                break
            if not out or nxt > out[-1]:
                out.append(nxt)
            cursor = nxt
        return out

    def days_per_year(self, year):
        """某一年中“月 + 日 + 星期”匹配的天数（与分钟、小时无关）。"""
        total = 0
        probe = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
        while probe < end:
            if self.day_matches(probe):
                total += 1
            probe = _start_of_next_day(probe)
        return total
