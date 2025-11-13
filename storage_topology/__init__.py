"""
Storage Topology Tool - Refactored Module

This module provides functionality to identify and map physical disk locations
by correlating storage controller information with system block devices.
"""

from .models import Disk, Enclosure, EnclosureConfig
from .storage_topology import StorageTopology

__version__ = "2.0.0"
__all__ = ["Disk", "Enclosure", "EnclosureConfig", "StorageTopology"]
