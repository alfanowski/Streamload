"""Nove service plugin for Streamload.

Nove is an Italian free-to-air channel operated by Warner Bros.
Discovery.  It broadcasts a mix of entertainment, comedy, talk shows,
and factual programming.

The service runs on the shared Aurora platform API.  This module
only declares service-specific attributes; all logic lives in
:class:`~streamload.services._aurora_base.AuroraServiceBase`.
"""

from streamload.services import ServiceRegistry
from streamload.services._aurora_base import AuroraServiceBase


@ServiceRegistry.register
class NoveService(AuroraServiceBase):
    """Nove (nove.tv) service plugin."""

    name = "Nove"
    short_name = "nv"
    domains = ["www.nove.tv", "nove.tv"]
    environment_id = "nove"
