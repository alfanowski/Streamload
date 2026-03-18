"""DMAX service plugin for Streamload.

DMAX is an Italian factual and adventure channel operated by Warner
Bros. Discovery.  It broadcasts documentaries, reality shows, and
action-oriented programming.

The service runs on the shared Aurora platform API.  This module
only declares service-specific attributes; all logic lives in
:class:`~streamload.services._aurora_base.AuroraServiceBase`.
"""

from streamload.services import ServiceRegistry
from streamload.services._aurora_base import AuroraServiceBase


@ServiceRegistry.register
class DMAXService(AuroraServiceBase):
    """DMAX (dmax.it) service plugin."""

    name = "DMAX"
    short_name = "dm"
    domains = ["www.dmax.it", "dmax.it"]
    environment_id = "dmaxit"
