from pathlib import Path
import importlib.metadata
import unittest
from unittest.mock import Mock

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tools.check_converter_runtime import check_versions, pinned_versions

ROOT = Path(__file__).resolve().parents[1]
LINUX = {'platform_system': 'Linux'}


class ConverterRollbackTests(unittest.TestCase):
    def profile(self):
        return pinned_versions(ROOT / 'constraints-converter.txt', LINUX)

    def test_converter_is_pinned_without_changing_video_profile(self):
        pins = self.profile()
        self.assertEqual(pins['ultralytics'], '8.4.123')
        video = (ROOT / 'constraints-cpu.txt').read_text(encoding='utf-8')
        self.assertIn('ultralytics==8.4.138', video)
        self.assertNotIn('8.4.123', video)
        for name in ('torch', 'torchvision'):
            self.assertIn(name + '==' + pins[name], video)
        self.assertEqual(pins['litert-torch'], '0.9.3')
        self.assertEqual(pins['ai-edge-litert'], '2.1.6')

    def test_nested_pip_constraints_resolve_to_selected_profile(self):
        # Reproduce Docker COPY's path mapping, without changing repo files.
        files = {p.name: p.read_text(encoding='utf-8') for p in ROOT.glob('requirements*.txt')}
        files['constraints-cpu.txt'] = (ROOT / 'constraints-converter.txt').read_text(encoding='utf-8')
        pins = self.profile()
        visited = set()
        constraint_visits = []
        def visit(name, constraint=False):
            if (name, constraint) in visited:
                return
            visited.add((name, constraint))
            for line in files[name].splitlines():
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue
                if line.startswith('-r '):
                    visit(line[3:].strip())
                elif line.startswith('-c '):
                    constraint_visits.append(line[3:].strip())
                    visit(line[3:].strip(), True)
                elif not line.startswith('-'):
                    req = Requirement(line)
                    if req.marker and not req.marker.evaluate(LINUX):
                        continue
                    key = canonicalize_name(req.name)
                    if key in pins:
                        self.assertIn(pins[key], req.specifier, line)
        visit('requirements-converter-service.txt')
        self.assertIn('constraints-cpu.txt', constraint_visits)
        self.assertIn(('requirements-yolo.txt', False), visited)
        self.assertIn(('requirements-convert.txt', False), visited)

    def test_docker_selects_profile_for_install_and_autoinstall(self):
        docker = (ROOT / 'Dockerfile.converter').read_text(encoding='utf-8')
        selected = 'COPY constraints-converter.txt ./constraints-cpu.txt'
        self.assertIn(selected, docker)
        self.assertNotIn('COPY requirements-cpu.txt constraints-cpu.txt ./', docker)
        self.assertLess(docker.index(selected), docker.index('RUN pip install'))
        self.assertIn('PIP_CONSTRAINT=/app/constraints-cpu.txt', docker)
        self.assertIn('&& python tools/check_converter_runtime.py --constraints /app/constraints-cpu.txt', docker)
        self.assertIn('!tools/check_converter_runtime.py', (ROOT / '.dockerignore').read_text())
        self.assertNotIn('constraints-converter.txt', (ROOT / 'Dockerfile').read_text())

    def test_runtime_audit_accepts_exact_profile(self):
        pins = self.profile()
        self.assertEqual(check_versions(pins, pins.__getitem__), pins)

    def test_release_build_is_clean_revision_bound_and_converter_only(self):
        script = (ROOT / 'tools/build_converter_release.sh').read_text(encoding='utf-8')
        for guard in ('git rev-parse HEAD', 'git status --porcelain --untracked-files=all --ignored',
                      'Refusing to overwrite existing image tag', 'org.opencontainers.image.revision=$expected',
                      '-f Dockerfile.converter .'):
            self.assertIn(guard, script)
        self.assertNotIn('docker compose', script)
        self.assertNotIn('docker push', script)
        self.assertNotIn('git reset', script)

    def test_runtime_audit_rejects_old_bad_exporter(self):
        pins = self.profile()
        actual = dict(pins, ultralytics='8.4.138')
        with self.assertRaisesRegex(RuntimeError, r'ultralytics: 8.4.138 .*8.4.123'):
            check_versions(pins, actual.__getitem__)

    def test_runtime_audit_rejects_missing_package_and_cpu_build_drift(self):
        pins = self.profile()
        actual = dict(pins, torch='2.12.0')
        with self.assertRaisesRegex(RuntimeError, 'torch:'):
            check_versions(pins, actual.__getitem__)
        def missing(name):
            raise importlib.metadata.PackageNotFoundError(name)
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            check_versions(pins, missing)

    def test_profile_rejects_ranges_missing_and_duplicate_pins(self):
        good = (ROOT / 'constraints-converter.txt').read_text(encoding='utf-8')
        for text in (good.replace('ultralytics==8.4.123', 'ultralytics>=8.4.123'),
                     good.replace('ultralytics==8.4.123', ''),
                     good + chr(10) + 'ultralytics==8.4.138' + chr(10)):
            path = Mock()
            path.read_text.return_value = text
            with self.assertRaises(ValueError):
                pinned_versions(path, LINUX)


if __name__ == '__main__':
    unittest.main()
