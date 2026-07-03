```markdown
# Reframe Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill teaches the core development patterns and workflows used in the Reframe repository. The codebase is primarily Python with some TypeScript/JavaScript for UI components. It emphasizes explicit error handling (fail-loud), test-driven development (TDD) with 100% coverage, and clear, conventional commit practices. You'll learn how to structure code, write and organize tests, and follow robust workflows for both feature development and error hardening.

## Coding Conventions

- **File Naming:**  
  Use `snake_case` for Python files and `PascalCase` or `camelCase` for TypeScript/JavaScript files.
  - Example:  
    - Python: `reframe_claudeshorts.py`
    - TypeScript: `ModelsSystemPanel.tsx`

- **Import Style:**  
  Use **relative imports** in Python.
  ```python
  from .utils import some_helper
  ```

- **Export Style:**  
  Use **named exports** in TypeScript/JavaScript.
  ```typescript
  export function doSomething() { ... }
  ```

- **Commit Patterns:**  
  Follow the [Conventional Commits](https://www.conventionalcommits.org/) standard, using prefixes like `fix:`.  
  Example:
  ```
  fix: handle missing model error in reframe_claudeshorts.py
  ```

## Workflows

### Feature or Bugfix with TDD and Coverage
**Trigger:** When adding a new feature or fixing a bug and ensuring it is fully tested and covered  
**Command:** `/feature-tdd`

1. **Modify or add implementation logic** in the relevant source file(s).
2. **Add or update corresponding test files** to cover all new or changed logic.
3. **Assert both expected behavior and error/failure conditions** in tests (including fail-loud, no-silent-fallback cases).
4. **Run the test suite** to confirm 100% coverage (lines, branches, functions, statements).
5. **Commit both implementation and test changes together**.

**Example:**
```python
# sidecar/media_studio/features/reframe_claudeshorts.py
def process_payload(payload):
    if not payload:
        raise ValueError("Payload must not be empty")
    # ...implementation...

# sidecar/tests/test_reframe_claudeshorts.py
import pytest
from ..media_studio.features import reframe_claudeshorts

def test_process_payload_empty():
    with pytest.raises(ValueError):
        reframe_claudeshorts.process_payload(None)
```

### Fail-Loud, No-Silent-Fallback Hardening
**Trigger:** When ensuring that failures (missing models, broken dependencies, malformed data) are never silently ignored or degraded  
**Command:** `/fail-loud`

1. **Identify a code path** where a failure could be silently ignored or degraded.
2. **Modify implementation** to raise explicit errors or surface actionable messages (fail loud).
3. **Update or add tests** to assert that these errors are raised and never silently degrade.
4. **Document the fail-loud behavior** inline or in test descriptions.
5. **Commit both implementation and test changes together**.

**Example:**
```python
# sidecar/runtime_setup/bootstrap.py
def load_model(model_path):
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")
    # ...load model...

# sidecar/tests/test_runtime_setup.py
import pytest
from ..runtime_setup import bootstrap

def test_load_model_missing():
    with pytest.raises(FileNotFoundError):
        bootstrap.load_model("/nonexistent/model.pt")
```

## Testing Patterns

- **Framework:**  
  - Python: Use `pytest` for unit and integration tests.
  - TypeScript: Use `vitest` for UI/component tests.

- **Test File Naming:**  
  - Python: Prefix with `test_`, e.g., `test_reframe_claudeshorts.py`
  - TypeScript: Suffix with `.test.ts` or `.test.tsx`, e.g., `ModelsSystemPanel.test.tsx`

- **Test Coverage:**  
  Always aim for 100% coverage. Tests should assert both successful and failure/error cases, especially for fail-loud behaviors.

- **Example (TypeScript):**
  ```typescript
  // app/renderer/src/panels/ModelsSystemPanel.test.tsx
  import { render, screen } from '@testing-library/react';
  import { ModelsSystemPanel } from './ModelsSystemPanel';

  test('renders missing model error', () => {
    render(<ModelsSystemPanel models={[]} />);
    expect(screen.getByText(/No models found/)).toBeInTheDocument();
  });
  ```

## Commands

| Command        | Purpose                                                        |
|----------------|----------------------------------------------------------------|
| /feature-tdd   | Start a feature or bugfix with TDD and 100% test coverage      |
| /fail-loud     | Harden error handling to ensure all failures are surfaced      |
```
