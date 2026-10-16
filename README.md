# QUAFU SDK (Python)

Full guide: [English](https://quafu.com.cn/en/docs/sdk) · [中文](https://quafu.com.cn/docs/sdk)

Run quantum circuits on the real devices and simulators of the QUAFU quantum computing platform from Python, and fetch the results.

- Install: `uv pip install quafu-sdk` (or `pip install quafu-sdk`; in a Jupyter notebook: `%pip install quafu-sdk`)
- Import: `import quafu` (Qiskit backend adapter: `from quafu.qiskit import QuafuProvider`)
- Command line: `quafu login` / `quafu logout` / `quafu whoami` / `quafu config`
- Python 3.9 or later; no third-party runtime dependencies. To use Qiskit circuits as input, install `pip install "quafu-sdk[qiskit]"`.

## Quick start

```python
import quafu

bell = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""

job = quafu.submit(bell, target="sim", shots=1024)
print(job.result().counts)          # e.g. {'00': 517, '11': 507}
```

On first run, the SDK prints a login link and tries to open your browser. Log in to QUAFU on the web page and click "Authorize"; the program then continues automatically.

## Log in

The SDK supports two ways to log in.

| | Browser login | API key |
|---|---|---|
| How to get it | `quafu.login()` or `quafu login`, then authorize in the browser | Create one on the website account page |
| Validity | 90 days from authorization; log in again when it expires (no renewal) | Never expires until disabled or deleted on the website |
| Best for | Personal computers, everyday use | Servers, scheduled jobs, CI, shared environments |
| Allowed operations | Submit, query, and cancel your own tasks | Same |

Neither method can manage your account or API keys; that can only be done on the website.

### Browser login

```python
quafu.login()                       # returns immediately if already logged in with more than 7 days left
quafu.login(force=True)             # log in again (switch account or renew early)
quafu.login(open_browser=False)     # only print the link; don't open a browser
```

```bash
quafu login                 # same as quafu.login()
quafu login --force
quafu login --no-browser
```

During login the SDK waits for either of two completion paths; whichever finishes first wins:

- **Local browser**: open the link on this machine and authorize; the browser redirects back to the SDK automatically, nothing else to do. Under WSL the link opens in your Windows default browser.
- **Paste an authorization code**: in environments that can't redirect back to the local machine (SSH terminals, containers, remote Jupyter), the web page shows an authorization code after you authorize. Copy it, paste it into the terminal or notebook input box, and press Enter.

The wait lasts 1 hour; after that the login stops with a message telling you what to do next. When you are not logged in, the first call that needs a login (such as `submit()` or `whoami()`) starts a browser login automatically; in non-interactive environments (CI, background jobs, pipes, Windows scheduled tasks, standard input redirected from `NUL`, and on Windows a console whose window is hidden or absent) it raises `NotLoggedIn` right away instead of waiting for input, and logs a warning on the `quafu` logger. The `quafu` command in that case prints the message to standard output and exits with code 1; use an API key (`QUAFU_API_KEY`) there, or run `quafu login` in a terminal first.

Within 7 days of expiry, the SDK prints a reminder to standard error once per run. After expiry, run `quafu login` again; for long-running scripts, use an API key.

Example of a successful login:

```text
Logged in as 甲 (u7f3a9c2b)  browser login  expires: 2027-01-06
```

### API key

Create an API key (starting with `qf_`) on the website account page, then use any of the following:

```bash
export QUAFU_API_KEY=qf_xxxxxxxx          # environment variable; suited to servers and CI
```

```python
c = quafu.Client(api_key="qf_xxxxxxxx")   # pass explicitly; you can hold several Clients with different identities
quafu.login(api_key="qf_xxxxxxxx")        # save on this machine (verified with the platform first; not saved if verification fails)
```

```bash
echo "$KEY" | quafu login --api-key -     # read from standard input on the command line and save
```

### Which credential is used

The first one found, in this order, is used; they are never merged:

1. Passed explicitly: `quafu.Client(api_key=...)`
2. Environment variable `QUAFU_API_KEY`
3. Saved login (from browser login or a key saved with `login(api_key=...)`)
4. None of the above: start a browser login if interactive, otherwise raise `NotLoggedIn`

`quafu.whoami()` or `quafu whoami` shows the current account, credential kind (`api_key` / `oauth`), source (`argument` / `env` / `saved`), and expiry time. Credentials are only shown masked (e.g. `qf_AbCdEfGh...`) and never appear in logs or error messages.

### Log out

```python
quafu.logout()
```

```bash
quafu logout
```

For a browser login, the SDK first revokes the login on the platform, then deletes the saved login. The saved login is deleted even if the revoke request fails; in that case, revoke it under "Signed-in devices" on the website. If the saved credential is an API key, only the local copy is deleted and the key itself stays valid; to invalidate it, disable or delete it on the website account page.

### Saved location

The saved login is stored in `~/.quafu-sdk/credentials.json` (directory mode 0700, file mode 0600). Set the environment variable `QUAFU_CONFIG_DIR` to use another directory. One login is saved per platform URL.

**Shared environments**: every program running under the same system account can read this file. On servers or Jupyter kernels where several people share an account, use the `QUAFU_API_KEY` environment variable instead, and disable the key on the website when you are done.

## Display language

CLI messages, login prompts, and exception messages are in English by default. Chinese is also available. The SDK never switches language based on the system locale.

Ways to set it, highest precedence first:

1. In Python: `quafu.set_language('zh')`. Applies to the current process only and is not saved; `quafu.set_language(None)` clears it. `quafu.get_language()` returns the effective language.
2. Environment variable `QUAFU_LANG=zh` (or `en`). Forms such as `zh_CN`, `zh-CN`, `en_US`, and `zh_CN.UTF-8` are also accepted. Unrecognized values are ignored.
3. Saved setting: `quafu config set language zh` / `quafu config get language`. Stored in `~/.quafu-sdk/config.json` (same directory as the credentials, honors `QUAFU_CONFIG_DIR`), separate from credentials and shared across platform URLs.
4. Default: `en`.

**First login**: the browser-login prompt ends with a line in the other language. In English mode it is `使用中文请按 Z 并回车。`; in Chinese mode it is `Press E then Enter to set English as display language.` Typing just `Z` (or `E`), case-insensitive, and pressing Enter switches the language, saves it the same way as `quafu config set language`, reprints the prompt in the new language, and keeps waiting. On Windows a single keypress is enough when nothing else has been typed. Authorization codes are never a single letter, so this doesn't conflict with pasting a code. The hint line appears only while no language has been chosen (no environment variable, no saved setting) and only in interactive sessions; the keys work in any interactive login.

## Submit circuits

```python
job = quafu.submit(
    circuits,            # OpenQASM 2.0 text or qiskit.QuantumCircuit, or a list of them
    target="sim",        # where to run; see the table below
    shots=1024,          # number of runs per circuit
    compiler="qiskit",   # compilation mode; see the table below
    name=None,           # optional job name, shown under "My jobs" on the website
)
```

Each `submit()` creates one **job**; each circuit in the list is one **task** in the job, in submission order. `submit()` returns immediately without waiting for the run to finish.

**target**

| Value | Meaning |
|---|---|
| `"sim"` | Ideal simulator |
| `"<device>"`, e.g. `"Dongling"` | The named real device; never moved to another device |
| `"<device>-sim"`, e.g. `"Dongling-sim"` | Noisy simulation based on that device's calibration data |
| `"<device>-sim-jiuding"`, e.g. `"Baihua-sim-jiuding"` | Jiuding simulator: ideal (noiseless) simulation that follows that device's qubit numbering, connectivity and native gates |
| `"all-race"` | Send to all online real devices at once and take the first result to finish |
| `"all-redispatch"` | Send to one real device first, automatically moving to the next if it is unavailable |

Query available names and their current status with `quafu.devices()`:

```python
for d in quafu.devices():
    print(d["name"], d["kind"], d["status"], d["n_qubits"], d["queue"], d["limits"])
```

`kind` is `real` (real device) or `sim` (simulator); `queue` is the number of tasks queued ahead, or `None` if unknown. Querying devices does not require login.

`limits` is the target's resource limits as published by the platform — the single source for every limit; this README does not repeat the numbers. It is the same object as `limits` in `GET {BASE_URL}/api/v1/backends/<target>/metadata` (also `quafu.Client().metadata(target)["limits"]`):

| Key | Meaning |
|---|---|
| `max_qubits` | Qubit limit, counted as `qubit_count` says: `declared` = the circuit's declared width, `active` = qubits touched by gates |
| `min_shots` / `max_shots` / `shots_step` | Allowed shots: between min and max, and a multiple of step |
| `max_depth` | Circuit depth limit (`None` = not limited by depth) |
| `wall_s` | Wall-clock limit per task in seconds (`None` for real devices) |
| `max_tasks_per_job` | Most tasks in one job |
| `method` | `statevector`, `noise_model` or `hardware` |

Before sending a submission, the SDK reads the target's `limits` (cached in the process) and, if the qubit count or shots exceed them, raises `PrecheckError` locally with the limit and the query URL in the message (`vars["local"]` is `True`). If the limits cannot be read, the check is skipped and the platform decides.

Jiuding simulator rows (`<device>-sim-jiuding`) also carry `max_qubits`: at most this many qubits may take part in the computation (see `limits`), while `n_qubits` is the real device's qubit count (the range of qubit numbers). Their `status` is `online`, `standby` (nobody is using the simulator, so it holds no compute; submit as usual and it starts automatically — the first task waits a little longer), `starting` (submissions are accepted and wait until the simulator is ready) or `offline` (submitting raises `DeviceUnavailable`). Submitting requires login and counts toward the ideal-simulation quota.

**shots**: the allowed range and step depend on the target (real devices require a multiple of a fixed step); see the target's `limits`. Out-of-range shots raise `PrecheckError`.

**compiler**

| Value | Meaning |
|---|---|
| `"qiskit"` (default) | The platform compiles the circuit for the target chip. Write a logical circuit and declare only the qubits you use |
| `"none"` | No compilation; runs as is. The circuit must already be a physical circuit for this chip, with qubit indices matching the chip's numbering |

The compiler and version actually used are echoed in the result's `compiler` field.

**Qiskit circuits**

```python
from qiskit import QuantumCircuit

qc = QuantumCircuit(2, 2)
qc.h(0)
qc.cx(0, 1)
qc.measure([0, 1], [0, 1])
job = quafu.submit(qc, target="sim")
```

The SDK uses Qiskit to export the circuit to OpenQASM 2.0 before submitting, and sorts the trailing measurement statements by classical bit in ascending order (required by real devices). Circuits with unbound parameters must be bound with `assign_parameters` before submission.

## Fetch results

```python
job.id                       # job ID; after the program exits, reattach with quafu.job(job.id)
job.status()                 # Queued / Running / Finished / PartiallyFinished / Failed / Cancelled
r = job.result(timeout=600)  # single circuit: wait until done, return a Result
rs = job.results()           # multiple circuits: return a list of Results in submission order
job.cancel()                 # cancel tasks that have not finished
job = quafu.job("u7f3a9c2b-261008-153000")   # reattach by job ID (only your own jobs)
```

- `result()` is only for jobs with a single circuit; it raises `JobFailed` on failure and `JobCancelled` if cancelled.
- `results()` does not raise when individual circuits fail: failed ones have `counts` set to `None`, and `status` and `error` explain why.
- If the job doesn't finish within `timeout` seconds, `Timeout` is raised; the job remains on the platform, and you can call again to keep waiting. Ctrl-C only stops waiting; it does not cancel the job.
- `cancel()` returns the platform's response: `cancelled_now` is the number of tasks cancelled outright; `cancel_requested` is the number already sent to a real device, for which waiting can only be stopped (quota already consumed is not refunded). Tasks whose results are being fetched are not cancelled and produce results as usual.

**Result**

| Field | Meaning |
|---|---|
| `counts` | Raw counts `{bitstring: count}`; `None` if unsuccessful |
| `bit_order` | Bit order; `"c0_rightmost"` means the rightmost character of the bitstring is classical bit `c[0]` |
| `n_clbits` | Number of classical bits |
| `shots_requested` / `shots_returned` | Shots requested / shots actually counted (normalize with the latter) |
| `probabilities()` | Probabilities normalized by `shots_returned` |
| `measurements` | `[{cbit, physical_qubit, virtual_qubit}]`: which physical qubit each classical bit measured |
| `counts_by_qubit([…])` / `reorder(…)` / `expectation_z(…)` | Counts rearranged by physical qubit or classical bit, Z-string expectation values; see "Per-qubit data" |
| `executed_qasm` | The circuit actually run |
| `compiler` | Compiler used: `{name, version, optimization_level, seed}` |
| `calibration_id` | ID of the calibration data used for this run (`None` for ideal simulation) |
| `target` / `backend` | Submitted target / backend actually used (for `all-race` and similar, the real device it landed on) |
| `status` / `ok` / `error` | Status of this task; failure reason `{category, stage, retryable, detail, vars}` |
| `parameter_values` | Parameter values for this task (sweeps, iterations, parameterized circuits); `None` if there are none |
| `iteration` / `evaluation_index` | Round and evaluation index in an iterative job |
| `task_id` / `raw` | Task ID; full details returned by the platform |

## Parameter sweeps

In a circuit template, write gate parameters as `{{param_name}}`, then provide a set of parameter points. The platform substitutes each point in turn; each point is one task in the job:

```python
template = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[1];
creg c[1];
rx({{theta}}) q[0];
measure q[0] -> c[0];
"""
job = quafu.sweep(template, parameters=[("theta", "rad")], points=[0.0, 0.5, 1.0], target="sim")
t = job.table()
t.column("theta")          # [0.0, 0.5, 1.0]
t.expectation_z([0])       # <Z> at each point
```

- `parameters`: name and unit of each parameter (`"rad"`, `"ns"`, etc.; `"1"` for dimensionless). The order defines the column order of each row in `points`.
- `points`: table of parameter points, as a nested list or numpy array; with a single parameter, each row can be a single number.
- Other arguments (`shots`, `compiler`, `name`) are the same as for `submit()`.

You can also substitute locally and submit a list of circuits, labeling each with its parameter values: `quafu.submit([{"qasm": ..., "parameter_values": {"theta": 0.5}}, ...], target, parameters=[("theta", "rad")])`. For Qiskit parameterized circuits, see "Qiskit" below.

## Iterative jobs

Variational algorithms (VQE, QAOA, etc.) need to "look at this round's results before deciding the next round". Open an iterative job and append round by round:

```python
job = quafu.open_job("sim", template=template, parameters=[("theta", "rad")], name="VQE")
theta = 0.1
for k in range(10):
    job.append(points=[[theta]], iteration=k)
    job.wait()                                  # returns when no tasks are queued or running
    z = job.results()[-1].expectation_z([0])
    theta = theta - 0.1 * z                     # illustration: update the parameter from the result
job.close()                                     # close when done; no more appends afterwards
```

- `append(points=...)` substitutes into the template (the job must be opened with `template` and `parameters`); `append(circuits=[...])` appends circuits directly (text, Qiskit circuits, or circuit items with `parameter_values`).
- `iteration` is the round number and `evaluation_index` the evaluation number within the round; both appear in the results.
- Append requests carry an idempotency key, so automatic retries after a lost response never append twice. Appending to a closed job raises `JobClosed`.

## Result tables

`job.table()` returns a columnar table (`ResultTable`) with rows aligned in submission order, suited to sweeps and iterations:

| Column | Meaning |
|---|---|
| `seq` / `task_ids` | Sequence number / task ID |
| `points`, `column("param_name")` | Parameter values of each row |
| `status` / `counts` / `shots_returned` | Status, counts, and shots actually counted per row; `counts` is `None` for unsuccessful rows |
| `iterations` / `evaluation_index` | Round and evaluation index in an iterative job |
| `errors` | Reasons for unsuccessful rows |

`t.probabilities()`, `t.reordered(order)`, and `t.expectation_z(cbits)` compute row by row; `t.to_dict()` or `t.to_pandas()` (requires pandas) converts to a table. `job.table(wait=False)` returns the current snapshot immediately, useful for inspecting progress during iterations.

## Per-qubit data

Both `Result` and `ResultTable` carry a bit-order declaration (`bit_order`) and a measurement mapping (`measurements`), so conversions are direct:

```python
r.reorder([1, 0])            # bitstring reads c[1], c[0] from left to right; listing only some bits gives a marginal distribution
r.reorder("c0_leftmost")     # switch to c[0] on the far left
r.counts_by_qubit([108, 109])# select by physical qubit
r.expectation_z([0, 1])      # Z⊗Z expectation value (computed from raw counts only)
```

Functions of the same names are also available at the top level: `quafu.reorder_counts`, `quafu.counts_by_qubit`, `quafu.probabilities`, `quafu.expectation_z`.

## Devices and calibration data

```python
d = quafu.device("Dongling")        # status, qubit count, queue length, current calibration ID
cal = d.calibration()               # current calibration data
cal.qubit(5)["t1_us"]               # T1 of qubit 5 (microseconds)
cal.coupler(5, 6)["cz_fidelity"]    # CZ gate fidelity between qubits 5 and 6
cal.measured_qubit(5)               # readout data measured by the platform
quafu.calibration(r.calibration_id) # the calibration data used by a given run (immutable, retrievable long-term)
```

Field names include units (e.g. `t1_us`); fidelities are decimals from 0 to 1; values not measured or not filled in are `None`. Querying devices and calibration data does not require login.

## Usage statistics

```python
quafu.stats(days=30)     # your task count, shots, daily breakdown, quota and runtime over the last 30 days
```

Quotas are counted per backend (`sim` / `noisy` / `real`) per day, and reset at 23:00 Beijing time. Each backend has two numbers:

- **Normal quota** (`limit`): tasks beyond it are still accepted and run, but at the lowest priority — they are dispatched only when nobody has a within-quota task waiting. No error is raised.
- **Daily hard cap** (`hard_limit`): only when you reach it is a submission rejected with `QuotaError`, until the next reset.

```python
q = quafu.stats()["quota"]["real"]
q["used"], q["limit"], q["hard_limit"]   # submitted today / normal quota / daily hard cap
q["remaining"]                           # tasks left within the normal quota (never below 0)
q["degraded"]                            # True: tasks you submit now run at the lowest priority
q["resets_at"]                           # next reset, e.g. "2026-10-10T23:00:00+08:00"
```

## Qiskit

```python
from qiskit import QuantumCircuit, transpile
from quafu.qiskit import QuafuProvider, sweep

backend = QuafuProvider().get_backend("sim")         # "sim", "<device>-sim", "<device>-sim-jiuding", or "<device>"
job = backend.run(transpile(qc, backend), shots=1024)
job.result().get_counts()

job = sweep(qc_with_parameters, points, "sim")       # parameterized circuit: substituted point by point locally, submitted as one job
job.table().column("theta")
```

- The backend's gate set and topology come from the platform; `backend.run()` submits all circuits as one job. When some circuits fail, the failed experiments have `success=False`.
- `sweep()` keeps the parameter names from Qiskit; the unit defaults to `"rad"`.
- Requires `pip install "quafu-sdk[qiskit]"`.

## Platform URL

By default the SDK connects to `https://quafu.com.cn`. To connect to another deployment:

```python
c = quafu.Client(base_url="https://example.org")
```

```bash
export QUAFU_BASE_URL=https://example.org
quafu --base-url https://example.org whoami
```

Precedence: argument > environment variable `QUAFU_BASE_URL` > default URL. Give the host only (no path), and it must be https, except for local loopback addresses (`http://127.0.0.1:<port>`).

## Network

- Certificates are always verified; there is no option to disable verification. For deployments with self-signed certificates, specify the CA certificate with `Client(ca_bundle="ca.pem")` or the environment variable `QUAFU_CA_BUNDLE`.
- System proxy settings are not used by default. To use a proxy, specify an HTTP proxy with `Client(proxy="host:port")` or the environment variable `QUAFU_PROXY`.
- Read requests are retried automatically on network errors or platform 5xx responses; submissions carry an idempotency key, so retries after a lost response never submit twice.

## Errors

All exceptions inherit from `quafu.QuafuError`; error messages explain the cause and what to do.

| Exception | When it occurs |
|---|---|
| `NotLoggedIn` | No credentials, and the environment is not interactive |
| `LoginFailed` | Browser login did not complete: authorization denied, timed out, or invalid authorization code |
| `LoginExpired` | The saved browser login has expired |
| `LoginRevoked` | The platform rejects the credential: the login was revoked, or the API key was disabled or deleted |
| `PrecheckError` | The platform rejected the circuit or parameters; `category` and `vars` give the specific reason |
| `QuotaError` | Daily hard cap or another limit reached; `retry_after` is the suggested wait in seconds, `resets_at` the next quota reset, `vars` the details. Going over the normal quota does not raise — those tasks just run at the lowest priority |
| `JobFailed` / `JobCancelled` | Circuit run failed / was cancelled; `retryable` indicates whether resubmitting unchanged makes sense |
| `JobNotFound` | The job does not exist or does not belong to the current account |
| `JobClosed` | Appending tasks to a closed or non-iterative job |
| `Timeout` | Waiting exceeded `timeout` |
| `ServerUnavailable` | Cannot connect to the platform, or the platform is temporarily unavailable |

## FAQ

**`import quafu` reports "another package occupying the quafu name", or `quafu.login` is missing after import**

The current Python environment has another package installed that also uses the name `quafu`, and the two overwrite each other's files. Create a clean virtual environment with [uv](https://docs.astral.sh/uv/) and install again. The error message shows only the commands for your system; each block below can be pasted as-is.

macOS / Linux:

```bash
uv venv quafu-env
source quafu-env/bin/activate
uv pip install quafu-sdk
```

Windows PowerShell (the second line lets this window run `Activate.ps1`):

```powershell
uv venv quafu-env
Set-ExecutionPolicy Bypass -Scope Process -Force
quafu-env\Scripts\Activate.ps1
uv pip install quafu-sdk
```

Windows cmd:

```bat
uv venv quafu-env
quafu-env\Scripts\activate.bat
uv pip install quafu-sdk
```

**`NotLoggedIn` when running on a server or in CI**

These environments are not interactive, so no browser login is started. Create an API key on the website account page and set the environment variable `QUAFU_API_KEY`.

**The browser doesn't redirect back after browser login**

This is expected in remote terminals, containers, or remote Jupyter. Copy the authorization code shown on the web page, paste it into the terminal or notebook input box, and press Enter.

## License

MIT
