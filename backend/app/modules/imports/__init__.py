"""imports context (L5): CSV imports of clients and households, memberships, opening balances and POS products
(IMP-01, IMP-02, MEM-23). It sits above every context it writes to and calls only their public import functions;
platform, which owns the `platform.import_job.*` keys, cannot import clients (overview section 2), hence its own
package. Public interface: `service`. Never import this package's models or schemas from another context.
"""

from app.modules import platform as _platform

from app.modules.imports import models, service  # isort: skip
from app.modules.imports import jobs  # noqa: F401  (registers the actor)

_platform.retention.register_purge("import_job_files", service.purge_expired_files)

__all__ = ["models", "service"]
