------------------------------- MODULE LogOut -------------------------------
(***************************************************************************)
(* Log out on the web (`MainView.on_log_out`, `MainView.log_out`), in      *)
(* src/composeui/webcore/routes.py and session.py.                         *)
(*                                                                         *)
(* `log_out` sets a flag (`WebMainRenderer.is_logging_out`), and an answer *)
(* that checks it (`WebSession.take_log_out`) sends the page to the login  *)
(* proxy's address and clears it. After `close`, that answer also drops    *)
(* the session.                                                            *)
(*                                                                         *)
(* A request holds the session's lock from its start to its answer, so it  *)
(* is one atomic step: it runs the session's pending work first (a job's   *)
(* outcome waits there for the next request, and its callback may call     *)
(* `log_out`), then the request's own app code, then its answer.           *)
(*                                                                         *)
(* The kinds of request that run the pending work are the widget posts     *)
(* ("click": a control or a dialog's answer), the route of Log out         *)
(* ("logout"), the jobs poll ("poll"), the page's load ("page") and a      *)
(* widget's fragment ("fragment"). `Checked` names those whose answer      *)
(* checks the flag. Save's and Open's routes run no pending work, and an   *)
(* app's Save or Open doesn't log out: they are left out.                  *)
(*                                                                         *)
(* The app's `on_log_out` (`mode`, the same for the whole behavior) does   *)
(* one of six things: log out now, close then log out, ask first (then log *)
(* out, or close and log out, once the user agrees), start a job whose     *)
(* callback logs out, or nothing. A job that a dialog's OK starts isn't    *)
(* one of `on_log_out`'s: the session doesn't track it.                    *)
(*                                                                         *)
(* While a job that `on_log_out` started runs, or its outcome waits, Log   *)
(* out is under way: the session ignores another click on it               *)
(* (`WebSession.log_out_clicked`), when `IgnoresUnderWay`.                 *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS
    Checked,  \* the kinds of request whose answer checks the flag
    MaxJobs,  \* the most log-out jobs at once: a user may click Log out again
    IgnoresUnderWay  \* a click on Log out while one is under way does nothing

Kinds == {"click", "logout", "poll", "page", "fragment"}
Choices == {"now", "close", "ask", "askclose", "job", "stay"}

VARIABLES
    mode,      \* what the app's `on_log_out` does, one of `Choices`
    browser,   \* where the tab is: "app", or "proxy" once the page left for it
    session,   \* "live", or "dropped" (closed, or expired)
    flag,      \* WebMainRenderer.is_logging_out
    closed,    \* MainView.close() was called (WebMainRenderer.is_closed)
    asking,    \* the app's confirmation: "no", "plain" or "close" (what OK does)
    jobs,      \* log-out jobs running
    pending,   \* their outcomes, waiting for the session's next request
    \* ghost variable, for the properties only
    leftover   \* an answer that ran the pending work left the flag set

vars == <<mode, browser, session, flag, closed, asking, jobs, pending, leftover>>

TypeOK ==
    /\ mode \in Choices
    /\ browser \in {"app", "proxy"}
    /\ session \in {"live", "dropped"}
    /\ {flag, closed, leftover} \subseteq BOOLEAN
    /\ asking \in {"no", "plain", "close"}
    /\ jobs \in 0..MaxJobs /\ pending \in 0..MaxJobs

\* a new session: what `SessionStore` builds for a browser without one
Fresh ==
    /\ session' = "live" /\ flag' = FALSE /\ closed' = FALSE
    /\ asking' = "no" /\ jobs' = 0 /\ pending' = 0

Init ==
    /\ mode \in Choices
    /\ browser = "app" /\ session = "live" /\ flag = FALSE /\ closed = FALSE
    /\ asking = "no" /\ jobs = 0 /\ pending = 0 /\ leftover = FALSE

(* One request of `kind` in a live session, its app code doing `mode` when *)
(* it is the click on Log out (nothing while Log out is under way), or     *)
(* answering the confirmation when it is a click (`answer`: "ok",          *)
(* "cancel", or "none" for another control).                               *)
(* f, c, a, j: the flag, `closed`, the question and the jobs after the app *)
(* code; the pending outcomes all ran first, each calling `log_out`.       *)
Request(kind, answer) ==
    LET underWay == IgnoresUnderWay /\ jobs + pending > 0
        choice == IF kind = "logout" /\ ~underWay THEN mode ELSE "stay"
        f0 == flag \/ pending > 0
        logOut == kind = "logout" /\ choice \in {"now", "close"}
        okCloses == kind = "click" /\ answer = "ok" /\ asking = "close"
        okLogsOut == kind = "click" /\ answer = "ok" /\ asking # "no"
        f == f0 \/ logOut \/ okLogsOut
        c == closed \/ (kind = "logout" /\ choice = "close") \/ okCloses
        a == CASE kind = "logout" /\ choice = "ask" -> "plain"
               [] kind = "logout" /\ choice = "askclose" -> "close"
               [] kind = "click" /\ answer # "none" -> "no"
               [] OTHER -> asking
        j == IF kind = "logout" /\ choice = "job" THEN jobs + 1 ELSE jobs
        leaves == kind \in Checked /\ f
    IN
    /\ j <= MaxJobs
    /\ pending' = 0
    /\ jobs' = j
    /\ asking' = a
    /\ closed' = c
    \* `_leave`: the page goes to the proxy, and a closed session is dropped
    /\ browser' = IF leaves THEN "proxy" ELSE "app"
    /\ flag' = IF leaves THEN FALSE ELSE f
    /\ session' = IF leaves /\ c THEN "dropped" ELSE session
    /\ leftover' = (leftover \/ (f /\ ~leaves))

\* the user (or the page) sends a request from the app's page
Act ==
    /\ browser = "app" /\ session = "live"
    /\ \/ Request("logout", "none")
       \/ \E answer \in {"ok", "cancel", "none"} :
            /\ answer # "none" => asking # "no"
            /\ Request("click", answer)
       \/ Request("page", "none")
       \/ Request("fragment", "none")

\* the page polls while the jobs run, and until their outcomes came back
Poll ==
    /\ browser = "app" /\ session = "live" /\ jobs + pending > 0
    /\ Request("poll", "none")

\* a job's thread ends: its outcome waits for the session's next request
JobEnd ==
    /\ session = "live" /\ jobs > 0
    /\ jobs' = jobs - 1 /\ pending' = pending + 1
    /\ UNCHANGED <<browser, session, flag, closed, asking, leftover>>

\* the session ends (`session_ttl`), the page open or not
Expire ==
    /\ session = "live"
    /\ session' = "dropped"
    /\ UNCHANGED <<browser, flag, closed, asking, jobs, pending, leftover>>

\* Log out without the session: the route sends the page to the proxy at once
LogOutWithoutSession ==
    /\ browser = "app" /\ session = "dropped"
    /\ browser' = "proxy"
    /\ UNCHANGED <<session, flag, closed, asking, jobs, pending, leftover>>

\* the page's request without the session: it reloads into a new one
Reload ==
    /\ browser = "app" /\ session = "dropped"
    /\ Fresh
    /\ UNCHANGED <<browser, leftover>>

\* the user logs in again and loads the page: the same session if it stays
Return ==
    /\ browser = "proxy"
    /\ IF session = "live"
       THEN Request("page", "none")
       ELSE Fresh /\ browser' = "app" /\ UNCHANGED leftover

Next ==
    /\ \/ Act \/ Poll \/ JobEnd \/ Expire \/ LogOutWithoutSession \/ Reload \/ Return
    /\ UNCHANGED mode

\* the jobs end, and the page polls while they run: the user may do nothing
Spec == Init /\ [][Next]_vars /\ WF_vars(JobEnd /\ UNCHANGED mode) /\ WF_vars(Poll /\ UNCHANGED mode)

-----------------------------------------------------------------------------
(* Properties *)

\* every answer that runs the pending work leaves with a log out asked
\* there: none leaves the flag for a later, unrelated answer
NoLeftoverFlag == ~leftover

\* a closed session never stays once its page left for the proxy
ClosedIsDropped == (browser = "proxy" /\ closed) => session = "dropped"

\* a flag set is never seen by the page: it is cleared as the page leaves
FlagClearedAsThePageLeaves == browser = "proxy" => ~flag

\* once the page left for the proxy, the session that stays has no log out on
\* its way: the user back from the proxy isn't sent there again, unless they
\* click Log out (a dropped session delivers nothing)
NoLogOutLeftBehind == (browser = "proxy" /\ session = "live") => jobs + pending = 0

\* a log out on its way, in a job, takes the page to the proxy, even if the
\* user does nothing more: the poll brings it. Unless the session ends first:
\* an ended session runs nothing more, its log out included
JobLogsOut ==
    (browser = "app" /\ session = "live" /\ jobs + pending > 0)
        ~> (browser = "proxy" \/ session = "dropped")

=============================================================================
