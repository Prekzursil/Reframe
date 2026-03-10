import sys
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / 'scripts'
QUALITY_DIR = SCRIPTS_DIR / 'quality'
for candidate in (SCRIPTS_DIR, QUALITY_DIR):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def load_module(relative_path: str, module_name: str):
    module_path = REPO_ROOT / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f'Unable to load module spec for {relative_path}')
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class VisualGateContractTests(unittest.TestCase):
    def test_strict23_default_contexts_use_chromatic_pairing(self):
        module = load_module('scripts/strict23_preflight.py', 'strict23_preflight_test')

        self.assertIn('Applitools Visual', module.DEFAULT_CANONICAL_CONTEXTS)
        self.assertIn('Chromatic Playwright', module.DEFAULT_CANONICAL_CONTEXTS)
        self.assertNotIn('Percy Visual', module.DEFAULT_CANONICAL_CONTEXTS)
        self.assertNotIn('BrowserStack E2E', module.DEFAULT_CANONICAL_CONTEXTS)

    def test_quality_secret_defaults_require_chromatic_not_percy_browserstack(self):
        module = load_module('scripts/quality/check_quality_secrets.py', 'check_quality_secrets_test')

        self.assertIn('APPLITOOLS_API_KEY', module.DEFAULT_REQUIRED_SECRETS)
        self.assertIn('CHROMATIC_PROJECT_TOKEN', module.DEFAULT_REQUIRED_SECRETS)
        self.assertNotIn('PERCY_TOKEN', module.DEFAULT_REQUIRED_SECRETS)
        self.assertNotIn('BROWSERSTACK_USERNAME', module.DEFAULT_REQUIRED_SECRETS)
        self.assertNotIn('BROWSERSTACK_ACCESS_KEY', module.DEFAULT_REQUIRED_SECRETS)


if __name__ == '__main__':
    unittest.main()
