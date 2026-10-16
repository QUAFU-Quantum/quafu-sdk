# quafu-sdk · 协作规则

QUAFU 量子计算云平台的 Python SDK：PyPI 分发名 `quafu-sdk`，导入名 `quafu`，命令行 `quafu`。人和 agent 都按本文协作；`CLAUDE.md` 只引用本文。

用户手册在 <https://quafu.com.cn/docs/sdk>（英文 <https://quafu.com.cn/en/docs/sdk>）；`README.md` 是 PyPI 页面，英文。

## 开发

```bash
uv run --group dev pytest -q                     # 单元测试 + 依赖切割（tests/deps/ 要联网，离线时自动跳过）
uv run --group dev pytest tests/unit tests/windows tests/deps -rs   # Windows 上
```

- 工具链用 [uv](https://docs.astral.sh/uv/)；`uv.lock` 入库，改依赖后一并提交。
- `tests/contract/` 对着一份真的任务分发器（平台服务端）跑，服务端源码不在本仓库：设 `QP_DISPATCHER_DIR` 指向它的源码目录才跑，否则整组跳过。平台维护方在服务端改接口时会拉本仓库跑这一组。
- `tests/windows/` 只在 Windows 上跑；GitHub Actions 的 windows job 覆盖 Python 3.9 与 3.14。手工测试步骤见 `docs/Windows手工测试清单.md`。
- 一个 PR 一个可验收的改动，直接向 `main` 提；CI 绿了再合。改行为的 PR 在同一个提交里改测试与文档。

## 规矩

1. **运行时零依赖。** 只用标准库；qiskit 只作可选依赖（`quafu-sdk[qiskit]`）。增加运行时依赖要维护者同意，并同步 `tests/unit/test_boundary.py` 与 `tests/deps/`。
2. **导入名 `quafu` 与 PyPI 上一个旧包相同**，SDK 导入时检测并报错。`src/quafu/` 下新增模块要同步 `_conflict.OWN_ENTRIES`（`tests/unit/test_conflict.py` 核对），文件名不得与那个旧包的文件重名（`tests/deps/` 核对）。
3. **打进安装包的东西只客观描述功能。** `src/` 下全部、`README.md`、`pyproject.toml`、`LICENSE` 不出现任何人的名字或 GitHub 账号，也不出现 Issue 号；注释里讲「为什么」只写现象与理由。谁提的、为什么改，写在 PR、Issue 与 `CHANGELOG.md`（不打进包）里。`tests/unit/test_release_content.py` 核对；包里新增文件类型时同步它的 `shipped_files()`。
4. **写出动机，不只写决定。** PR 描述与 `CHANGELOG.md` 写清看到了什么现象、想解决什么、考虑过又放弃了什么。
5. **版本号**：补丁号是修补、跟上平台口径、文案；次版本号是新功能、成块的新接口；主版本号是重大更新，可能不兼容旧接口。拿不准时往小了升。版本号三处同值（`pyproject.toml`、`src/quafu/__init__.py` 的 `__version__`、`src/quafu/cli.py` 的 `VERSION`，测试核对），`uv.lock` 跟着改；每版在 `CHANGELOG.md` 写一节，发 PyPI 后标日期。已在 PyPI 上删掉的版本号（0.2.0、0.2.1）不能再用。
6. **安装写法**：说明书默认写 uv（`uv pip install`），pip 作备选写在后面；面向教学的示例写 pip（Jupyter 里 `%pip install quafu-sdk`）。conda 不在支持范围内。
7. **凭证不入库。** API Key、令牌、密码不进代码、测试、日志与 Issue。
