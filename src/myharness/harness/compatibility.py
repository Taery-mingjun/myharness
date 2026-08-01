"""Version compatibility checking between system components.

Ensures that drivers, skills, and LLM providers are compatible with
each other before execution.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class CompatibilityChecker:
    """Version compatibility checking between system components.

    All methods are static — compatibility checking is a pure function
    with no side effects. Uses semantic versioning for comparison.
    """

    @staticmethod
    def check_driver_compatibility(
        driver_version: str, required_version: str
    ) -> bool:
        """Check if a driver version is compatible with a required version.

        Compatibility rules:
        - Same major version required.
        - Minor version must be >= required.
        - Patch version ignored for compatibility.

        Args:
            driver_version: The actual driver version (e.g., "1.2.0").
            required_version: The minimum required version (e.g., "1.0.0").

        Returns:
            True if compatible, False otherwise.
        """
        try:
            d_major, d_minor, _ = map(int, driver_version.split("."))
            r_major, r_minor, _ = map(int, required_version.split("."))
        except (ValueError, AttributeError):
            logger.warning(
                "invalid_version_format",
                driver_version=driver_version,
                required_version=required_version,
            )
            return False

        if d_major != r_major:
            logger.debug(
                "driver_version_major_mismatch",
                driver_version=driver_version,
                required_version=required_version,
            )
            return False

        if d_minor < r_minor:
            logger.debug(
                "driver_version_minor_too_low",
                driver_version=driver_version,
                required_version=required_version,
            )
            return False

        return True

    @staticmethod
    def check_skill_compatibility(
        skill_version: str, system_version: str
    ) -> bool:
        """Check if a skill version is compatible with the system version.

        Same rules as driver compatibility: same major, minor >= required.

        Args:
            skill_version: The skill's version string.
            system_version: The system's minimum supported version.

        Returns:
            True if compatible, False otherwise.
        """
        return CompatibilityChecker.check_driver_compatibility(
            skill_version, system_version
        )

    @staticmethod
    def check_llm_provider_compatibility(
        provider_name: str,
        required_capabilities: list[str],
    ) -> bool:
        """Check if an LLM provider supports the required capabilities.

        Args:
            provider_name: The LLM provider name.
            required_capabilities: List of required capability names.

        Returns:
            True if the provider supports all required capabilities.
        """
        # Known provider capabilities
        provider_capabilities: dict[str, set[str]] = {
            "openai": {
                "function_calling",
                "streaming",
                "json_mode",
                "vision",
                "embeddings",
                "structured_output",
            },
            "anthropic": {
                "function_calling",
                "streaming",
                "vision",
                "tool_use",
            },
            "google": {
                "function_calling",
                "streaming",
                "vision",
                "embeddings",
                "json_mode",
            },
            "qwen": {
                "function_calling",
                "streaming",
                "vision",
            },
            "deepseek": {
                "function_calling",
                "streaming",
            },
            "ollama": {
                "streaming",
            },
        }

        provider_caps = provider_capabilities.get(provider_name.lower(), set())

        missing = set(required_capabilities) - provider_caps
        if missing:
            logger.debug(
                "llm_provider_missing_capabilities",
                provider=provider_name,
                missing=list(missing),
            )
            return False

        return True
