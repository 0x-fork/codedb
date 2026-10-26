//! Read-only specialization of XiangpengHao/bbtree's unsync string search.
//! Copyright (c) 2026 Xiangpeng Hao; MIT notice: bbtree.LICENSE.
//! Upstream f0a5d361ecb4df176b3e07d4e33bb399dc3d22bf (MIT):
//! tree/{search,prefix}.rs, node/{inline_key_search,leaf,internal,node_plan}.rs.
//! Same 1KiB leaves / 512B internals, 8/4-byte inline windows, fence prefixes,
//! full-capacity counts, head separators, early-exit tie search and length tags.
//! Keys borrow validated mmap records; values are sorted dictionary ordinals.
//! Only bulk construction is specialized: no mutable/concurrent map is ported.
const std = @import("std");

const Entry = extern struct { key: [*]const u8, len: usize, rank: u32, padding: u32 = 0 };
const Header = extern struct { len: u16, prefix: u16, reserved: u32 = 0 };
const Leaf = extern struct {
    header: Header align(1024),
    windows: [30]u64,
    tags: [30]u8,
    padding: [2]u8 = .{ 0, 0 },
    entries: [31]Entry, // slot zero is the separator's head
};
const Internal = extern struct {
    header: Header align(512),
    windows: [41]u32,
    padding: u32 = 0,
    children: [42]usize,
};
comptime {
    std.debug.assert(@sizeOf(Leaf) == 1024);
    std.debug.assert(@sizeOf(Internal) == 512);
}

