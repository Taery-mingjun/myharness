"""MyHarness REST API module.

Provides the FastAPI application factory and all API routers for the
cognitive operating system's HTTP interface.
"""

from myharness.api.app import create_app

__all__ = ["create_app"]
