"""Full production app, with ONLY storage construction redirected to test paths."""
import os
from pathlib import Path

root = Path(os.environ['M36_T18_RUNTIME']).resolve()
if not root.is_dir() or root.parent.name != '.tmp' or not root.name.startswith('m36-t18-'):
    raise RuntimeError('expected a dedicated M36-T18 runtime')
if Path.cwd().resolve() != root:
    raise RuntimeError('worker must start outside the repository .env directory')

from app.model_catalog import ModelCatalog
from app.model_parameters import ModelParameterStore

catalog_init = ModelCatalog.__init__
profile_init = ModelParameterStore.__init__


def isolated_catalog(self, registry_path=None):
    catalog_init(self, root / 'models/registry.json')


def isolated_profiles(self, path=None, database_manager=None):
    profile_init(self, root / 'models/profiles.json', database_manager)


ModelCatalog.__init__ = isolated_catalog
ModelParameterStore.__init__ = isolated_profiles
from app.main import app  # noqa: E402,F401