pub const Dictionary = struct {
    allocator: std.mem.Allocator,
    root: usize = 0, // low bit denotes an internal node
    shared: []const u8 = &.{},
    count: usize,
    bytes: usize = 0,
    storage: []align(1024) u8 = &.{},
    leaf_cursor: usize = 0,
    internal_cursor: usize = 0,

    /// A fixed ceiling on accelerator memory, independent of corpus size.
    /// Larger dictionaries retain the complete binary-search index instead.
    pub const max_bytes: usize = 8 * 1024 * 1024;

    pub fn init(allocator: std.mem.Allocator, data: []const u8, offsets: []const u32) !Dictionary {
        return initWithBudget(allocator, data, offsets, max_bytes);
    }

    pub fn initWithBudget(allocator: std.mem.Allocator, data: []const u8, offsets: []const u32, budget: usize) !Dictionary {
        var self = Dictionary{ .allocator = allocator, .count = offsets.len };
        if (offsets.len == 0) return self;
        // Each record needs at least one Entry, even before inline windows.
        // Reject oversized input before traversing its shape or reading keys.
        if (offsets.len > budget / @sizeOf(Entry)) return error.DictionaryBudgetExceeded;
        const first = word(data, offsets[0]);
        self.shared = first[0..@min(64, common(first, word(data, offsets[offsets.len - 1])))];
        var height: usize = 0;
        var capacity: usize = 30;
        while (capacity < offsets.len) : (height += 1) capacity = capacity * 42 + 41;
        const layout = nodeCounts(offsets.len, height);
        self.bytes = layout.leaves * @sizeOf(Leaf) + layout.internals * @sizeOf(Internal);
        if (self.bytes > budget) return error.DictionaryBudgetExceeded;
        // One exact-size allocation: no per-node malloc/alignment overhead and
        // no arena high-water retention after promotion. Leaves come first so
        // every leaf and internal page has its upstream alignment without gaps.
        self.storage = try allocator.alignedAlloc(u8, .fromByteUnits(1024), self.bytes);
        self.internal_cursor = layout.leaves * @sizeOf(Leaf);
        self.root = self.build(data, offsets, 0, offsets.len, height, null, null, null);
        return self;
    }

    pub fn deinit(self: *Dictionary) void {
        self.allocator.free(self.storage);
    }

    fn nodeCounts(count: usize, height: usize) struct { leaves: usize, internals: usize } {
        if (height == 0) return .{ .leaves = 1, .internals = 0 };
        var capacity: usize = 30;
        for (1..height) |_| capacity = capacity * 42 + 41;
        const children = @min(42, (count + capacity + 1) / (capacity + 1));
        const remaining = count - (children - 1);
        var total: @TypeOf(nodeCounts(0, 0)) = .{ .leaves = 0, .internals = 1 };
        for (0..children) |i| {
            const child = nodeCounts(remaining / children + @intFromBool(i < remaining % children), height - 1);
            total.leaves += child.leaves;
            total.internals += child.internals;
        }
        return total;
    }

    fn build(self: *Dictionary, data: []const u8, offsets: []const u32, start: usize, end: usize, height: usize, head: ?usize, low: ?usize, high: ?usize) usize {
        const prefix = if (low != null and high != null)
            common(word(data, offsets[low.?]), word(data, offsets[high.?]))
        else
            self.shared.len;
        if (height == 0) {
            const n: *Leaf = @ptrCast(@alignCast(self.storage.ptr + self.leaf_cursor));
            self.leaf_cursor += @sizeOf(Leaf);
            n.* = .{ .header = .{ .len = @intCast(end - start), .prefix = @intCast(prefix) }, .windows = @splat(std.math.maxInt(u64)), .tags = @splat(255), .entries = undefined };
            if (head) |h| n.entries[0] = entry(data, offsets, h);
            for (start..end, 0..) |rank, i| {
                const e = entry(data, offsets, rank);
                n.entries[i + 1] = e;
                n.windows[i] = window(e.key[0..e.len], prefix);
                n.tags[i] = tag(e.len);
            }
            return @intFromPtr(n);
        }
        var child_capacity: usize = 30;
        for (1..height) |_| child_capacity = child_capacity * 42 + 41;
        const count = end - start;
        const children = @min(42, (count + child_capacity + 1) / (child_capacity + 1));
        const n: *Internal = @ptrCast(@alignCast(self.storage.ptr + self.internal_cursor));
        self.internal_cursor += @sizeOf(Internal);
        n.* = .{ .header = .{ .len = @intCast(children - 1), .prefix = @intCast(prefix) }, .windows = @splat(std.math.maxInt(u32)), .children = undefined };
        const remaining = count - (children - 1);
        var pos = start;
        var prev = low;
        for (0..children) |i| {
            const size = remaining / children + @intFromBool(i < remaining % children);
            const next: ?usize = if (i + 1 < children) pos + size else high;
            n.children[i] = self.build(data, offsets, pos, pos + size, height - 1, if (i == 0) head else prev, prev, next);
            pos += size;
            if (i + 1 < children) {
                n.windows[i] = @truncate(window(word(data, offsets[pos]), prefix) >> 32);
                prev = pos;
                pos += 1;
            }
        }
        return @intFromPtr(n) | 1;
    }

    /// Ordered lookup, also used as the prefix range's lower bound.
    pub fn lowerBound(self: *const Dictionary, key: []const u8) usize {
        if (self.root == 0) return 0;
        const compared = std.mem.order(u8, key[0..@min(key.len, self.shared.len)], self.shared);
        if (compared == .lt) return 0;
        if (compared == .gt) return self.count;
        var node = self.root;
        while (node & 1 != 0) {
            const n = internal(node);
            const target: u32 = @truncate(window(key, n.header.prefix) >> 32);
            const range = equalRange(u32, 41, n.windows, n.header.len, target);
            var lo = range[0];
            var hi = range[1];
            while (lo < hi) {
                const mid = lo + (hi - lo) / 2;
                const e = headEntry(n.children[mid + 1]);
                switch (compare(key, e, @as(usize, n.header.prefix) + 4)) {
                    .eq => return e.rank,
                    .lt => hi = mid,
                    .gt => lo = mid + 1,
                }
            }
            node = n.children[lo];
        }
        const n = leaf(node);
        const range = equalRange(u64, 30, n.windows, n.header.len, window(key, n.header.prefix));
        var lo = range[0];
        var hi = range[1];
        while (lo < hi) {
            const mid = lo + (hi - lo) / 2;
            switch (compare(key, n.entries[mid + 1], @as(usize, n.header.prefix) + 8)) {
                .eq => return n.entries[mid + 1].rank,
                .lt => hi = mid,
                .gt => lo = mid + 1,
            }
        }
        if (lo < n.header.len) return n.entries[lo + 1].rank;
        if (n.header.len > 0) return n.entries[n.header.len].rank + 1;
        return n.entries[0].rank + 1;
    }

    pub fn find(self: *const Dictionary, key: []const u8) ?usize {
        if (self.root == 0 or !std.mem.startsWith(u8, key, self.shared)) return null;
        var node = self.root;
        while (node & 1 != 0) {
            const n = internal(node);
            const range = equalRange(u32, 41, n.windows, n.header.len, @truncate(window(key, n.header.prefix) >> 32));
            var lo = range[0];
            var hi = range[1];
            while (lo < hi) {
                const mid = lo + (hi - lo) / 2;
                const e = headEntry(n.children[mid + 1]);
                switch (compare(key, e, @as(usize, n.header.prefix) + 4)) {
                    .eq => return e.rank,
                    .lt => hi = mid,
                    .gt => lo = mid + 1,
                }
            }
            node = n.children[lo];
        }
        const n = leaf(node);
        const range = equalRange(u64, 30, n.windows, n.header.len, window(key, n.header.prefix));
        if (range[0] == range[1]) return null;
        if (range[1] - range[0] == 1) {
            const e = n.entries[range[0] + 1];
            return if (compare(key, e, @as(usize, n.header.prefix) + 8) == .eq) e.rank else null;
        }
        var matches: [2]usize = undefined;
        var count: usize = 0;
        for (range[0]..range[1]) |i| {
            if (n.tags[i] == tag(key.len)) {
                if (count < 2) matches[count] = i;
                count += 1;
            }
        }
        if (count <= 2) {
            var i = count;
            while (i > 0) {
                i -= 1;
                const e = n.entries[matches[i] + 1];
                const order = compare(key, e, @as(usize, n.header.prefix) + 8);
                if (order == .eq) return e.rank;
                if (order == .gt) return null;
            }
            return null;
        }
        var lo = range[0];
        var hi = range[1];
        while (lo < hi) {
            const mid = lo + (hi - lo) / 2;
            const e = n.entries[mid + 1];
            switch (compare(key, e, @as(usize, n.header.prefix) + 8)) {
                .eq => return e.rank,
                .lt => hi = mid,
                .gt => lo = mid + 1,
            }
        }
        return null;
    }
};

