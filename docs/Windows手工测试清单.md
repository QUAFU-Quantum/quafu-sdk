# quafu-sdk Windows 11 手工测试清单

照着从上往下走一遍，大约一个半小时；最后第 10 项跑自动化测试，第一次要下载依赖，再留二十分钟左右。目的是确认 quafu-sdk 在 Windows 11 上和 WSL、macOS、Linux 一样好用：同一件事不能多一步，也不能多一处让人困惑的地方。

- 只测、不改代码。发现问题记下现象，修不修由 SDK 维护者定。
- 用你自己的 QUAFU 账号（正式账号，不能是游客），往理想模拟器 `sim` 交的任务不花真机额度。
- 每一步都写了「预期」。和预期不一样就记「不通过」，并把终端里的原文复制下来。
- 贴结果前先遮掉：授权码、API Key、账号那一行（名字和编号）。
- 界面默认是英文。第 2 项第一次登录时按提示切成中文，后面各项的「预期」都按中文写；错过了就执行 `quafu config set language zh`。

## 一、要走的两个组合

| 组合 | Python | 安装方式 | 终端 |
|---|---|---|---|
| W1 | 最新版（3.13） | uv | PowerShell 走全部九项；cmd 再走第 1、2、3、4、7 项 |
| W2 | 3.9 | pip（在 uv 建的环境里用 pip 装） | cmd 走第 1、2、3、5、7 项 |

开始前先记一行环境：Windows 版本（`winver`）、终端（Windows Terminal 还是老式黑框；PowerShell 用 `$PSVersionTable.PSVersion` 看版本）、代码页（`chcp`，一般是 936）、`uv --version`。

## 二、准备

1. 没有 uv 的话装一个，任选一种：
   - `winget install --id=astral-sh.uv -e`
   - `pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple`
2. 装 Python：`uv python install 3.13 3.9`。下载不动就去 python.org 下载 3.13 和 3.9.13 的安装包，安装时勾上「Add python.exe to PATH」。
3. 准备 quafu-sdk 的安装包。测已发布的版本时，后面的 `<安装包>` 直接写 `quafu-sdk`；测仓库里还没发布的代码时，在仓库根目录（先 `git pull` 到最新 main）执行：

   PowerShell：
   ```powershell
   uv build --wheel . -o $env:USERPROFILE\quafu-wheel
   dir $env:USERPROFILE\quafu-wheel
   ```
   cmd：
   ```bat
   uv build --wheel . -o %USERPROFILE%\quafu-wheel
   dir %USERPROFILE%\quafu-wheel
   ```
   预期：出现 `quafu_sdk-<版本>-py3-none-any.whl`（`<版本>` 是 `pyproject.toml` 里的 `version`）。后面的 `<安装包>` 写这个文件的完整路径。
4. 下载慢的话，在 `pip install` / `uv pip install` 后面加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
5. 在桌面建一个名字带中文和空格的目录 `量子 测试`，后面的环境都建在这里（顺带测第 6 项「路径里有中文和空格」）。

## 三、逐项检查

### 1. 安装、`quafu --help`、PATH

W1（PowerShell）：
```powershell
cd "$env:USERPROFILE\Desktop\量子 测试"
uv venv -p 3.13 w1
.\w1\Scripts\Activate.ps1
uv pip install <安装包>
quafu --version
quafu --help
(Get-Command quafu).Source
```
- 预期：`quafu-sdk <版本>`；帮助是英文（还没切中文）；最后一行是 `…\量子 测试\w1\Scripts\quafu.exe`。
- 如果 `Activate.ps1` 报「在此系统上禁止运行脚本」，把原文记下来，再执行 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 继续。这一条要记（冲突提示与 README「常见问题」的 PowerShell 那块已带上这一行）。

W1（cmd，新开一个 cmd 窗口）：
```bat
cd /d "%USERPROFILE%\Desktop\量子 测试"
w1\Scripts\activate.bat
quafu --version
where quafu
```

W2（cmd）：
```bat
cd /d "%USERPROFILE%\Desktop\量子 测试"
uv venv -p 3.9 --seed w2
w2\Scripts\activate.bat
python -V
pip install <安装包>
quafu --version
where quafu
```
- 预期：`Python 3.9.x`；pip 装完能直接敲 `quafu`。

另做一次不建虚拟环境的装法（很多新手这么装）。这一步要用 python.org 装的 Python；只有 uv 装的 Python 时跳过，记「没做」。开一个没激活任何环境的 cmd：
```bat
py -3.13 -m pip install --user <安装包>
quafu --version
```
- 记下 pip 有没有提示「Scripts 目录不在 PATH 里」，以及 `quafu` 能不能直接敲。敲不了就记「不通过」，并记下 pip 的提示原文。

