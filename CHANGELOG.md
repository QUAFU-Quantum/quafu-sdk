# Changelog

All notable changes to `quafu-sdk` are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Versioning: patch = bug fixes, following platform-side changes, and wording; minor = new features; major = may break the API (breaking changes are deprecated for one release first).

## [Unreleased]

### Added

- Public tasks (share a result). Owners: `job.publish(seq=0)` / `job.unpublish(seq=0)` / `job.publication(seq=0)`, and `quafu.publish(task_id)` / `quafu.unpublish(task_id)`, return a `Publication` with `public_id` and `url` (the share link). Anyone: `quafu.public_task(public_id_or_link)` returns a `PublicTask` whose `result` is the same `Result` the owner gets from `job.result()`, plus `executor` (real hardware or which simulator), `record`, `record_sha256`, `integrity` and `verify()`, which recomputes the record's SHA-256 locally and checks it against the result. Reading needs no login; if the platform is configured to require one (HTTP 401), the SDK retries with your saved credential. New exceptions `PublicTaskNotFound` and `NotPublishable` (`reason` is `not_finished` or `demo`).
  - Why: users want to share a computation so that others can see exactly what ran and what came back, e.g. task results cited in a paper. The platform gives each published task a random public ID (separate from the task ID, which is guessable) that stops working when the owner makes the task private.
  - `verify()` proves the record has not changed since publication; it is not a platform signature (planned separately).

### Changed

- Documentation only, no behavior change: the platform's Jiuding simulated chips (`<chip>-sim-jiuding`) now start on demand and are released after a few idle minutes, so their `status` in `devices()` can also be `standby` (no simulator running right now; one starts automatically when you submit). `devices()` already passed `status` through unchanged; its docstring and the README now list `standby` and state that submitting to a `standby` target is accepted normally instead of raising `DeviceUnavailable`. 0.2.7 keeps working against the platform; only its docstring lacks this value.

## [0.2.7] - 2026-10-13

### Added

- `devices()`: every row has a new key `limits` with the target's resource limits exactly as the platform reports them (the same object as `limits` in `GET {BASE_URL}/api/v1/backends/<target>/metadata`), or `None` if the platform does not provide them. The `metadata(target)` docstring and the README describe the keys of `limits`.
- Local pre-submit check against `limits`: `submit`, `sweep`, `open_job` and `job.append(circuits=...)` on a job group opened in the current process fetch the target's `limits` before sending the request (cached per platform URL and target for 10 minutes; a failed fetch is cached for 30 seconds). If the qubit count exceeds `max_qubits`, or `shots` is outside `min_shots..max_shots` or not a multiple of `shots_step`, they raise `PrecheckError` without contacting the submit endpoint. `category` matches the platform's (`precheck.simTooLarge`, `precheck.shotsOutOfRange`, `precheck.shotsGranularity`); `vars` carries the limit values, `limits_url` (the full URL to query the limits) and `local: True`; the message, in both languages, states the limit and the query URL.
  - Qubits are counted as the target's `qubit_count` says: `declared` is the sum of all `qreg` sizes, `active` is the qubits touched by gates (barriers do not count). Counting uses a small OpenQASM 2 scanner that does not need Qiskit; if it cannot count (no `qreg`, unsupported syntax) the qubit check is skipped. For Jiuding simulated chips the platform also counts qubits used by routing after transpilation, which is not visible locally, so the local count can only be lower than the platform's and never rejects a circuit the platform would accept.
  - If `limits` cannot be fetched (offline, HTTP 503, a target with no metadata such as `all-race`, or the platform does not report `limits`), the local check is skipped and the platform decides. The platform's check is always authoritative. Fetching `limits` uses the public endpoint without credentials and without retries. When not logged in, the not-logged-in error is raised first, before any network request for limits.
  - The Qiskit adapter's `backend.run` goes through `Client.submit` and gets the same check.
- `PrecheckError` raised by the platform for a limit violation (with `vars.limits_url`) now ends its message with the query URL.

### Changed