fn leaf(node: usize) *Leaf {
    return @ptrFromInt(node);
}
fn internal(node: usize) *Internal {
    return @ptrFromInt(node & ~@as(usize, 1));
}
fn headEntry(node_: usize) Entry {
    var node = node_;
    while (node & 1 != 0) node = internal(node).children[0];
    return leaf(node).entries[0];
}
pub fn word(data: []const u8, offset: u32) []const u8 {
    const len = std.mem.readInt(u16, data[offset..][0..2], .little);
    return data[offset + 2 ..][0..len];
}
fn entry(data: []const u8, offsets: []const u32, rank: usize) Entry {
    const key = word(data, offsets[rank]);
    return .{ .key = key.ptr, .len = key.len, .rank = @intCast(rank) };
}
fn common(a: []const u8, b: []const u8) usize {
    var i: usize = 0;
    while (i < @min(a.len, b.len) and a[i] == b[i]) : (i += 1) {}
    return i;
}
fn tag(len: usize) u8 {
    return @intCast(@min(255, len));
}
fn window(key: []const u8, prefix: usize) u64 {
    var bytes: [8]u8 = @splat(0);
    if (prefix < key.len) @memcpy(bytes[0..@min(8, key.len - prefix)], key[prefix..][0..@min(8, key.len - prefix)]);
    return std.mem.readInt(u64, &bytes, .big);
}
fn compare(key: []const u8, e: Entry, skip: usize) std.math.Order {
    // Upstream SearchBytes::cmp_from: compare 8-byte big-endian words;
    // the final word may overlap bytes already proven equal. No memcmp.
    const stored = e.key[0..e.len];
    const both = @min(key.len, e.len);
    if (skip < both and both < 8) {
        const order = std.math.order(window(key, 0), window(stored, 0));
        return if (order == .eq) std.math.order(key.len, e.len) else order;
    }
    var compared = skip;
    while (compared < both) {
        const end = @min(compared + 8, both);
        const query_word = std.mem.readInt(u64, key[end - 8 ..][0..8], .big);
        const stored_word = std.mem.readInt(u64, stored[end - 8 ..][0..8], .big);
        const order = std.math.order(query_word, stored_word);
        if (order != .eq) return order;
        compared = end;
    }
    return std.math.order(key.len, e.len);
}
fn equalRange(comptime T: type, comptime capacity: usize, slots: [capacity]T, len: usize, target: T) [2]usize {
    const values: @Vector(capacity, T) = slots;
    const query: @Vector(capacity, T) = @splat(target);
    const below = @reduce(.Add, @as(@Vector(capacity, u16), @intFromBool(values < query)));
    const equal = @reduce(.Add, @as(@Vector(capacity, u16), @intFromBool(values == query)));
    const start = @min(len, below);
    return .{ start, @min(len, start + equal) };
}