### 2. 网页登录

在 W1（PowerShell）里：
```powershell
quafu login
```
- 这是第一次登录，终端里的提示是英文，其中有一行中文「使用中文请按 Z 并回车。」。浏览器打开后**先别点授权**，回到终端只按一下 Z。预期：不用回车，提示马上换成中文重打一遍，接着等授权。记下按 Z 之后有没有反应、要不要回车。
- 然后回浏览器继续。预期：自动打开默认浏览器到 QUAFU 授权页；登录后点「授权」，浏览器显示「登录成功」，终端出现「已在浏览器中完成授权。」和**一行**「已登录：…  网页登录  有效期至 …」（以前会连着打两行）。
- 记下：有没有弹出 Windows 防火墙或安全提示。

粘贴授权码：
```powershell
quafu logout
quafu login --no-browser
```
- 预期：只打印链接，不开浏览器。把链接复制到浏览器，授权后页面显示授权码；复制授权码，粘贴到终端的「授权码：」后面，回车，显示「已登录」。
- 记下：在 PowerShell 和 cmd 里各怎么粘贴的（Ctrl+V 还是右键），有没有粘出多余字符。

Ctrl+C：
```powershell
quafu login --no-browser
```
- 在「授权码：」那里按 Ctrl+C。预期：一两秒内回到提示符，显示「已中断」，没有 `Traceback`。
- 再执行 `quafu login --force`，浏览器打开后不点授权，回到终端按 Ctrl+C，预期同上。

在 cmd（激活 w1）里把上面三段各走一次。

### 3. whoami 和 logout

```powershell
quafu whoami
quafu logout
quafu whoami
```
- 预期：第一次显示账号、平台、「网页登录 qf_…（来自本机保存的登录态）」和「有效期至」。
- logout 显示「已退出登录，本机登录态已删除。平台上的本次登录已撤销。」
- 再次 whoami 时会重新要求登录：打印登录链接并等待。按 Ctrl+C 退出即可。

**3b. 没人在电脑前时不等登录**（未登录状态下做；0.2.5 起）。先在 PowerShell 里设一个空的凭证目录，确保未登录：`$env:QUAFU_CONFIG_DIR = "$env:TEMP\quafu-empty"; Remove-Item Env:QUAFU_API_KEY -ErrorAction SilentlyContinue`。

为免误开浏览器，先只问判定、不发起登录：在下面每种启动方式里跑 `python -c "from quafu import oauth; open(r'<结果文件>','w').write(str(oauth.interactive()))"`，读结果文件。

| 启动方式 | `interactive()` 应为 | 之后跑 `quafu whoami`（输出重定向到文件）应 |
|---|---|---|
| `cmd /c "… < NUL"` | False | 立即退出，退出码 1，stdout 有「未登录」说明，不打出登录链接 |
| `echo. \| …`（管道） | False | 同上 |
| `Start-Process cmd -ArgumentList '/c …' -WindowStyle Hidden`（窗口隐藏） | False | 同上 |
| 父进程用 `subprocess.Popen([...], creationflags=subprocess.CREATE_NO_WINDOW)` 启动（没有窗口） | False | 同上 |
| 新开的 PowerShell 窗口、cmd 窗口、Windows Terminal 窗口里直接运行 | True | 不用跑（会发起网页登录） |

判定为 True 的那几行只看判定，不跑 whoami。

### 4. API Key

先在网站「个人中心 › API 与授权」用你自己的账号新建一把 Key，复制下来。

PowerShell：
```powershell
quafu logout
$env:QUAFU_API_KEY="qf_你的Key"
quafu whoami
```
cmd（注意等号两边不加空格、不加引号）：
```bat
quafu logout
set QUAFU_API_KEY=qf_你的Key
quafu whoami
```
- 预期：凭证一行是「API Key qf_xxxxxxxx...（来自环境变量 QUAFU_API_KEY）」，有效期「不过期」，屏幕上看不到完整的 Key。
- 然后在网站上停用这把 Key，再 `quafu whoami`。预期：一句话说明这把 Key 不被平台认了（已停用或删除），没有 `Traceback`。
- 测完清掉环境变量：PowerShell `Remove-Item Env:QUAFU_API_KEY`，cmd `set QUAFU_API_KEY=`。不再用的话，在网站上把 Key 删掉。

