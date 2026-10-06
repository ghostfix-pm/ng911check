"""Importing this module registers every check via its @registry.check decorator."""
from . import address_checks, cross_layer_checks, response_area_checks, street_checks

__all__ = ["address_checks", "cross_layer_checks", "response_area_checks", "street_checks"]
