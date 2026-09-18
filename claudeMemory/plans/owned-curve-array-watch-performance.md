# Owned curve array watch performance correction

Status: reviewed for implementation, 2026-09-16. Both fresh reviewers finished;
all surviving findings are folded in below.

The headed 32767-point boundary fixture exceeded the debug request deadline
while replacing its raw point array and synchronizing. Do not replay the write:
the original test process is still executing it. Inspection found newly added
watch invalidation traverses the complete IDProperty array on every SetIndex
and every append, including fresh codec arrays. This makes construction
quadratic whenever an unrelated editor path watch exists. This is an inferred
cause pending a measured corrected run.

Proposed bounded correction:

1. Separate exact-container membership notification from actual relocation.
   Add a path-watch-only exact-node invalidation helper. It must never detach
   curve records. IDP_SetIndexArray invalidates the array watch through that
   helper; its existing old-item content-free hook invalidates the replaced
   subtree. Other items do not move, so their watches need not be traversed.
2. IDP_ResizeIDPArray invalidates the array's exact watch on any length change.
   Retain whole-subtree path-watch invalidation immediately before reallocating
   the inline buffer, while all old pointers remain valid. Shrinking frees
   trailing items through existing hooks. Growing within capacity moves no
   existing elements. Preserve conservative stale-create rejection through the
   array watch; actual RNA move retains full subtree invalidation.
3. Native tests exercise watched target/sibling/array on SetIndex, growth within
   capacity, reallocating growth, shrink, and move. Records still tolerate moves.
   Measure fresh codec/raw construction with unrelated live watches, then run
   the actual headed maximum-point insertion cases. Do not lower the format
   limit or bypass the raw mutation API merely to make the test finish.
4. Repeat existing runtime/RNA/editor lifecycle checks, rebuild and restore
   original test build options. Record actual timing and any residual bottleneck.

Reviewers must try to break this against actual IDP_ResizeIDPArray branches,
invalidation/free hooks, RNA move and path inspector watch acquisition. In
particular, inspect temporary worker copies, stale inline keys, equal-content
replacements, and whether any branch reallocates without invalidation.

## Surviving review corrections

- `review_array_watch_lifetime`: RNA collection removal and library-override
  collection clear shift inline items with `memmove` before calling Resize.
  Add full path-tree invalidation before each memmove, just as explicit move
  already does. Shrink alone cannot detect that surviving identities moved.
- `review_array_watch_complexity`: both reallocating growth and large-capacity
  shrink need full invalidation. Place it on the common non-early-return path,
  before freeing trailing items, while every old node is intact. Codec
  preallocation plus SetIndex currently triggers the quadratic full scans.
- A surviving item watch remains valid for within-capacity append; the array
  watch expires and therefore existing UI captures still reject changed paths.
  Correct the previous native test which required the item itself to expire.
- Equal-content replacement still invalidates the replaced subtree through
  its existing free hook. Actual curve definitions are stable heap children;
  inline-array relocation must continue preserving their runtime records.
- Explicitly test within-capacity shrink (`300 -> 299`) and reallocating
  shrink (`totallen - 200`), equal-content replacement with an untouched watched
  sibling, and preallocated encoding versus raw construction/sync at two sizes.
  Keep an unrelated live watch held during timing, otherwise the empty-watch
  fast path masks the old behavior. Do not add unconditional main-thread
  assertions to hooks used by unregistered worker temporaries.
