"""Action translation — maps high-level actions to driver-specific calls.

The cognitive layer works with abstract actions (e.g., "move_forward").
This translator converts those abstract actions into the concrete
parameters that each driver understands.
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol

logger = structlog.get_logger(__name__)


class ActionTranslator:
    """Translates high-level actions to driver-specific parameters.

    The cognitive layer operates on abstract actions. Each driver may
    require different parameter names or structures for the same
    conceptual action. This translator bridges that gap.
    """

    def __init__(self) -> None:
        """Initialize the action translator."""
        self._translation_maps: dict[str, dict[str, dict[str, Any]]] = {}
        logger.info("action_translator_initialized")

    async def translate(
        self,
        action: str,
        parameters: dict[str, Any],
        driver: UnifiedDriverProtocol,
    ) -> tuple[str, dict[str, Any]]:
        """Translate an action and its parameters for a specific driver.

        If no translation is registered for this driver/action pair,
        the action and parameters are passed through unchanged.

        Args:
            action: The abstract action name.
            parameters: The abstract action parameters.
            driver: The target driver.

        Returns:
            A tuple of (translated_action, translated_parameters).
        """
        driver_name = driver.driver_name

        # Check if we have a translation map for this driver
        driver_maps = self._translation_maps.get(driver_name, {})
        if action in driver_maps:
            translation = driver_maps[action]
            translated_action = translation.get("action", action)
            translated_params = self._apply_translation(
                parameters, translation.get("parameters", {})
            )
            logger.debug(
                "action_translated",
                driver_name=driver_name,
                original_action=action,
                translated_action=translated_action,
            )
            return translated_action, translated_params

        # Pass through unchanged
        return action, parameters

    async def register_translation(
        self,
        driver_name: str,
        action: str,
        translated_action: str,
        parameter_map: dict[str, str] | None = None,
    ) -> None:
        """Register a translation mapping for a driver/action pair.

        Args:
            driver_name: The driver to register for.
            action: The abstract action name.
            translated_action: The driver-specific action name.
            parameter_map: Mapping from abstract param names to driver param names.
        """
        if driver_name not in self._translation_maps:
            self._translation_maps[driver_name] = {}

        self._translation_maps[driver_name][action] = {
            "action": translated_action,
            "parameters": parameter_map or {},
        }

        logger.info(
            "translation_registered",
            driver_name=driver_name,
            action=action,
            translated_action=translated_action,
        )

    @staticmethod
    def _apply_translation(
        parameters: dict[str, Any],
        param_map: dict[str, str],
    ) -> dict[str, Any]:
        """Apply parameter name translations.

        Args:
            parameters: Original parameters with abstract names.
            param_map: Mapping from abstract names to driver names.

        Returns:
            Parameters with translated names.
        """
        translated: dict[str, Any] = {}
        for key, value in parameters.items():
            new_key = param_map.get(key, key)
            translated[new_key] = value
        return translated
