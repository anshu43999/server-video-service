"""M32-T34 source-only release safety checks; no Docker or remote access."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VideoReleaseTests(unittest.TestCase):
    def test_build_is_clean_revision_bound_and_video_only(self):
        script = (ROOT / 'tools/build_video_release.sh').read_text(encoding='utf-8')
        for guard in ('git rev-parse HEAD', 'git status --porcelain --untracked-files=all --ignored',
                      'git ls-files --error-unmatch', 'Refusing to overwrite existing image tag',
                      'org.opencontainers.image.revision=$expected', '-f Dockerfile .',
                      'test ! -e .env', 'test ! -e admin-web/dist', 'docker info'):
            self.assertIn(guard, script)
        for forbidden in ('docker compose', 'docker push', 'git reset', 'git clean',
                          'kubectl', 'Dockerfile.converter', 'pip install'):
            self.assertNotIn(forbidden, script)

    def test_frontend_is_built_from_source_and_local_outputs_are_excluded(self):
        docker = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        self.assertIn('RUN npm run test && npm run build && npm run build:preview', docker)
        self.assertIn('COPY --from=admin-build', docker)
        ignore = (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()
        for path in ('.git', '.env', 'admin-web/dist', 'admin-web/dist-preview', 'models', 'evidence'):
            self.assertIn(path, ignore)

    def test_video_runtime_keeps_its_own_profile_and_upgrade_tools(self):
        self.assertIn('ultralytics==8.4.138', (ROOT / 'constraints-cpu.txt').read_text())
        docker = (ROOT / 'Dockerfile').read_text()
        self.assertNotIn('constraints-converter.txt', docker)
        self.assertIn('USER app', docker)
        self.assertIn('check_app_update_runtime.py --tools-only', docker)
        self.assertIn('deploy/container-models', docker)


if __name__ == '__main__':
    unittest.main()
