# Environment variables

Every setting the delegator reads, in one place. All of them are optional; the default is in brackets.
Secrets (API keys) belong in `.env`, which is never committed. Never paste their values into logs or issues.

## Safety: real input and approvals

| Variable | Meaning |
|---|---|
| `NELLY_LIVE_INPUT` | `1` = real mouse and keyboard. [unset = **dry run**: nothing is clicked or typed] |
| `NELLY_DRY_RUN` | `1` = force a dry run, even if `NELLY_LIVE_INPUT=1` (tests set it). |
| `NELLY_POLICY_MODE` | `standard` (ask only for the always-ask list) or `strict` (also ask for anything above low risk). [standard] |
| `NELLY_APP_ALLOWLIST` | Comma list of apps that need no approval. [the Safety schema's apps] |
| `NELLY_SAFETY_MODULE` | Importable module with `check(request)`: Team 3's real Safety. [mock policy] |
| `NELLY_EXECUTOR` | `team1` = run Team 1's executor through `execution/team1_bridge.py`. [our interim executor] |

## Vision (Team 1)

| Variable | Meaning |
|---|---|
| `NELLY_DETECTOR_WEIGHTS` | Path to the trained detector (`best.pt`). Without it Team 1's vision may fall back to weak edge proposals; a start-up warning says so. |
| `NELLY_VISION` | `off` / `0` / `fake` = do not use Team 1's vision (labelled fake screen, dry runs only). |
| `NELLY_ALLOW_FAKE_VISION` | `1` = allow the fake screen even with live input (not recommended). |
| `NELLY_VISION_TIMEOUT` | Seconds one vision call may take before the step stops as needs_review. `0` = no limit. [180] |
| `NELLY_CAPTURE` | `window` = vision reads only the foreground window (Team 1 capture_window), which makes OCR much faster; anything else = the whole screen. [screen] |
| `NELLY_TOP_ELEMENTS` | How many screen elements the model sees, most relevant to the goal first (10 to 200). More = more tokens and time per decision. [60] |
| `NELLY_MIN_FREE_MEM_GB` | Free memory (RAM + page file) below which OCR is never started (it crashed the process when memory was low). [3] |
| `NELLY_MAX_OBS_AGE` | Maximum age in seconds of an observation used for a click (our resolver and, through the bridge, Team 1's executor). [15] |
| `NELLY_OCR_LANGS`, `NELLY_DETECTOR_IMGSZ` | Read by Team 1's vision package itself (OCR languages, detector input size). |

## Worker

| Variable | Meaning |
|---|---|
| `NELLY_MAX_ACTIONS` | Actions the worker may take per sub-goal. [8] |
| `NELLY_REGROUND_RETRIES` | Fresh looks after a "the screen changed" refusal (stale, window_*, wrong_window) before escalating. [2] |
| `NELLY_FIND_RETRIES` | Extra looks when the model finds no usable target on screen; each failure is fed back so it tries another way. 0 = stop at once, max 10. [3] |
| `NELLY_ACTION_DECIDER` | `legacy` = force the no-model prefix parser. |
| `NELLY_VERIFIER` | `rule` = force the offline structural verifier. |

## Interim executor (`execution/desktop_adapter.py`)

| Variable | Meaning |
|---|---|
| `NELLY_ACTION_PAUSE` | Pause between pyautogui actions, seconds. [0.4] |
| `NELLY_SETTLE` | Wait before the after-action screenshot, seconds. [0.6] |
| `NELLY_OPEN_WAIT` | Wait after open_app, seconds. [2.5] |
| `NELLY_SHOTS_DIR` | Folder for after-action screenshots. [system temp folder] |

## Model (LLM)

| Variable | Meaning |
|---|---|
| `NELLY_LLM_API_KEY`, `NELLY_LLM_BASE_URL`, `NELLY_LLM_MODEL` | Any OpenAI-compatible provider; the single source for every model call. When any of them is set, the DashScope variables are ignored. Set the model together with the base URL. Key in `.env` only. |
| `NELLY_LLM_TIMEOUT` | Seconds to wait for the model's answer before the call fails with a clear error. [60] |
| `NELLY_LLM_RETRIES` | How many times a failed model call is retried (503, timeout, dropped connection) before it fails. 0 to 8. [2] |
| `NELLY_LLM_MAX_TOKENS` | Optional upper bound on the length of one model answer (a cut-off answer is re-asked once). Unset = the provider default. [unset] |
| `NELLY_PLAN_MODEL` | Optional: a different (stronger) model used ONLY for planning; it wins over NELLY_LLM_MODEL for that call. Unset = the normal model. [unset] |
| `NELLY_PLAN_CHECK` | `off` = skip the model's review of the plan: the planner writes it and the run goes straight on, UNCHECKED (shown as method "skipped", reason disabled_by_NELLY_PLAN_CHECK). [on] |
| `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL` | **Legacy** provider settings, used only when no `NELLY_LLM_*` variable is set. Key in `.env` only. |

## Store, persistence and output

| Variable | Meaning |
|---|---|
| `NELLY_PERSIST` | `0` = turn persistence off. |
| `NELLY_DB` | The store's database file. [agent.db] |
| `NELLY_DB_BACKEND` | Force a store backend. |
| `NELLY_CHECKPOINT_MODULE` | Which store module to import. |
| `NELLY_REQUIRE_STORE` | `1` = fail instead of using the built-in shim. |
| `NELLY_STORE_PATH`, `NELLY_STORE_PATH_CAPABLE` | Where the team store lives, and whether it accepts a path. |
| `NELLY_GRAPH_DB` | LangGraph checkpoint file (separate from the store). |
| `NELLY_QUIET` | `1` = `run.py` prints no progress. |
| `NELLY_TRACE` | `1` = same as `python run.py --trace`: write `runs/run_<id>.json` and `.html` (the run viewer page). |
| `NELLY_TRACE_DIR` | Folder for the trace files. [runs] |
| `NELLY_TRACE_FULL` | `1` keeps window titles and screen text in the trace. Default: hidden. Such a file is private; clean it before showing it. |

## Start-up checks

`run.py` prints a `[startup] WARNING` line when `NELLY_DETECTOR_WEIGHTS` is not set or points to a missing file, and when free memory is below `NELLY_MIN_FREE_MEM_GB`. The checks only read; they never start a model and never print a secret.
