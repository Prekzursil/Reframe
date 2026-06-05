```markdown
# Reframe Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches you the core development patterns, coding conventions, and workflows used in the Reframe Python codebase. You'll learn how to structure files, write imports and exports, follow commit message conventions, and implement and run tests according to the repository's standards. This guide is ideal for contributors aiming for consistency and maintainability in Reframe projects.

## Coding Conventions

### File Naming
- Use **snake_case** for all file names.
  - Example:  
    ```plaintext
    my_module.py
    utils/helpers.py
    ```

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import helper_function
    from ..core import base_class
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - Example:
    ```python
    __all__ = ['MyClass', 'my_function']
    ```

### Commit Messages
- Follow **conventional commit** patterns.
- Use the `fix` prefix for bug fixes.
- Keep commit messages concise (average 73 characters).
  - Example:
    ```plaintext
    fix: correct calculation in data processing module
    ```

## Workflows

### Bug Fixing
**Trigger:** When a bug or issue is identified in the codebase  
**Command:** `/bug-fix`

1. Create a new branch for your fix.
2. Make code changes following the coding conventions.
3. Write or update tests in `*.test.*` files to cover the fix.
4. Commit your changes using the `fix:` prefix and a concise message.
5. Push your branch and open a pull request.

### Adding a New Module
**Trigger:** When adding new functionality  
**Command:** `/add-module`

1. Create a new Python file using snake_case naming.
2. Implement your module using relative imports as needed.
3. Define `__all__` for explicit exports.
4. Add or update tests in a corresponding `*.test.*` file.
5. Commit with a descriptive message (use `feat:` if following extended conventional commits).
6. Push and open a pull request.

### Writing Tests
**Trigger:** When adding or updating tests  
**Command:** `/write-test`

1. Create or update a test file matching the pattern `*.test.*`.
2. Write test cases for your module or function.
3. Ensure tests are comprehensive and follow the codebase's style.
4. Run tests (see Testing Patterns below).
5. Commit with a message like `test: add tests for my_module`.

## Testing Patterns

- Test files follow the pattern `*.test.*` (e.g., `my_module.test.py`).
- The specific testing framework is **unknown**; check existing test files for structure.
- Place tests alongside or near the modules they test.
- Example test file name:
  ```plaintext
  utils.test.py
  ```

## Commands
| Command      | Purpose                                   |
|--------------|-------------------------------------------|
| /bug-fix     | Start the bug fixing workflow             |
| /add-module  | Start the process to add a new module     |
| /write-test  | Begin writing or updating tests           |
```