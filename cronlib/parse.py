"""五字段 cron 表达式的语法解析。"""

from __future__ import annotations

from .field import Field

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

DAY_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}

# (字段名, 下界, 上界, 名称表)。星期字段的上界是 7，因为 Vixie 接受 7 表示周日。
FIELD_DEFS = (
    ("minute", 0, 59, {}),
    ("hour", 0, 23, {}),
    ("day_of_month", 1, 31, {}),
    ("month", 1, 12, MONTH_NAMES),
    ("day_of_week", 0, 7, DAY_NAMES),
)

FIELD_NAMES = tuple(definition[0] for definition in FIELD_DEFS)

# 语法错误按“每一类一条”列出，便于基准测试把解析器的契约量化。
ERROR_CODES = {
    "EMPTY_EXPRESSION": "expression is empty",
    "WRONG_FIELD_COUNT": "expression must have exactly 5 fields",
    "EMPTY_ITEM": "empty item in list",
    "EMPTY_RANGE": "empty range",
    "NOT_A_NUMBER": "not a number",
    "UNKNOWN_NAME": "unknown month or weekday name",
    "OUT_OF_RANGE": "value out of range",
    "REVERSED_RANGE": "reversed range",
    "NON_POSITIVE_STEP": "step is zero or negative",
    "STEP_WITHOUT_RANGE": "step without a range or star",
    "TOO_MANY_STEPS": "more than one step separator",
    "NOT_AN_INTEGER": "step is not an integer",
    "EMPTY_RANGE_END": "range has no end",
    "EMPTY_RANGE_START": "range has no start",
    "NO_VALUES": "field matches no value",
    "BAD_TYPE": "expression must be a string",
}


class CronParseError(ValueError):
    """解析失败；消息里永远带上字段名和原始片段。"""

    def __init__(self, code, field_name, token, message):
        self.code = code
        self.field_name = field_name
        self.token = token
        super().__init__(
            "%s: %s (got %r)" % (field_name, message, token)
        )


def parse(expression):
    """把表达式解析成 5 个 :class:`Field`。"""
    if not isinstance(expression, str):
        raise CronParseError("BAD_TYPE", "expression", repr(expression)[:24],
                             ERROR_CODES["BAD_TYPE"])
    parts = expression.split()
    if not parts:
        raise CronParseError("EMPTY_EXPRESSION", "expression", expression,
                             ERROR_CODES["EMPTY_EXPRESSION"])
    if len(parts) != 5:
        raise CronParseError(
            "WRONG_FIELD_COUNT", "expression", expression,
            "%s (found %d; seconds and @macros are not supported)"
            % (ERROR_CODES["WRONG_FIELD_COUNT"], len(parts)),
        )
    fields = []
    for spec, definition in zip(parts, FIELD_DEFS):
        name, minimum, maximum, names = definition
        fields.append(parse_field(spec, name, minimum, maximum, names))
    return tuple(fields)


def parse_field(spec, name, minimum, maximum, names):
    """解析一个字段：列表、区间、步长与名称。"""
    # 裸星号才算“未限制”，其它写法（含 */n）都算作者做了限制。
    restricted = spec != "*"
    values = set()
    for token in spec.split(","):
        if token == "":
            raise CronParseError("EMPTY_ITEM", name, spec,
                                 ERROR_CODES["EMPTY_ITEM"])
        values.update(_parse_item(token, name, minimum, maximum, names))
    if not values:
        raise CronParseError("NO_VALUES", name, spec, ERROR_CODES["NO_VALUES"])
    return Field(name, minimum, maximum, sorted(values), restricted, spec)


def _boundary(token, name, minimum, maximum, names):
    if not token:
        raise CronParseError("EMPTY_RANGE", name, token,
                             ERROR_CODES["EMPTY_RANGE"])
    key = token.lower()
    if key in names:
        return names[key]
    try:
        value = int(token)
    except ValueError:
        if any(character.isalpha() for character in token):
            raise CronParseError("UNKNOWN_NAME", name, token,
                                 "%s, allowed: %s" % (
                                     ERROR_CODES["UNKNOWN_NAME"],
                                     ",".join(sorted(set(names)))))
        raise CronParseError("NOT_A_NUMBER", name, token,
                             ERROR_CODES["NOT_A_NUMBER"])
    if value < minimum or value > maximum:
        raise CronParseError("OUT_OF_RANGE", name, token,
                             "%s %d, field %s accepts %d-%d" % (
                                 ERROR_CODES["OUT_OF_RANGE"], value, name,
                                 minimum, maximum))
    return value


def _parse_item(token, name, minimum, maximum, names):
    if token.count("/") > 1:
        raise CronParseError("TOO_MANY_STEPS", name, token,
                             ERROR_CODES["TOO_MANY_STEPS"])
    base, slash, raw_step = token.partition("/")
    step = 1
    if slash:
        if base == "":
            raise CronParseError("STEP_WITHOUT_RANGE", name, token,
                                 ERROR_CODES["STEP_WITHOUT_RANGE"])
        try:
            step = int(raw_step)
        except ValueError:
            raise CronParseError("NOT_AN_INTEGER", name, token,
                                 ERROR_CODES["NOT_AN_INTEGER"])
        if step < 1:
            raise CronParseError("NON_POSITIVE_STEP", name, token,
                                 "%s: %d" % (ERROR_CODES["NON_POSITIVE_STEP"],
                                             step))
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        head, _, tail = base.partition("-")
        if head == "":
            raise CronParseError("EMPTY_RANGE_START", name, token,
                                 ERROR_CODES["EMPTY_RANGE_START"])
        if tail == "":
            raise CronParseError("EMPTY_RANGE_END", name, token,
                                 ERROR_CODES["EMPTY_RANGE_END"])
        start = _boundary(head, name, minimum, maximum, names)
        end = _boundary(tail, name, minimum, maximum, names)
    else:
        start = _boundary(base, name, minimum, maximum, names)
        # Vixie 允许 "5/10" 这种写法，含义是 5 起步长 10 直到上界。
        end = maximum if slash else start
    if start > end:
        raise CronParseError("REVERSED_RANGE", name, token,
                             "%s: %d after %d" % (ERROR_CODES["REVERSED_RANGE"],
                                                  end, start))
    values = list(range(start, end + 1, step))
    if name == "day_of_week":
        values = [0 if value == 7 else value for value in values]
    return values
