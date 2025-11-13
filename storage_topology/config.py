"""Configuration management for storage topology"""

import os
import logging
from typing import Dict, List, Optional
import yaml

from .models import EnclosureConfig, DiskMapping


class ConfigManager:
    """Manages loading and accessing configuration from YAML file"""

    def __init__(self, config_file: str = "./storage_topology.conf", logger: Optional[logging.Logger] = None):
        """Initialize configuration manager

        Args:
            config_file: Path to configuration file
            logger: Logger instance
        """
        self.config_file = os.path.expanduser(config_file)
        self.logger = logger or logging.getLogger(__name__)

        self.enclosures: Dict[str, EnclosureConfig] = {}
        self.disk_mappings: Dict[str, DiskMapping] = {}

        self.load()

    def load(self) -> None:
        """Load configuration from YAML file

        Configuration file structure:
        ```yaml
        enclosures:
          - id: "SAS3x48Front"    # Enclosure ID, logical_id, or product ID
            name: "Front JBOD"    # Human-readable name
            start_slot: 1         # Starting slot number (1-based)
            max_slots: 48         # Maximum number of slots
            offset: 0             # Offset for slot calculation

        disks:
          - serial: "ABC123"      # Disk serial number
            enclosure: "Top"      # Custom enclosure name
            slot: 5               # Physical slot number
            disk: 1               # Logical disk number
        ```
        """
        if not os.path.exists(self.config_file):
            self.logger.warning(f"Configuration file {self.config_file} not found. Using default settings.")
            return

        try:
            self.logger.info(f"Loading user configuration from {self.config_file}")

            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)

            if not config:
                self.logger.warning(f"Configuration file {self.config_file} is empty or invalid")
                return

            # Load enclosure configurations
            if 'enclosures' in config:
                self._load_enclosures(config['enclosures'])

            # Load custom disk mappings
            if 'disks' in config:
                self._load_disk_mappings(config['disks'])

        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing YAML in configuration file: {e}")
        except IOError as e:
            self.logger.error(f"Error reading configuration file: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error loading configuration: {e}")

    def _load_enclosures(self, enclosures_data: List[Dict]) -> None:
        """Load enclosure configurations from data

        Args:
            enclosures_data: List of enclosure configuration dictionaries
        """
        self.logger.info(f"Found {len(enclosures_data)} enclosure configurations")

        for encl_config_data in enclosures_data:
            encl_id = encl_config_data.get('id')
            if not encl_id:
                self.logger.warning("Skipping enclosure config without ID")
                continue

            try:
                encl_config = EnclosureConfig.from_dict(encl_config_data)
                self.enclosures[encl_id] = encl_config
                self.logger.debug(f"Loaded enclosure config for {encl_id}: {encl_config}")
            except Exception as e:
                self.logger.warning(f"Error loading enclosure config for {encl_id}: {e}")

    def _load_disk_mappings(self, disks_data: List[Dict]) -> None:
        """Load custom disk mappings from data

        Args:
            disks_data: List of disk mapping dictionaries
        """
        self.logger.info(f"Found {len(disks_data)} custom disk mappings")

        for disk_config_data in disks_data:
            serial = disk_config_data.get('serial')
            if not serial:
                self.logger.warning("Skipping disk mapping without serial number")
                continue

            try:
                disk_mapping = DiskMapping.from_dict(disk_config_data)
                self.disk_mappings[serial] = disk_mapping
                self.logger.debug(f"Loaded custom mapping for disk {serial}: {disk_mapping}")
            except Exception as e:
                self.logger.warning(f"Error loading disk mapping for {serial}: {e}")

    def get_enclosure_config(self, logical_id: str = None, enclosure_id: str = None,
                            product_id: str = None) -> Optional[EnclosureConfig]:
        """Get enclosure configuration by ID

        Tries to match by product_id first, then logical_id, then enclosure_id.

        Args:
            logical_id: Logical ID (SAS address) of the enclosure
            enclosure_id: Enclosure ID from controller
            product_id: Product ID of the enclosure

        Returns:
            EnclosureConfig if found, None otherwise
        """
        # Try to find by product ID first (for storcli)
        if product_id:
            product_id_stripped = product_id.strip()
            self.logger.debug(
                f"Looking for config with product_id='{product_id}' (stripped='{product_id_stripped}'), "
                f"available keys: {list(self.enclosures.keys())}"
            )

            # Try exact match
            if product_id in self.enclosures:
                config = self.enclosures[product_id]
                self.logger.debug(f"Found config for product ID (exact) {product_id}: {config}")
                return config

            # Try stripped version
            if product_id_stripped in self.enclosures:
                config = self.enclosures[product_id_stripped]
                self.logger.debug(f"Found config for product ID (stripped) {product_id_stripped}: {config}")
                return config

            # Try matching any config key when stripped
            for config_id, config_entry in self.enclosures.items():
                if isinstance(config_id, str):
                    config_id_stripped = config_id.strip()
                    if config_id_stripped == product_id_stripped:
                        self.logger.debug(
                            f"Found config for product ID (matched stripped) '{config_id}' "
                            f"(stripped='{config_id_stripped}') == '{product_id_stripped}': {config_entry}"
                        )
                        return config_entry

        # Try by logical ID
        if logical_id and logical_id in self.enclosures:
            config = self.enclosures[logical_id]
            self.logger.debug(f"Found config for logical ID {logical_id}: {config}")
            return config

        # Try by enclosure ID
        if enclosure_id and enclosure_id in self.enclosures:
            config = self.enclosures[enclosure_id]
            self.logger.debug(f"Found config for enclosure ID {enclosure_id}: {config}")
            return config

        return None

    def get_disk_mapping(self, serial: str) -> Optional[DiskMapping]:
        """Get custom disk mapping by serial number

        Args:
            serial: Disk serial number

        Returns:
            DiskMapping if found, None otherwise
        """
        return self.disk_mappings.get(serial)

    def has_enclosure_configs(self) -> bool:
        """Check if any enclosure configurations are loaded"""
        return len(self.enclosures) > 0

    def has_disk_mappings(self) -> bool:
        """Check if any custom disk mappings are loaded"""
        return len(self.disk_mappings) > 0
