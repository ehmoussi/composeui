--------------------------- MODULE RepeatingTasks ---------------------------
(***************************************************************************)
(* A repeating task (`Task` with `every`, src/composeui/core/jobs.py) and  *)
(* the process's timer thread (`_Timer`).                                  *)
(*                                                                         *)
(* Three kinds of thread share the task:                                   *)
(*   - the main thread: the app's calls (start, start_latest, cancel,      *)
(*     Jobs.cancel, Jobs.drop) and the callbacks posted to it (a run's     *)
(*     outcome, `_run_due`). Each of its actions is one atomic step;       *)
(*   - the run's worker thread, which posts the run's outcome;             *)
(*   - the timer thread, which pops a due entry, and the post thread it    *)
(*     starts for it (`_post_due`), which posts `_run_due` to the main     *)
(*     thread, as late as it likes: on the web it waits for the session's  *)
(*     lock.                                                               *)
(*                                                                         *)
(* Time is left out: the timer may pop an entry at any moment, which       *)
(* covers every `every`, `backoff` and `max_wait` (`repeat_wait` is a pure *)
(* function, tested apart).                                                *)
(*                                                                         *)
(* `_generation` is modelled by what it decides: whether a due entry, or a *)
(* run's outcome, is the current one ("cur") or a stale one ("stale").     *)
(* `_unschedule` bumps the generation, so it makes every entry on its way  *)
(* stale; a new run makes the outcome of the run before stale (`_forget`,  *)
(* `drop`). This keeps the state space finite.                             *)
(***************************************************************************)

VARIABLES
    repeating,   \* task._repeat_args is not None
    job,         \* task._job: "none", "running", or "canceled" (job.cancel was called)
    workerDone,  \* the current run's worker thread has posted its outcome
    outcomes,    \* outcomes posted to the main thread, not yet handled
    heap,        \* the task's entries in the timer's heap
    posting,     \* entries the timer popped, their post thread not done yet
    mainq,       \* `_run_due` calls posted to the main thread, not yet run
    ended,       \* a web session closed or suspended: its posts do nothing
    \* ghost variables, for the properties only
    stopped,         \* cancel or drop since the last start
    jobsCanceled,    \* Jobs.cancel since the last start
    timerAfterStop,  \* the timer started a run after cancel or drop
    timerAfterJobsCancel, \* the timer started a run after Jobs.cancel
    overlap,         \* a run started while the task's run before still ran
    timerAfterEnd    \* the timer started a run in an ended session

ghosts == <<stopped, jobsCanceled, timerAfterStop, timerAfterJobsCancel, overlap,
            timerAfterEnd>>
vars == <<repeating, job, workerDone, outcomes, heap, posting, mainq, ended, ghosts>>

Kind == {"cur", "stale"}

\* every element of S becomes stale
Stale(S) == IF S = {} THEN {} ELSE {"stale"}

TypeOK ==
    /\ repeating \in BOOLEAN
    /\ job \in {"none", "running", "canceled"}
    /\ workerDone \in BOOLEAN
    /\ outcomes \subseteq Kind /\ heap \subseteq Kind
    /\ posting \subseteq Kind /\ mainq \subseteq Kind
    /\ {ended, stopped, jobsCanceled, timerAfterStop, timerAfterJobsCancel, overlap,
        timerAfterEnd} \subseteq BOOLEAN

Init ==
    /\ repeating = FALSE /\ job = "none" /\ workerDone = FALSE
    /\ outcomes = {} /\ heap = {} /\ posting = {} /\ mainq = {}
    /\ stopped = FALSE /\ jobsCanceled = FALSE
    /\ timerAfterStop = FALSE /\ timerAfterJobsCancel = FALSE /\ overlap = FALSE
    /\ ended = FALSE /\ timerAfterEnd = FALSE

-----------------------------------------------------------------------------
(* Helpers: the primed values of the timer's variables, as `_unschedule`   *)
(* leaves them, and with the next run scheduled (`_schedule_next`).        *)

\* `_unschedule`: the current entry leaves the heap; one already popped stays
\* on its way, stale.
UnscheduleHeap    == Stale(heap \ {"cur"})
UnschedulePosting == Stale(posting)
UnscheduleMainq   == Stale(mainq)

\* a new run of the task (`_run`): the outcome of any run before is stale
NewRun ==
    /\ job' = "running"
    /\ workerDone' = FALSE
    /\ outcomes' = Stale(outcomes)

-----------------------------------------------------------------------------
(* The main thread: the app's calls *)

\* Task.start, with `every`: returns False while running or repeating
Start ==
    /\ ~ended
    /\ job = "none" /\ ~repeating
    /\ NewRun
    /\ repeating' = TRUE
    \* `_reset` calls `_stop_repeat`
    /\ heap' = UnscheduleHeap /\ posting' = UnschedulePosting /\ mainq' = UnscheduleMainq
    /\ overlap' = (overlap \/ job # "none")
    /\ stopped' = FALSE /\ jobsCanceled' = FALSE
    /\ UNCHANGED <<ended, timerAfterStop, timerAfterJobsCancel, timerAfterEnd>>

\* Task.start_latest: replaces the run (the old one forgotten), repeats from now
StartLatest ==
    /\ ~ended
    /\ NewRun
    /\ repeating' = TRUE
    /\ heap' = UnscheduleHeap /\ posting' = UnschedulePosting /\ mainq' = UnscheduleMainq
    /\ stopped' = FALSE /\ jobsCanceled' = FALSE
    /\ UNCHANGED <<ended, overlap, timerAfterStop, timerAfterJobsCancel, timerAfterEnd>>

\* Task.cancel: stops repeating; the run, if any, still posts its outcome
Cancel ==
    /\ ~ended
    /\ repeating' = FALSE
    /\ job' = IF job = "running" THEN "canceled" ELSE job
    /\ heap' = UnscheduleHeap /\ posting' = UnschedulePosting /\ mainq' = UnscheduleMainq
    /\ stopped' = TRUE
    /\ UNCHANGED <<workerDone, outcomes, ended, jobsCanceled, timerAfterStop,
                   timerAfterJobsCancel, overlap, timerAfterEnd>>

\* Jobs.cancel (e.g. a Stop all button): cancels the runs going on
\* (`_cancel_runs`), then stops every repeat, a waiting one too (`_stop_repeat`)
JobsCancel ==
    /\ ~ended
    /\ job' = IF job = "running" THEN "canceled" ELSE job
    /\ repeating' = FALSE
    /\ heap' = UnscheduleHeap /\ posting' = UnschedulePosting /\ mainq' = UnscheduleMainq
    /\ jobsCanceled' = TRUE
    /\ UNCHANGED <<workerDone, outcomes, ended, stopped, timerAfterStop,
                   timerAfterJobsCancel, overlap, timerAfterEnd>>

\* Jobs.drop (New, Open, closing), Jobs._release, Jobs._abort: `_reset`; the
\* run's outcome won't be emitted
Drop ==
    /\ ~ended
    /\ repeating' = FALSE
    /\ job' = "none"
    /\ outcomes' = Stale(outcomes)
    /\ heap' = UnscheduleHeap /\ posting' = UnschedulePosting /\ mainq' = UnscheduleMainq
    /\ stopped' = TRUE
    /\ UNCHANGED <<workerDone, ended, jobsCanceled, timerAfterStop, timerAfterJobsCancel,
                   overlap, timerAfterEnd>>

\* a web session closes or hibernates (`WebSession.suspend`), a waiting repeat
\* too: `Jobs._cancel_runs` only, the repeat left on; then `call_in_session`
\* returns at once
\* (`has_ended`), so no post reaches the task. A web post runs in its posting
\* thread under the session's lock, with no queue in between: nothing waits in
\* `outcomes` or `mainq` when the session ends.
SessionEnd ==
    /\ ~ended
    /\ outcomes = {} /\ mainq = {}
    /\ ended' = TRUE
    /\ job' = IF job = "running" THEN "canceled" ELSE job
    /\ UNCHANGED <<repeating, workerDone, outcomes, heap, posting, mainq, stopped,
                   jobsCanceled, timerAfterStop, timerAfterJobsCancel, overlap,
                   timerAfterEnd>>

\* the run's work cancels its own job (`job.cancel()` in the work): the repeat
\* goes on, its next run after the outcome
SelfCancel ==
    /\ job = "running" /\ ~workerDone
    /\ job' = "canceled"
    /\ UNCHANGED <<repeating, workerDone, outcomes, heap, posting, mainq, ended, ghosts>>

-----------------------------------------------------------------------------
(* The main thread: what the other threads posted to it *)

\* Task._finish / Task._fail of the current run, then `_schedule_next`
Deliver ==
    /\ "cur" \in outcomes
    /\ outcomes' = outcomes \ {"cur"}
    /\ job' = "none"
    \* only while repeating: Task.cancel and Jobs.cancel stopped the repeat already
    /\ IF repeating
          \* `_unschedule`, then the next run in the heap
          THEN /\ heap' = UnscheduleHeap \cup {"cur"}
               /\ posting' = UnschedulePosting /\ mainq' = UnscheduleMainq
          ELSE UNCHANGED <<heap, posting, mainq>>
    /\ UNCHANGED <<repeating, workerDone, ended, ghosts>>

\* the outcome of a forgotten or dropped run: not emitted
IgnoreOutcome ==
    /\ "stale" \in outcomes
    /\ outcomes' = outcomes \ {"stale"}
    /\ UNCHANGED <<repeating, job, workerDone, heap, posting, mainq, ended, ghosts>>

\* the ghost variables as a run that the timer starts sets them
TimerRunGhosts ==
    /\ overlap' = (overlap \/ job # "none")
    /\ timerAfterStop' = (timerAfterStop \/ stopped)
    /\ timerAfterJobsCancel' = (timerAfterJobsCancel \/ jobsCanceled)
    /\ timerAfterEnd' = (timerAfterEnd \/ ended)
    /\ UNCHANGED <<stopped, jobsCanceled>>

\* Task._run_due: starts the next run if the entry is the current one
RunDue(e) ==
    /\ e \in mainq
    /\ mainq' = mainq \ {e}
    /\ IF e = "cur" /\ repeating
          THEN /\ NewRun
               /\ TimerRunGhosts
               /\ UNCHANGED <<repeating, heap, posting>>
          ELSE UNCHANGED <<repeating, job, workerDone, outcomes, heap, posting, ghosts>>
    /\ UNCHANGED ended

\* Task._run_due, the run's thread failing to start: `_run` stops the repeat
\* and raises
RunDueFails(e) ==
    /\ e \in mainq
    /\ e = "cur" /\ repeating
    /\ mainq' = UnscheduleMainq \ {e}
    /\ repeating' = FALSE
    /\ heap' = UnscheduleHeap /\ posting' = UnschedulePosting
    /\ UNCHANGED <<job, workerDone, outcomes, ended, ghosts>>

-----------------------------------------------------------------------------
(* The other threads *)

\* the run's worker thread ends, and posts its outcome (`Jobs._run`); nothing
\* reaches an ended session
WorkerEnd ==
    /\ job \in {"running", "canceled"} /\ ~workerDone
    /\ workerDone' = TRUE
    /\ outcomes' = IF ended THEN outcomes ELSE outcomes \cup {"cur"}
    /\ UNCHANGED <<repeating, job, heap, posting, mainq, ended, ghosts>>

\* the timer thread pops a due entry and starts its post thread (`_Timer._loop`)
TimerPop(e) ==
    /\ e \in heap
    /\ heap' = heap \ {e}
    /\ posting' = posting \cup {e}
    /\ UNCHANGED <<repeating, job, workerDone, outcomes, mainq, ended, ghosts>>

\* the post thread posts `_run_due` to the main thread (`_post_due`); it reads
\* only the generation it was given, never `_generation`. In an ended session,
\* `call_in_session` returns at once.
Post(e) ==
    /\ e \in posting
    /\ posting' = posting \ {e}
    /\ mainq' = IF ended THEN mainq ELSE mainq \cup {e}
    /\ UNCHANGED <<repeating, job, workerDone, outcomes, heap, ended, ghosts>>

-----------------------------------------------------------------------------

App == Start \/ StartLatest \/ Cancel \/ JobsCancel \/ Drop \/ SessionEnd

System ==
    \/ Deliver \/ IgnoreOutcome \/ WorkerEnd \/ SelfCancel
    \/ \E e \in Kind : TimerPop(e) \/ Post(e) \/ RunDue(e) \/ RunDueFails(e)

Next == App \/ System

\* the threads go on: the app's calls may never come
Fairness ==
    /\ WF_vars(Deliver) /\ WF_vars(IgnoreOutcome) /\ WF_vars(WorkerEnd)
    /\ \A e \in Kind : WF_vars(TimerPop(e)) /\ WF_vars(Post(e)) /\ WF_vars(RunDue(e))

Spec == Init /\ [][Next]_vars /\ Fairness

-----------------------------------------------------------------------------
(* Properties *)

\* cancel, New, Open or closing stops the repeat: the timer starts no run
\* after it, not even one it had posted already
NoRunAfterStop == ~timerAfterStop

\* the timer never starts a run while the task's run before still runs
NoOverlap == ~overlap

\* a task that repeats, with no run going on, always has its next run on the way
NoStall == (repeating /\ job = "none" /\ ~ended) => "cur" \in heap \cup posting \cup mainq

\* an ended web session starts no run: its waiting repeat's posts do nothing
NoRunAfterEnd == ~timerAfterEnd

\* at most one current entry: `_unschedule` before each `schedule`
\* (sets can't hold two "cur"; this checks that it never sits in two places)
OneCurrentEntry ==
    /\ ~("cur" \in heap /\ "cur" \in posting)
    /\ ~("cur" \in heap /\ "cur" \in mainq)
    /\ ~("cur" \in posting /\ "cur" \in mainq)

\* a repeating task waiting for its next run gets it, unless the app stops it
NextRunComes == (repeating /\ job = "none") ~> (job = "running" \/ ~repeating \/ ended)

\* Jobs.cancel (e.g. a Stop all button) stops the repeat whatever its moment:
\* during a run or while it waits for the next one
NoRunAfterJobsCancel == ~timerAfterJobsCancel

=============================================================================
