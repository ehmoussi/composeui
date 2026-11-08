---
name: state-machines
description: "Use before adding, changing or reviewing a state machine in ComposeUI, explicit or implicit: code that holds state over time, even when nobody calls it one. Signs: a flag or optional field that says where something is in its life; a thread, job, timer or callback that ends later than the code that started it; open/close, start/stop or setup/teardown; what a control or screen allows in each state; a stack or queue; numbered or retried requests; a file being replaced; a lock. Also when fixing a bug in such code."
---

# State Machines

Most lifecycle bugs in ComposeUI came from code that was a state machine without being written
as one. A flag, a timer and a callback made several states. Nobody decided what each event does
in each state, so a late event took the path that the normal case had.

Threads are one kind of this. A dialog stack, a control's enabled state, a row's position and a
request between the browser and the server are others, and they need no thread to fail.

Use this procedure when a change adds or alters state of this kind. To decide, ask: can the
result be wrong because of when an event arrives, or which one comes first? If not, stop here:
ordinary view code that sets a field and shows it does not need a table.

**The lists below are not exhaustive.** The signs, the kinds and the answers are starting points,
from bugs found so far. The method is the table: a case that no list names is the one to look
for. Do not stop because every item here is checked.

## Find the state machine

Look for these signs in the code that the change touches:

- **Fields that change together,** such as a flag and an optional object: `has_ended`, a loader's
  `isLoading`, a renderer's `screen`.
- **Work that ends later than its start:** a job's thread, a `threading.Timer`, a callback
  handed to the main thread, an htmx answer.
- **Pairs:** open and close, start and stop, setup and teardown, acquire and release.
- **Counters and watermarks,** such as `PostOrder`'s next number.
- **A list or stack that other code also changes,** such as Textual's screen stack, or `rows`
  that a `cell_edited` callback replaces.

## Write the table

Do these steps before you write the code, and keep the table in your notes or in the review.

1. **Name the states,** also those that nobody wrote down: "dropped, thread alive",
   "closed while covered", "load failed".
2. **List the events, also those in an unusual order:** a close from the code while another dialog
   covers this one, a worker that ends after a close, a timer already firing, a duplicate post, a
   failed setup, a second click, an error in a callback.
3. **Cross every state with every event.** Each cell needs one of four answers: do it (say what),
   ignore it, refuse it, or "cannot happen", naming what guarantees that. An empty cell is a bug
   that has not happened yet. So is a "cannot happen" that no code guarantees.
   Keep the table small: merge the states that answer every event alike, and the events that
   every state answers alike. Add a row back when two of them differ.
4. **List what must never be true together:** a closed session whose views still change, a disabled
   action whose shortcut runs.

For example, a job, in part:

| State | Result delivered | Database write | Upload read |
| --- | --- | --- | --- |
| Running | Emit it | Allow | Keep the file |
| Canceled | Emit it | Allow | Keep the file |
| Dropped, thread alive | Ignore | Refuse (`Job.is_dropped`) | Keep the file (`Jobs.has_workers`) |
| Session closed, thread alive | Ignore (`has_ended`) | Refuse | Keep the file (`Jobs.after_workers`) |
| Thread over | Emit it, unless dropped or the session ended | Cannot happen: no thread is left | Delete the file, if replaced or closed |

A result normally arrives after its thread is over: the thread only queues it. A form dialog on
Textual has no thread, and the same method applies:

| State | The app closes it | Escape | The app opens it | The dialog above closes |
| --- | --- | --- | --- | --- |
| On top | Pop it | Close it | Ignore | Cannot happen: nothing is above it |
| Covered | Mark it closed | Goes to the top screen | Ignore | Show it |
| Closed, still covered | Ignore | Goes to the top screen | Mark it open | Pop it |
| Closed, off the stack | Ignore | Cannot happen: it isn't shown | Push it | Cannot happen: it isn't on the stack |

A message dialog differs: it builds a new screen at each opening, so opening it while the closed
one is covered pushes another screen. Write the table of the code in front of you.