### 5. 往 sim 交 Bell 线路

先 `quafu login` 登录好。在 `量子 测试` 目录里新建 `bell.py`，内容：
```python
import quafu
bell = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n'
job = quafu.submit(bell, target="sim", shots=1024, name="Windows 测试")
print(job.result(timeout=180).counts)
```
```powershell
python bell.py
```
- 预期：一两秒到半分钟内打印类似 `{'00': 517, '11': 507}`，只有 00 和 11，各约一半。

Qiskit（只在 W1 做）：
```powershell
uv pip install "<安装包>[qiskit]"
```
如果 `<安装包>` 是文件路径，写成 `"C:\…\quafu_sdk-<版本>-py3-none-any.whl[qiskit]"`，要带引号。再新建 `qbell.py`：
```python
import quafu
from qiskit import QuantumCircuit
qc = QuantumCircuit(2, 2); qc.h(0); qc.cx(0, 1); qc.measure([0, 1], [0, 1])
print(quafu.submit(qc, target="sim", shots=1024).result(timeout=180).counts)
```
- 预期同上。

### 6. 凭证文件

```powershell
dir "$env:USERPROFILE\.quafu-sdk"
icacls "$env:USERPROFILE\.quafu-sdk\credentials.json"
```
- 预期：登录后有 `credentials.json`。`icacls` 列出的只有你自己、SYSTEM、Administrators，没有 `Everyone`、`Users`、`Authenticated Users`。把 `icacls` 的输出原样贴上来（里面的用户名可以遮掉）。

换一个带中文和空格的凭证目录：
```powershell
$env:QUAFU_CONFIG_DIR="$env:USERPROFILE\Desktop\量子 测试\凭证 目录"
quafu login
quafu whoami
dir "$env:QUAFU_CONFIG_DIR"
Remove-Item Env:QUAFU_CONFIG_DIR
```
- 预期：登录正常，whoami 正常，文件落在那个目录里。这个目录里没有语言设置，这一步的输出是英文，登录提示末尾又会出现「按 Z」那一行，不用管。
- 另外记下：你的 Windows 用户名里有没有中文或空格。有的话，前面所有步骤本身就测过了这一点。

### 7. 中文不乱码（GBK）

在 cmd（老式黑框更好，代码页 936）和 PowerShell 里各执行：
```bat
chcp
quafu --help
quafu whoami
quafu --help > help.txt
python bell.py > bell.txt
```
- 预期：屏幕上的中文正常；没有 `←[1;34m` 这类方括号乱码；两个输出文件用记事本打开，中文正常；没有 `UnicodeEncodeError`。
- 英文版 Windows（代码页 1252）重定向到文件时写不出中文，预期是中文变成 `?`、退出码照常，**不出 `UnicodeEncodeError` 和 `Traceback`**（0.2.0 起）。
- 再 `chcp 65001` 切到 UTF-8，执行 `quafu --help` 看一眼，最后 `chcp 936` 切回来。

### 8. 同一环境里装了旧的 pyquafu

pyquafu 没有 Python 3.14 的安装包，用 3.12：
```powershell
cd "$env:USERPROFILE\Desktop\量子 测试"
uv venv -p 3.12 w8
.\w8\Scripts\Activate.ps1
uv pip install <安装包>
uv pip install pyquafu
quafu whoami
python -c "import quafu; print(hasattr(quafu, 'submit'))"
```
- 预期：`quafu whoami` 输出一段话「检测到当前 Python 环境里还装了另一个占用 quafu 名字的包（pyquafu …）…」，没有 `Traceback`。`python -c` 打印 `False`（导入的是旧包，这一点 README「常见问题」里写了）。
- 再把顺序反过来试一次：新建 `w8b`，先 `uv pip install pyquafu`，再装 `<安装包>`，最后 `quafu whoami`。预期同上。

然后把那段说明里给的命令照抄一遍：Windows 上它分 PowerShell 和 cmd 两块，在一个没激活任何环境的 PowerShell 里抄 PowerShell 那块，在一个没激活任何环境的 cmd 里抄 cmd 那块：
```powershell
uv venv quafu-env
Set-ExecutionPolicy Bypass -Scope Process -Force
quafu-env\Scripts\Activate.ps1
uv pip install quafu-sdk
```
```bat
uv venv quafu-env
quafu-env\Scripts\activate.bat
uv pip install quafu-sdk
```
- 预期：每一行都能直接用，不调 `python`、不撞执行策略；提示里只有 Windows 的两块，没有 `source …`。PyPI 上还没有 quafu-sdk 的话，最后一行失败属正常，记一句即可。

