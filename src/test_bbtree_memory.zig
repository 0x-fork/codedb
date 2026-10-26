const std = @import("std");
const bb = @import("bbtree_dictionary.zig");

fn construct(allocator: std.mem.Allocator) !void {
    const data = "\x05\x00alpha";
    var tree = try bb.Dictionary.init(allocator, data, &.{0});
    defer tree.deinit();
    try std.testing.expectEqual(@as(?usize, 0), tree.find("alpha"));
    try std.testing.expectEqual(@as(usize, 1024), tree.storage.len);
}

test "bbtree memory: single slab allocation failure releases everything" {
    try std.testing.checkAllAllocationFailures(std.testing.allocator, construct, .{});
}

test "bbtree memory: budget ceiling rejects before allocating" {
    const data = "\x05\x00alpha";
    try std.testing.expectError(error.DictionaryBudgetExceeded,
        bb.Dictionary.initWithBudget(std.testing.allocator, data, &.{0}, 1023));
    var tree = try bb.Dictionary.initWithBudget(std.testing.allocator, data, &.{0}, 1024);
    defer tree.deinit();
    try std.testing.expectEqual(@as(usize, 1024), tree.bytes);
    var empty = try bb.Dictionary.initWithBudget(std.testing.allocator, &.{}, &.{}, 0);
    defer empty.deinit();
    try std.testing.expectEqual(@as(?usize, null), empty.find("alpha"));
}
