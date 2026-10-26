const std = @import("std");
const bb = @import("bbtree_dictionary.zig");
const a = std.testing.allocator;

fn check(keys: []const []const u8) !void {
    var bytes: std.ArrayList(u8) = .empty;
    defer bytes.deinit(a);
    const offsets = try a.alloc(u32, keys.len);
    defer a.free(offsets);
    for (keys, 0..) |key, i| {
        offsets[i] = @intCast(bytes.items.len);
        var length: [2]u8 = undefined;
        std.mem.writeInt(u16, &length, @intCast(key.len), .little);
        try bytes.appendSlice(a, &length);
        try bytes.appendSlice(a, key);
    }
    var tree = try bb.Dictionary.init(a, bytes.items, offsets);
    defer tree.deinit();
    try std.testing.expectEqual(tree.bytes, tree.storage.len);
    try std.testing.expect(tree.bytes <= bb.Dictionary.max_bytes);
    for (keys, 0..) |key, i| {
        try std.testing.expectEqual(@as(?usize, i), tree.find(key));
        try std.testing.expectEqual(i, tree.lowerBound(key));
        const absent = try std.fmt.allocPrint(a, "{s}~", .{key});
        defer a.free(absent);
        try std.testing.expectEqual(@as(?usize, null), tree.find(absent));
        var after = i + 1;
        while (after < keys.len and std.mem.order(u8, keys[after], absent) == .lt) : (after += 1) {}
        try std.testing.expectEqual(after, tree.lowerBound(absent));
        const prefix = key[0 .. key.len / 2];
        var expected: usize = 0;
        while (expected < keys.len and std.mem.order(u8, keys[expected], prefix) == .lt) : (expected += 1) {}
        try std.testing.expectEqual(expected, tree.lowerBound(prefix));
    }
    try std.testing.expectEqual(@as(?usize, null), tree.find(""));
    try std.testing.expectEqual(@as(usize, 0), tree.lowerBound(""));
    try std.testing.expectEqual(@as(?usize, null), tree.find("\xff\xff"));
    try std.testing.expectEqual(keys.len, tree.lowerBound("\xff\xff"));
}

test "bbtree dictionary: empty, page boundaries and multilevel fence prefixes" {
    for ([_]usize{ 0, 1, 29, 30, 31, 41, 42, 1300, 1301, 1302, 55000 }) |count| {
        const keys = try a.alloc([]const u8, count);
        defer a.free(keys);
        defer for (keys) |key| a.free(key);
        for (keys, 0..) |*key, i| key.* = try std.fmt.allocPrint(a, "common_prefix_{d:0>8}_suffix", .{i});
        try check(keys);
    }
}

test "bbtree dictionary: long prefixes, length-tag collisions and prefix keys" {
    const keys = try a.alloc([]const u8, 150);
    defer a.free(keys);
    defer for (keys) |key| a.free(key);
    const shared: [100]u8 = @splat('a');
    for (keys, 0..) |*key, i| {
        const suffix: [300]u8 = @splat('z');
        key.* = try std.fmt.allocPrint(a, "{s}{d:0>8}{s}", .{ &shared, i, suffix[0 .. i * 2] });
    }
    try check(keys);
    // Long leaf-window ties, including differing lengths and saturated tags.
    const tied = [_][]const u8{ "abcdefgh", "abcdefgha", "abcdefghaa", "abcdefghaaa", "abcdefghb", "abcdefghbb", "abcdefghc" };
    try check(&tied);
}

test "bbtree dictionary: maximum disk word lengths do not overflow prefix skips" {
    const shared: [65532]u8 = @splat('a');
    const keys = try a.alloc([]const u8, 64);
    defer a.free(keys);
    defer for (keys) |key| a.free(key);
    for (keys, 0..) |*key, i| key.* = try std.fmt.allocPrint(a, "{s}{d:0>3}", .{ &shared, i });
    try check(keys);
}
