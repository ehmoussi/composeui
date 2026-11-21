# Reloading on a change

With `--reload`, a change to a watched Python file triggers a reload. Qt and Textual use
`composeui.core.reload`. The web uses uvicorn's reload. The user guide explains
[what the user sees](../user-guide/running-the-app.md#reloading-the-app-on-a-change).

Each backend runs the program again from `__main__`. So `composeui run` (`composeui/cli.py`) gives
the file's `__main__` the module spec of `composeui.cli`. It keeps the file's path in the
`COMPOSEUI_APP_FILE` environment variable. To run the file again, `composeui.cli` reads the
variable.

## Reloading on Qt

On Qt, `--reload` works like this:

1. **A supervisor process.** With `--reload`, the process that the user starts runs
   `run_reloading` and shows no window. It runs the same command line again in a child
   process (`program_command`). The `COMPOSEUI_RELOADED` environment variable marks the
   child, so the child shows the app and does not start a supervisor of its own. The
   variable holds a scratch directory that the two processes share.
2. **Watching the files.** `watch_changes` watches the Python files under the current
   directory. It skips hidden directories, `__pycache__`, `node_modules`, and
   `site-packages`. With watchfiles, the system reports the changes
   (`force_polling=False`). Without watchfiles, and for a Windows drive under WSL
   (`has_change_events`), the supervisor compares the modification times every half
   second. watchfiles polls everywhere on WSL by default, and its polling misses changes.
3. **The change request.** On a change, the supervisor writes the paths of the changed files
   to the `changes` file of the scratch directory. The app looks for it every 200 ms, and
   takes the request by renaming the file to `taken` (`take_changes`). Once the app takes the
   request, the supervisor waits without a timeout. The timer can take the request in a dialog's
   nested event loop. The callback returns without reloading while that loop runs. Back in the
   main event loop, the app saves the study to the same directory
   (`save_reloaded_state`): the view state, the model's data, and in `session.json` the
   study file's path, whether the study has unsaved changes, the language shown, and the state
   of a new main view of this code.
   `load_reloaded_state` compares that state with a new main view of the changed code. A
   field that differs takes the value of the changed code (`_with_code_edits`). Both views
   come from the class, so that a build function cannot make them differ without an edit.
4. **In place.** When only the app's own code changed (`can_reload_in_place`),
   `rerun_program` removes the program's modules from `sys.modules`. These are the modules
   under the current directory, without ComposeUI's. Then it runs the program again as a new
   `__main__`. The app's `run` calls `keep_rerun`, which keeps the new app and ends the
   program there, as `run` would. `_Reloads` opens the study in the new main view. It
   detaches the previous views from their widgets (`_forget_widgets`), and renders the new
   main view into the same `QMainWindow` (`QtMainRenderer(view, window)` removes the
   previous bars, menus, and sidebar). Then the app removes the `taken` file
   (`acknowledge_changes`), and the supervisor keeps it running.
5. **In a new process.** When ComposeUI's own code changed, the app exits after it saves the
   study. It does the same when the new main view fails to show. It exits without the question
   on unsaved changes (`_quit_without_asking`): Qt 6's `QApplication.quit` closes the windows,
   and a window that refuses its close stops it. The supervisor then starts
   a new child, which opens the study (`load_reloaded_state`). It does the same when the app
   does not take the request within 5 seconds, after it terminates it. When the program
   fails while it runs again, for example on a syntax error, the app logs the error, keeps
   the previous code, and answers.

The supervisor stops its child when it exits, also on Ctrl+C or `kill` (SIGTERM).

## Reloading on Textual

Textual has the supervisor and the change request of Qt, but not the reload in place: its app
saves the study and exits on every request, and the supervisor starts a new child. Its
timer starts once the Textual app is mounted (`mounted_callbacks`). The supervisor logs a
change only after the app answered or exited, so it never prints over a terminal app.

## Reloading on the web

The web's `--reload` is uvicorn's, which restarts the server process. The web app only tells
watchfiles not to poll where the system reports the changes. Its sessions outlive the
processes: the process that `run` starts makes a scratch directory and a key that signs
the session cookies, and gives both to the server's processes through environment
variables. Each process takes the key out of its environment before it runs the app's code, so that
the programs that the app starts don't inherit it. Each process saves its sessions as it stops, in
its lifespan's end (`SessionStore.save_all`, with `save_reloaded_state`). The next takes them as
sessions on disk, and opens one when its cookie comes back, under the same id, as it wakes an idle
session (see [Order and sessions](web-backend.md#order-and-sessions)). Its pages ask `GET /reload`
every second, naming the process that served them (`reload_poller`): another process answers with
`HX-Refresh`.