## Answers that often apply

These are common answers, grouped by kind. Your table can need another one.

### Threads, jobs and timers

- **"No longer counts" is not "has stopped".** `Job.cancel` and `Jobs.drop` do not stop a thread.
  Track the thread apart from its outcome. Guard what it can still reach.
- **A closed session is final.** After a session closes, nothing changes its views or reports to
  its user. Cleanup still runs, such as `Jobs.after_workers` deleting its uploads.
- **Never wait for the main thread while holding a lock that its callback may need.**
  `App.call_from_thread` waits. A job's handover must not.
- **Compare a timer with the current one before it acts.** Canceling a timer cannot take back a
  call already on its way.
- **Serialize what depends on global settings,** such as Matplotlib's `rcParams`.
- **Catch only the failure that you mean.** A `RuntimeError` from a callback is not a failed
  dispatch. Never run a callback again because it raised.

### Screens and controls

- **Every way in checks the same state.** A shortcut as well as a button. The server as well as
  the HTML: `WebRenderer.takes_events`.
- **An action on the top of a stack is not an action on this screen.** A screen covered by another
  one can't pop itself: Textual's `dismiss` pops the top screen.
- **"No choice" is a state to show,** apart from a value that is `None`.

### Data and positions

- **A position is valid only until the next callback.** A callback can sort, replace or remove
  `rows`. Find the record again.

### Requests between the browser and the server

- **An answer can arrive twice, late, or out of order.** Number what can be reordered.
- **A failed load needs a way back, if it is safe to repeat.** Clear its pending mark and retry a
  bounded number of times, as `loadLibrary` does. Never retry a post that changes state: `PostOrder`
  refuses a number that it has seen.

### Files and other resources

- **Each resource has one owner at each moment.** Give it an owner from the line that creates it.
  Close it when the setup fails.
- **A restored session owns only what it can prove is its own.** A saved state that names a path
  can be wrong or changed: check the path before the session can delete it, as `_saved_uploads` in
  `webcore/session.py` does. See the `web-security` skill.
- **Write beside a file, then rename.** Use `_partial_path` and `_publish` in `core/view.py`. A
  failure or a cancel leaves the previous file, and reports no success.
- **Cleanup goes in `finally`, and restores what was there before.** Restore a previous state,
  such as `blockSignals`' return value, rather than a constant.

## Prove it

Ask the user before you add or change a test, as `AGENTS.md` requires. Follow the `test-audit`
skill: each test must fail without the fix, for the intended reason.

- **Drive each order through the real widget,** with `qtbot`, the Textual pilot or the
  `TestClient`. A dialog closed while covered needs no thread: open, close and press the keys in
  that order.
- **Delay or fail an answer in the browser** with Playwright's `page.route`, then let it through.
- **Hold a race with events.** Pause the worker with a `threading.Event` at the exact moment, make
  the other event happen, then release it. Join the thread, or wait for the job, before you read
  the result. A fixed sleep does not prove the order.
- **Test a deadlock in a subprocess,** with a timeout and `faulthandler.dump_traceback_later`, so
  that a failure shows the stacks and does not hang the test run, as
  `test_a_job_reporting_inside_a_transaction_and_a_callback_reading_the_model_both_end` does.
- **Test an event against each state that it can reach,** not only the normal order.
- **Use a `RuleBasedStateMachine` when states combine.** See "Property-based tests" in the
  `test-audit` skill.
- **A cell answered "ignore" or "refuse" needs a test too.** It must fail if the guard goes away.

## Make it explicit when it pays

When the table has more than a few real states, or a bug came from a missing cell, say so in the
review, and propose making the states explicit. This is a separate change, unless the fix needs
it: one fix per pull request. Such a change can:

- Put the transition in one place, such as `WebSession.handle_event` for a control's events.
- Replace flags that must agree with one field that holds the state.
- Add a state-machine test, which fails whether or not someone read this skill.

## Report

In a review or a pull request, say which state machine the change touches and which cells it
adds or changes. Say which orders of events you checked, and which you did not.
