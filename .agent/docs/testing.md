# Testing

## The gate

A `Stop` hook runs `TEST_CMD` from `.agent/config.sh` before your turn is allowed
to end. If it exits non-zero, the hook blocks and hands you the output. You are
expected to fix it, not to weaken the test.

The gate is skipped when the turn produced no commits, so exploration and
question-answering turns are not charged the cost of a test run.

## What counts as a fix

- Changing production code so the test passes: yes.
- Adding a test that covers the bug you just fixed: yes, do this.
- Marking a test skipped, xfail, or deleting it: **no**. That is a blocker.
  Log it with `.agent/bin/log-blocker` and leave the test failing if you cannot
  fix it. A red suite with a logged blocker is a better outcome than a green suite
  that lies.
- Changing an assertion to match observed output without understanding why the
  output changed: **no**. That is a `high` risk blocker at minimum.

## Pre-existing failures

If `TEST_CMD` was already red when you claimed the task, note it in your first
blocker entry and scope your gate to the files you touched. Do not spend the
session fixing unrelated red.

## Cost

The gate runs the whole command each turn. If your suite is slow, set
`TEST_CMD` to a scoped invocation (a package, a marker, a changed-files selector)
and let CI run the full suite. A gate that takes four minutes will eat more plan
capacity than the work it protects.
