"""单个 cron 字段：展开后的取值集合、是否被限制、匹配。"""

from __future__ import annotations


class Field:
    """一个字段的解析结果。

    ``restricted`` 只在原始写法是裸 ``*`` 时为 ``False``。Vixie 的“日/星期择一”
    规则取决于原始写法而不是展开结果：``*/2`` 覆盖了半个值域，但作者确实限制了
    这个字段，所以它算被限制。这个区别一旦丢掉就无法还原语义。
    """

    __slots__ = ("name", "minimum", "maximum", "values", "restricted", "spec")

    def __init__(self, name, minimum, maximum, values, restricted, spec):
        self.name = name
        self.minimum = minimum
        self.maximum = maximum
        self.values = frozenset(values)
        self.restricted = restricted
        self.spec = spec

    def matches(self, value: int) -> bool:
        return value in self.values

    @property
    def size(self) -> int:
        return len(self.values)

    def sorted_values(self):
        return sorted(self.values)

    def __str__(self) -> str:
        return self.spec

    def __repr__(self) -> str:
        return "Field(%s, spec=%r, values=%d)" % (
            self.name,
            self.spec,
            self.size,
        )