### 9. 代理

SDK 默认不读系统代理。
1. 直连能上网时：在「设置 › 网络和 Internet › 代理」里打开「使用代理服务器」，地址填 `127.0.0.1`，端口填 `9`（故意填一个不通的），保存后执行 `quafu whoami`。预期：照常显示账号，说明 SDK 没用系统代理。**做完立刻关掉这个代理设置。**
2. 指定一个不通的代理：
   ```powershell
   $env:QUAFU_PROXY="127.0.0.1:9"
   quafu whoami
   Remove-Item Env:QUAFU_PROXY
   ```
   预期：一句话「连不上平台 quafu.com.cn（…，经代理 127.0.0.1:9）」，没有 `Traceback`。
3. 如果你平时用代理软件（比如 Clash 的 7890 端口），设 `$env:QUAFU_PROXY="127.0.0.1:7890"` 再 `quafu whoami`。预期：照常显示账号。

### 10. 自动化测试

上面第 1、6、7、9 项里不需要账号和浏览器的部分写成了只在 Windows 上跑的测试，这里连同 SDK 原有的单元测试和依赖切割测试一起跑，Python 3.14 和 3.9 各一遍。测试都在临时目录里进行，不连平台、不用你的账号，本机已保存的登录不会被改动；其中一条会在你的用户目录下临时建一个 `quafu-sdk-test-…` 目录，跑完自己删掉。

在 PowerShell 里，在仓库根目录（先 `git pull` 到最新 main）执行：
```powershell
uv run --python 3.14 --group dev pytest tests/unit tests/windows tests/deps -rs
uv run --python 3.9 --group dev pytest tests/unit tests/windows tests/deps -rs
```
- 没装 3.14 的话 uv 会自己下载。依赖切割测试会临时建几个虚拟环境、下载旧的 pyquafu 来比对，不影响你自己的环境。
- 预期：两遍的最后一行都是「N passed, M skipped」（数字不用对），没有 failed 或 error。skipped 是只在别的系统上跑的用例，正常。
- 有 failed 或 error 的，把 `FAILED` / `ERROR` 那几行和上面对应的报错段落原样贴上来。

## 四、怎么记、贴在哪

在仓库开一个 GitHub Issue（已有对应的测试 Issue 就回在那里），贴下面这张表。每格写「通过」或「不通过：现象」，没做的写「没做：原因」。

| 项 | W1 PowerShell | W1 cmd | W2 cmd |
|---|---|---|---|
| 1 安装、--help、PATH |  |  |  |
| 1b 不建环境 `--user` 安装 | — | 写在这里 | — |
| 2 首次登录按 Z 切中文 |  | — | — |
| 2 自动开浏览器登录 |  |  |  |
| 2 粘贴授权码 |  |  |  |
| 2 Ctrl+C |  |  |  |
| 3 whoami / logout |  |  |  |
| 4 API Key（设上、停用后被拒） |  |  | — |
| 5 Bell → sim |  | — |  |
| 5 Qiskit 输入 |  | — | — |
| 6 凭证位置、权限、中文空格目录 |  | — | — |
| 7 中文不乱码 |  |  |  |
| 8 装了旧 pyquafu |  | — | — |
| 9 代理 |  | — | — |
| 10 自动化测试（3.14） |  | — | — |
| 10 自动化测试（3.9） |  | — | — |

表下面附上：
- 开头那一行环境；
- 每个「不通过」的终端原文（遮掉授权码、Key、账号）；
- 第 6 项 `icacls` 的输出、第 8 项那三行命令逐行的结果；
- 第 10 项两遍各自的最后一行。

拿不准算不算问题的，也写上，注一句「拿不准」。

自动化测试模拟不可交互调用时，标准输入使用已关闭的空管道（`input=b''`）。Windows 的 NUL 会让 `isatty()` 返回 True；0.2.3 及以前 SDK 只看 `isatty()`，未登录的 `whoami < NUL` 会进入网页登录等待。0.2.4 起 SDK 另用 `GetConsoleMode` 判断是不是真的控制台，NUL 判为不可交互（`tests/windows/test_win_cli.py` 有一条专门用 DEVNULL 核对）；0.2.5 起还要求控制台窗口存在且可见（`GetConsoleWindow` + `IsWindowVisible`），窗口隐藏或没有窗口的控制台也判为不可交互，这一项靠上面第 3b 项手工核对。其余子进程测试仍用空管道。
