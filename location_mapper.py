"""
Location Mapping for the Storage Topology Tool

This module handles mapping of physical disk locations based on
enclosure configurations and custom mappings.
"""

from typing import Dict, List, Optional, Tuple
import logging
from storage_models import DiskInfo, EnclosureInfo, EnclosureConfig, DiskMapping


class LocationMapper:
    """Maps physical disk locations based on configuration"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.enclosure_configs: Dict[str, EnclosureConfig] = {}
        self.custom_mappings: Dict[str, DiskMapping] = {}
    
    def add_enclosure_config(self, config: EnclosureConfig) -> None:
        """Add an enclosure configuration"""
        self.enclosure_configs[config.id] = config
        self.logger.debug(f"Added enclosure config for {config.id}: {config.name}")
    
    def add_disk_mapping(self, mapping: DiskMapping) -> None:
        """Add a custom disk mapping"""
        self.custom_mappings[mapping.serial] = mapping
        self.logger.debug(f"Added custom mapping for disk {mapping.serial}")
    
    def map_disk_location(self, disk: DiskInfo, enclosure: Optional[EnclosureInfo]) -> DiskInfo:
        """Map physical location for a disk
        
        Args:
            disk: DiskInfo to map
            enclosure: EnclosureInfo for the disk's enclosure
            
        Returns:
            Updated DiskInfo with location information
        """
        # Check for custom mapping first
        if disk.serial in self.custom_mappings:
            mapping = self.custom_mappings[disk.serial]
            disk.enclosure_name = mapping.enclosure
            disk.physical_slot = mapping.slot
            disk.logical_disk = mapping.disk
            self.logger.debug(f"Using custom mapping for disk {disk.serial}")
            return disk
        
        # Get enclosure configuration
        config = self._get_enclosure_config(enclosure)
        
        if config:
            disk.enclosure_name = config.name
            
            # Calculate position
            try:
                drive_num = int(disk.drive)
                hw_start_slot = enclosure.hw_start_slot if enclosure else 1
                disk.physical_slot, disk.logical_disk = self._calculate_position(
                    drive_num, hw_start_slot, config
                )
            except (ValueError, TypeError):
                disk.physical_slot = 0
                disk.logical_disk = 0
        else:
            # No configuration - use defaults
            disk.enclosure_name = self._get_default_enclosure_name(enclosure)
            try:
                drive_num = int(disk.drive)
                disk.physical_slot = drive_num + 1
                disk.logical_disk = drive_num
            except (ValueError, TypeError):
                disk.physical_slot = 0
                disk.logical_disk = 0
        
        return disk
    
    def _get_enclosure_config(self, enclosure: Optional[EnclosureInfo]) -> Optional[EnclosureConfig]:
        """Get configuration for an enclosure"""
        if not enclosure:
            return None
        
        # Try by product ID (stripped)
        if enclosure.product_id:
            product_id_stripped = enclosure.product_id.strip()
            
            # Exact match
            if enclosure.product_id in self.enclosure_configs:
                return self.enclosure_configs[enclosure.product_id]
            
            # Stripped match
            if product_id_stripped in self.enclosure_configs:
                return self.enclosure_configs[product_id_stripped]
            
            # Try matching any config key that matches when stripped
            for config_id, config in self.enclosure_configs.items():
                if isinstance(config_id, str) and config_id.strip() == product_id_stripped:
                    return config
        
        # Try by logical ID
        if enclosure.logical_id and enclosure.logical_id in self.enclosure_configs:
            return self.enclosure_configs[enclosure.logical_id]
        
        # Try by enclosure ID
        if enclosure.enclosure_id and enclosure.enclosure_id in self.enclosure_configs:
            return self.enclosure_configs[enclosure.enclosure_id]
        
        return None
    
    def _get_default_enclosure_name(self, enclosure: Optional[EnclosureInfo]) -> str:
        """Get default name for enclosure without configuration"""
        if not enclosure:
            return "-"
        
        if enclosure.enclosure_type and enclosure.enclosure_type != "Unknown":
            return enclosure.enclosure_type
        
        if enclosure.enclosure_id:
            return f"Enclosure-{enclosure.enclosure_id}"
        
        return "-"
    
    def _calculate_position(self, drive_num: int, hw_start_slot: int, 
                          config: EnclosureConfig) -> Tuple[int, int]:
        """Calculate physical slot and logical disk number
        
        Args:
            drive_num: Raw drive number from controller (1-based)
            hw_start_slot: Hardware start slot number
            config: Enclosure configuration
            
        Returns:
            Tuple of (physical_slot, logical_disk)
        """
        # Default hw_start_slot to 1 if not provided or 0
        if hw_start_slot <= 0:
            hw_start_slot = 1
        
        # Calculate relative drive number (0-based from hardware start)
        real_drive_num = drive_num - hw_start_slot
        if real_drive_num < 0:
            real_drive_num = 0
        
        # Calculate physical slot
        physical_slot = config.start_slot + real_drive_num + config.offset
        
        # Logical disk is same as physical slot
        logical_disk = physical_slot
        
        return physical_slot, logical_disk
    
    def map_all_disks(self, disks: List[DiskInfo], 
                     enclosures: List[EnclosureInfo]) -> List[DiskInfo]:
        """Map locations for all disks
        
        Args:
            disks: List of DiskInfo objects
            enclosures: List of EnclosureInfo objects
            
        Returns:
            List of DiskInfo objects with location information
        """
        # Create enclosure lookup
        enclosure_map = {}
        for enclosure in enclosures:
            key = f"{enclosure.controller}_{enclosure.enclosure_id}"
            enclosure_map[key] = enclosure
        
        # Map each disk
        mapped_disks = []
        for disk in disks:
            key = f"{disk.controller}_{disk.enclosure}"
            enclosure = enclosure_map.get(key)
            mapped_disk = self.map_disk_location(disk, enclosure)
            mapped_disks.append(mapped_disk)
        
        # Sort by enclosure name and slot
        mapped_disks.sort(key=lambda d: (d.enclosure_name, d.physical_slot))
        
        return mapped_disks
