# Contributing to Brix

Thank you for helping build reliable, user-controlled browser automation.

## 🚀 Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (for dependency management)
- Git
- An authenticated Codex CLI
- Playwright Chromium (`uv run playwright install chromium`)

### Local Development

1. **Clone the repository**
   ```bash
   git clone <your-brix-fork>
   cd brix
   ```

2. **Install development dependencies**
   ```bash
   make setup-dev

   # or manually:
   uv sync
   uv run pre-commit install
   ```

3. **Configure local state**
   ```bash
   export BRIX_DATA_DIR="$PWD/.brix"
   export BRIX_API_TOKEN="development-token"
   ```

4. **Run Brix in development mode**
   ```bash
   uv run brix serve --reload
   ```

## 🔧 Contributing Code

### Pull Request Process

1. **Create an issue first** - Describe the problem or feature
2. **Fork and branch** - Work from the `main` branch
3. **Make your changes** - Follow existing code style
4. **Write/update tests** - Ensure coverage for new features
5. **Run quality checks** - `make check-all` should pass
6. **Submit PR** - Link to issue and provide context

### PR Guidelines

- **Clear description** - Explain what and why
- **Small, focused changes** - One feature/fix per PR
- **Include examples** - Show before/after behavior
- **Update documentation** - If adding features
- **Pass all checks** - Tests, linting, type checking

### Code Style

- Follow PEP 8 with 100-character line limit
- Use type hints for all functions
- Write docstrings for public methods
- Keep functions focused and small
- Use meaningful variable names

## 🐛 Reporting Issues

When reporting bugs, please include:

- Python version and OS
- Brix version (`brix --version`)
- Codex CLI version
- Full error traceback
- Steps to reproduce
- Expected vs actual behavior

## 💡 Feature Requests

We welcome feature ideas! Please:

- Check existing issues first
- Describe the use case clearly
- Explain why it would benefit users
- Consider implementation approach
- Be open to discussion

## Scope and safety

Browser tasks must respect configured permissions. Never add challenge bypasses, log credentials,
or commit `.brix/`, browser profiles, cookies, downloads, screenshots, or task artifacts.

## 🤝 Community

- Open an issue in the Brix repository with a minimal reproduction.

## ✨ Recognition

We value all contributions! Contributors will be:
- Listed in release notes
- Thanked in our Discord
- Added to contributors list (coming soon)

---

**Questions?** Open a discussion or issue in the Brix repository.
