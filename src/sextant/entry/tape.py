"""Parameter-horizon native tape; ADR-0004 records the source search and pending ruling."""

from bisect import bisect_left, bisect_right


class Tape:
    def __init__(self, fold):
        self.times, self.data, self.seen = [-1], [(None, False, None, fold.checkpoint())], set()
        self.floor = 0

    @staticmethod
    def identity(tick):
        return str(tick.trade_id), tick.ts_event, tick.price.raw, tick.size.raw

    def add(self, tick, eligible, atr, surge):
        if (identity := self.identity(tick)) in self.seen:
            return None
        if tick.ts_event < self.floor:
            raise ValueError("print precedes retained history")
        index = bisect_right(self.times, tick.ts_event)
        self.times.insert(index, tick.ts_event)
        self.data.insert(index, (tick, eligible, atr, None))
        fold = self.rebuild(surge, index)
        self.seen.add(identity)
        return fold

    def rebuild(self, surge, index=1):
        fold = self.data[index - 1][3].checkpoint()
        fold.surge = surge
        for i in range(index, len(self.data)):
            tick, eligible, atr = self.data[i][:3]
            fold._advance(tick, eligible, atr)
            self.data[i] = (tick, eligible, atr, fold.checkpoint())
        return fold

    def prune(self, cutoff):
        index = max(0, bisect_left(self.times, cutoff) - 1)
        self.seen.difference_update(self.identity(row[0]) for row in self.data[1 : index + 1])
        del self.times[:index], self.data[:index]
        self.floor = max(self.floor, cutoff)

    def rows(self, after=0):
        return (row[:3] for row in self.data[bisect_left(self.times, after) :])

    def count(self, after, end):
        return bisect_right(self.times, end) - bisect_right(self.times, after)

    def dollar_volume(self, after, end):
        a, b = bisect_right(self.times, after), bisect_right(self.times, end)
        return self.data[b - 1][3].dollars - self.data[a - 1][3].dollars