- Hard-coded limit values (shot ranges, qubit counts) were removed from docstrings and the README, which now point to `limits`; the README gains a table of the `limits` keys. Reason: the platform can adjust these limits at any time, and copies in the SDK went stale. A bundled fallback default was deliberately not added for the same reason.
- The full user guide moved to the documentation site, in English (<https://quafu.com.cn/en/docs/sdk>) and Chinese (<https://quafu.com.cn/docs/sdk>), covering overview, installation, quick start, login, Python usage, command line, configuration, errors and FAQ, plus API key management. `README.md` links to both; the separate `README.zh-CN.md` was removed so the Chinese text exists in one place only.

## [0.2.6] - 2026-10-13

### Added

- Jiuding simulated chips: noise-free simulators that behave like a specific real chip, available as targets `Baihua-sim-jiuding`, `Shenglian-sim-jiuding` and `Dongling-sim-jiuding`.
  - `devices()` lists them after the `<chip>-sim` rows, with `kind` `sim`, `status` as reported (`online` / `starting` / `offline`) and `queue` as the number of queued tasks. These rows have an extra key `max_qubits` (the maximum number of qubits a circuit may actually use). `n_qubits` is the real chip's qubit count, not `max_qubits`, because circuits use that chip's qubit numbering (physical qubit indices can exceed `max_qubits`); it matches `metadata()` and the Qiskit `Target`.
  - `submit(target=...)` accepts these names as-is; the docstring now mentions them.
  - Qiskit adapter: their metadata uses the same `coupling_map` / `basis_gates` as the real chip, plus `simulator: true`, `noise: 'none'` and `max_qubits`. `build_target` builds the `Target` from the chip graph, so local `transpile` routes on the chip's connectivity.
  - `DeviceUnavailable`: when no simulator is ready for a Jiuding simulated chip (platform returns 503 `runtime.deviceUnavailable` with `vars.device_status = offline`), the SDK rewrites the message in the UI language: no simulator is ready for that target right now, try again in a few minutes.

### Changed

- The warning about missing topology, previously shown only for non-simulator backends, is now also shown for noise-free backends tied to a real chip, since they are transpiled against the chip graph too.

## [0.2.5] - 2026-10-10

### Fixed

- Windows: a console whose window is hidden (for example started with `Start-Process -WindowStyle Hidden`) or that has no window at all (parent process used `CREATE_NO_WINDOW`) is now treated as non-interactive. Previously the SDK considered it interactive, so an unauthenticated `quafu whoami` printed a login link and waited at the authorization-code prompt for up to an hour. After `isatty()` and `GetConsoleMode` succeed, the SDK now also requires `GetConsoleWindow()` to return a window and `IsWindowVisible` to be true (new function `oauth.console_window_visible()`; standard-library `ctypes` only, handle types declared pointer-sized so they are not truncated on 64-bit). Any query failure counts as non-interactive. Minimized windows still count as visible; normal PowerShell, cmd, Windows Terminal and conhost windows remain interactive. POSIX is unchanged; notebooks still count as interactive.

## [0.2.4] - 2026-10-10

### Changed

- Browser login now waits up to one hour instead of 10 minutes (`LOGIN_TIMEOUT` 600 s → 3600 s). On timeout it raises `LoginFailed` ("browser login timed out (60 minutes)") with hints to rerun or use an API key. An explicit `quafu login` in a non-interactive environment still waits only for the local loopback callback, also for up to one hour.
- When not logged in (or the saved browser login has expired) in a non-interactive environment: Python still raises `NotLoggedIn` / `LoginExpired` (no `sys.exit`), and additionally logs one WARNING on logger `quafu` saying the SDK is not logged in and did not start a browser login. The `quafu` command line prints the explanation (both options: `quafu login` and `QUAFU_API_KEY`) to **stdout** instead of stderr, because scheduled tasks and background scripts often capture only stdout, and exits with code 1.

### Fixed

- Windows: with standard input redirected to `NUL` (`subprocess.DEVNULL`, scheduled tasks, background scripts, `< NUL`), an unauthenticated SDK no longer starts a browser login and hangs waiting for an authorization code. `NUL` is a character device, so `isatty()` is true for it; the SDK now additionally calls `GetConsoleMode` on standard input, which succeeds only for a real console (not for `NUL`, files or pipes). Any query failure counts as non-interactive. POSIX still uses `isatty()` only; notebooks still count as interactive.

## [0.2.3] - 2026-10-10

### Changed

- Follows the platform's new daily quota model: quotas reset every day at 23:00 Beijing time; each user has a normal quota and a daily hard limit per backend type. Tasks beyond the normal quota are still accepted but queued behind everyone's within-quota tasks; only the hard limit causes HTTP 429.
- `stats()` still returns the platform's statistics unchanged; its documentation now describes the new fields: `quota.date` (the quota day, switching at 23:00) and, per backend type, `{used, limit, hard_limit, remaining, degraded, resets_at}` — tasks submitted, normal quota, daily hard limit, remaining within the normal quota, whether further submissions are deprioritized, and the next reset time.
- `QuotaError`: when the daily hard limit is hit (`runtime.quotaExhausted` with `hard_limit`), the message is rewritten in the UI language: how many tasks were submitted today, the hard limit, the normal quota, that tasks above the normal quota are accepted at lowest priority, the reset time (Beijing time) and roughly how long until you can submit again. If a single submission alone exceeds the hard limit, it suggests splitting it; a hard limit of 0 means the backend type is currently not accepting tasks. `vars` is the platform's `{limit, hard_limit, used, remaining, requested, resets_at, wait_s}`; `retry_after` still reads the `Retry-After` header or a top-level `retry_after` in the body.

### Added

- `QuotaError.resets_at` (same as `vars['resets_at']`).

## [0.2.2] - 2026-10-09

### Fixed

- While waiting for the pasted authorization code, the prompt text can no longer be edited. The terminal's own line editing and echo are turned off (Ctrl+C still works) and the SDK manages the line itself: you can only type or paste at the end; Backspace deletes only what you typed; arrow keys and other control sequences are discarded entirely (also when split across reads), and clicking in the terminal no longer moves the cursor; Ctrl+U clears the line; Ctrl+D on an empty line is still EOF. The original terminal settings are restored afterwards. Non-terminal input (pipes, tests) is still read line by line; Windows uses its own character-by-character reader and is unaffected.
- Source comments in the distributed package no longer contain personal names or internal tracker references.

### Removed

- Versions 0.2.0 and 0.2.1 were deleted from PyPI because their packages contained such internal notes. These version numbers will not be reused.

## [0.2.1] - 2026-10-09

Deleted from PyPI on the same day (see 0.2.2).

### Changed

- WSL: login opens the Windows default browser (where you are usually already signed in to QUAFU) instead of a Linux browser inside WSL. WSL is detected via `WSL_DISTRO_NAME` or `microsoft` in the kernel version; the SDK uses `wslview` if available, otherwise Windows' `rundll32 url.dll,FileProtocolHandler`. No network-mode detection is done: if the loopback callback cannot be reached, pasting the authorization code still works. If Windows interop is disabled, the previous behavior is used.
- Browser output is discarded: browser processes started by the SDK have stdin/stdout/stderr connected to the null device, so browser startup logs no longer appear after the authorization-code prompt. Linux desktops use `xdg-open` (also silenced); macOS and Windows still use `webbrowser`.

### Fixed

- Clicking in the terminal while waiting for the authorization code no longer prints growing runs of `^[[D`: ECHOCTL is turned off during the prompt and restored afterwards, and such escape sequences are stripped from the line read.

## [0.2.0] - 2026-10-08

Deleted from PyPI on 2026-10-09 (see 0.2.2).

### Added

- Parameter sweeps: `quafu.sweep(template, parameters, points, target, …)`; the platform substitutes `{{name}}` placeholders in the template for each point.
- Iterative job groups: `quafu.open_job(target, template=None, parameters=None, …)` → `job.append(points=… | circuits=…, iteration, evaluation_index)`, `job.wait()` (returns for an open group once no task is running), `job.close()`. Appends carry an idempotency key.
- Result tables: `job.table(timeout=None, wait=True)` → `ResultTable` (columns aligned in submission order; `column`, `reordered`, `expectation_z`, `to_dict`, `to_pandas`), with automatic pagination.
- Result helpers: `Result.reorder`, `Result.expectation_z`, `Result.parameter_values` / `iteration` / `evaluation_index`; top-level `reorder_counts`, `counts_by_qubit`, `probabilities`, `expectation_z`.
- Devices and calibration: `quafu.device(name)` → `Device` (`.calibration()`), `quafu.calibration(id)` → `Calibration` (`qubit`, `coupler`, `measured_qubit`, `measured_coupler`, `grid`). Public data, no login needed.
- Usage statistics: `quafu.stats(days=30)`.
- Qiskit adapter `quafu.qiskit`: `QuafuProvider`, `QuafuBackend`, `QuafuJob`, `bind`, and `sweep(qc, points, target, …)`.
- `submit()` circuit items may be dicts `{"qasm", "shots", "name", "parameter_values", "metadata"}`, and `parameters=` declares parameters with units.
- Display language: English by default, Chinese available. Applies to all CLI output, login prompts and the callback page, expiry reminders, logging warnings, exception messages and the package-conflict notice. Precedence (high to low): `quafu.set_language('zh')` (current process only) > environment variable `QUAFU_LANG` (accepts forms like `zh_CN`) > the setting saved by `quafu config set language zh` (in `~/.quafu-sdk/config.json`, separate from credentials) > default `en`. The system locale is not consulted. New: `quafu.set_language`, `quafu.get_language`, and the command `quafu config get|set`.
- On the first interactive browser login (no language chosen yet), the prompt ends with a hint to switch language: typing a single `Z` (Chinese) or `E` (English) and Enter switches, saves, reprints the prompt and keeps waiting; on Windows a single keypress suffices if nothing else was typed. Authorization codes are never a single letter, so this does not conflict with pasting.
- Connection failures without a proxy now suggest setting `QUAFU_PROXY=host:port` if a proxy is needed.

### Changed

- `job.results()` on an open iterative job group fetches only new or unfinished tasks each time; tasks already in a terminal state are not fetched again.
- `quafu login` prints a single "Logged in" line (with login method and expiry date); `quafu.login()` in Python still prints its own line.
- The package-conflict notice gives copy-pasteable commands for the current OS only, based on uv: one block for macOS / Linux, and separate PowerShell (with `Set-ExecutionPolicy Bypass -Scope Process -Force`) and cmd blocks on Windows. The previous version started with `python -m venv`, which fails on systems without a `python` command.
- `README.md` is now in English (shown on PyPI); the PyPI summary is in English.

### Fixed

- Redirecting CLI output (e.g. `quafu --help > f.txt` or a pipe) on Windows with a non-Chinese code page (cp1252) no longer crashes with `UnicodeEncodeError`; the CLI entry point (including the early package-conflict path) sets stdout/stderr error handling to replace, so unencodable characters become `?`. The encoding itself is not changed.

## [0.1.0] - Unreleased

First version of `quafu-sdk` (never published to PyPI): maintain a login session and submit circuits / fetch results with one function call.

### Added

- Package `quafu-sdk`, import name `quafu`, command `quafu`. Credentials directory `~/.quafu-sdk/`; platform URL from `QUAFU_BASE_URL`, with a built-in default `https://quafu.com.cn` so it works right after installation (arguments and environment variables take precedence). The URL is the portal origin; the SDK builds the API paths itself.
- Two kinds of login:
  - Browser login (authorization code + PKCE S256). The local loopback callback and "copy the code shown on the web page back into the terminal" are awaited simultaneously, first one wins, so it works over SSH and in containers without detection. Tokens are valid for 90 days from authorization; a reminder appears 7 days before expiry; an expired login raises `LoginExpired`, a revoked one `LoginRevoked`. `logout()` calls the revocation endpoint before deleting local credentials.
  - API key (does not expire).
  - Precedence: argument > `QUAFU_API_KEY` > saved credentials. In non-interactive environments the SDK never waits for input and raises `NotLoggedIn`. Credentials are stored per platform URL; directory mode 0700, file mode 0600, atomic writes, symlinks refused.
- Top-level API: `login`, `logout`, `whoami`, `submit(circuit or list, target, shots, compiler, name)`, `job(job_id)`, `devices()`, `Client`. Job handles provide `status`, `wait`, `result`, `results`, `cancel`. `Result` carries counts, bit order, measurement mapping, the executed circuit, compiler echo and calibration ID. `compiler='qiskit'` (platform-side compilation) or `'none'` (pass physical circuits through). Circuits may be OpenQASM 2.0 text or a Qiskit `QuantumCircuit` (Qiskit is an optional dependency, `quafu-sdk[qiskit]`).
- No third-party runtime dependencies.
- Package-name conflict detection: another, older PyPI package also uses the import name `quafu`. Both import and the CLI detect it and raise an error explaining how to switch to a clean virtual environment, instead of running with overwritten files.
- Exceptions: `QuafuError` hierarchy including `ServerUnavailable` (with subclass `SubmitUncertain`); messages refer to "the platform" rather than to individual server components.
