"""墙上时间与 ``zoneinfo``：DST 缺口/重叠的判定与回退策略。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
UTC = timezone.utc

# 可用性检查分三层：模块是否存在、时区数据库是否可读、目标时区能否加载。
# 只检查模块会漏掉 Windows 上最常见的失败——没有系统 tz 数据库。
try:  # pragma: no cover - 取决于运行环境
    from zoneinfo import ZoneInfo, available_timezones

    HAVE_ZONEINFO = True
    ZONEINFO_IMPORT_ERROR = None
except ImportError as error:  # pragma: no cover
    ZoneInfo = None
    available_timezones = None
    HAVE_ZONEINFO = False
    ZONEINFO_IMPORT_ERROR = str(error)

PROBE_ZONES = ("UTC", "America/New_York", "Australia/Lord_Howe")


class ZoneUnavailableError(RuntimeError):
    """请求的时区无法加载，或者传进了不接受时区的函数。"""


def zoneinfo_available() -> bool:
    """当前解释器能否 ``import zoneinfo``（Python 3.9 以上为 True）。"""
    return HAVE_ZONEINFO


def zone_status(probes=PROBE_ZONES):
    """返回可用性报告：模块、数据库、逐个时区的加载结果。

    ``tzdata_installed`` 表示至少一个探测时区能加载——这等价于“IANA 数据库可用”。
    数据库缺失时本库退化到无时区模式（纯 ``datetime`` 墙上时间算术），
    调用方可以据此决定是否安装 ``tzdata`` 包。
    """
    loaded = {}
    if not HAVE_ZONEINFO:
        return {
            "module": False,
            "error": ZONEINFO_IMPORT_ERROR,
            "tzdata_installed": False,
            "zone_count": 0,
            "zones": loaded,
        }
    for name in probes:
        try:
            loaded[name] = str(ZoneInfo(name))
        except Exception as error:  # 数据库缺失时 ZoneInfo 抛 ZoneInfoNotFoundError
            loaded[name] = "%s: %s" % (type(error).__name__, error)
    count = 0
    try:
        count = len(available_timezones())
    except Exception:  # pragma: no cover
        count = 0
    return {
        "module": True,
        "error": None,
        "tzdata_installed": all(
            loaded.get(name) == name for name in probes if name in loaded
        ),
        "zone_count": count,
        "zones": loaded,
    }


def get_zone(name):
    """加载时区；失败时抛 :class:`ZoneUnavailableError` 并说明回退方式。"""
    if not HAVE_ZONEINFO:
        raise ZoneUnavailableError(
            "zoneinfo is unavailable (%s); pass tz=None for naive wall-clock"
            " mode" % ZONEINFO_IMPORT_ERROR
        )
    try:
        return ZoneInfo(name)
    except Exception as error:
        raise ZoneUnavailableError(
            "cannot load tz %r (%s); install the tzdata package or pass"
            " tz=None to fall back to DST-blind wall-clock arithmetic"
            % (name, error)
        )


def minute_status(wall, tz):
    """判断一个墙上分钟在 ``tz`` 里是 ``ok`` / ``gap`` / ``overlap``。

    ``gap`` 是拨快跳过、从未出现的墙上分钟；``overlap`` 是拨慢后被第二次经过的
    墙上分钟（同一墙上分钟对应两个瞬间）。

    两个坑，都是实测出来的：

    1. ``wall.replace(tzinfo=tz).astimezone(tz)`` 不能用来判缺口——CPython 在
       ``self.tzinfo is tz`` 时直接返回原对象，墙上读数永远“往返成功”。
    2. 偏移不同也不能直接判成重叠：缺口里的分钟同样拿到两个不同偏移。
       瞬间 = 墙上时间 - 偏移，所以 ``fold=0`` 的偏移**更大**意味着它的瞬间**更早**，
       即这个分钟被经过两次（重叠）；偏移更小则是拨快跳过（缺口）。
    """
    if tz is None:
        return "ok"
    naive = wall.replace(second=0, microsecond=0)
    offset_first = naive.replace(tzinfo=tz, fold=0).utcoffset()
    offset_second = naive.replace(tzinfo=tz, fold=1).utcoffset()
    if offset_first == offset_second:
        return "ok"
    return "overlap" if offset_first > offset_second else "gap"


def earliest_instant(wall, tz):
    """墙上分钟的第一次经过对应的瞬间（无 ``tz`` 时就是墙上时间本身）。

    ``fold=0`` 按定义就是较早的那个瞬间，直接贴时区即可；不能再调 ``astimezone``
    去“归一化”，那在同一个 tz 对象上是空操作。
    """
    if tz is None:
        return wall
    return wall.replace(tzinfo=tz, fold=0)


def to_wall(when, tz):
    """把输入折成 ``tz`` 下的无时区墙上分钟，供逐分钟搜索使用。"""
    if when.tzinfo is None:
        return when.replace(second=0, microsecond=0)
    if tz is None:
        raise ZoneUnavailableError(
            "got an aware datetime %r but the schedule has tz=None; build"
            " the schedule with a zoneinfo zone instead" % (when.utcoffset(),)
        )
    return when.astimezone(tz).replace(tzinfo=None, second=0, microsecond=0)


def wall_year_end(year, tz):
    """某一年墙上时间的上界（次年 1 月 1 日 00:00）。"""
    return datetime(year + 1, 1, 1)


def utc_instant(when, tz):
    """把返回值换算成可比较的 UTC 瞬间，方便链式单调性断言。"""
    if when.tzinfo is None:
        return when
    return when.astimezone(UTC).replace(tzinfo=None)
