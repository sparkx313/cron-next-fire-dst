"""cronlib：仅用标准库实现的 5 字段 cron 解析与 DST 感知的触发时刻计算。"""

from __future__ import annotations

from . import brute, dst, field, parse, schedule
from .brute import brute_fires, count_matching_days, count_matching_minutes
from .dst import (
    ZONEINFO_IMPORT_ERROR,
    ZoneUnavailableError,
    HAVE_ZONEINFO,
    get_zone,
    minute_status,
    zone_status,
    zoneinfo_available,
)
from .field import Field
from .parse import (
    DAY_NAMES,
    ERROR_CODES,
    FIELD_DEFS,
    MONTH_NAMES,
    CronParseError,
    parse,
    parse_field,
)
from .schedule import (
    MAX_SEARCH_YEARS,
    CronSchedule,
    CronSearchLimitError,
)

__version__ = "0.1.0"

__all__ = [
    "CronParseError",
    "CronSchedule",
    "CronSearchLimitError",
    "DAY_NAMES",
    "ERROR_CODES",
    "FIELD_DEFS",
    "Field",
    "HAVE_ZONEINFO",
    "MAX_SEARCH_YEARS",
    "MONTH_NAMES",
    "ZoneUnavailableError",
    "ZONEINFO_IMPORT_ERROR",
    "brute",
    "brute_fires",
    "count_matching_days",
    "count_matching_minutes",
    "dst",
    "field",
    "get_zone",
    "minute_status",
    "parse",
    "parse_field",
    "schedule",
    "zone_status",
    "zoneinfo_available",
    "__version__",
]
