# Contributing to zan

Thank you for your interest in making zan better! This document is available in both English and Chinese.

- [English](#english)
- [中文](#中文)

---

## English

### Ways to contribute

- Report bugs or unexpected Flask-compatibility differences by opening an issue.
- Suggest features or improvements.
- Submit pull requests for bug fixes, docs, tests, or new features.
- Help translate documentation into other languages.

### Before you open an issue

1. Search existing issues to avoid duplicates.
2. Include a minimal reproducible example for bugs.
3. Mention your environment: OS, Python version, Rust version (`rustc --version`), and zan version.

### Development setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install maturin pytest jinja2
maturin develop --release
pytest tests/ -q
```

### Pull request guidelines

1. Fork the repository and create a feature branch.
2. Add or update tests for any code change.
3. Run the full test suite locally and make sure it passes.
4. Keep changes focused; split unrelated changes into separate PRs.
5. Follow the existing code style (Rust `cargo fmt`, Python `black`/`ruff` if applicable).
6. Write clear commit messages and a descriptive PR title.

### Code of conduct

Please be respectful and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## 中文

### 参与方式

- 提交 issue 报告 bug 或与 Flask 的兼容性差异。
- 提出新功能或改进建议。
- 提交 PR 修复 bug、补充文档/测试或实现新功能。
- 帮助将文档翻译成其他语言。

### 提交 issue 前

1. 搜索已有 issue，避免重复。
2. 提供最小可复现示例。
3. 说明运行环境：操作系统、Python 版本、Rust 版本（`rustc --version`）和 zan 版本。

### 开发环境

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS：bin/activate
pip install maturin pytest jinja2
maturin develop --release
pytest tests/ -q
```

### Pull request 规范

1. Fork 仓库并创建功能分支。
2. 任何代码改动请补充或更新测试。
3. 在本地运行完整测试套件并确保通过。
4. 保持改动聚焦；无关改动请拆分到不同 PR。
5. 遵循现有代码风格（Rust 用 `cargo fmt`，Python 可用 `black`/`ruff`）。
6. 提交清晰的 commit message 和描述性的 PR 标题。

### 行为准则

请保持尊重和建设性。详见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
