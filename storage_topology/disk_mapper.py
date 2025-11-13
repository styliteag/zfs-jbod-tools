"""Disk location mapping functionality"""

import logging
import subprocess
import json
from typing import List, Dict, Set, Optional, Tuple

from .models import Disk, Enclosure, EnclosureConfig
from .config import ConfigManager


class DiskMapper:
    """Maps disks to their physical locations in enclosures"""

    def __init__(self, config_manager: ConfigManager, logger: Optional[logging.Logger] = None):
        """Initialize disk mapper

        Args:
            config_manager: Configuration manager instance
            logger: Logger instance
        """
        self.config_manager = config_manager
        self.logger = logger or logging.getLogger(__name__)

    def match_with_system_devices(self, controller_disks: List[Disk]) -> List[Disk]:
        """Match controller disks with system block devices

        Args:
            controller_disks: List of disks from controller

        Returns:
            List of disks with updated device names from lsblk
        """
        self.logger.info("Matching controller devices with system devices")

        # Get lsblk information
        lsblk_data = self._get_lsblk_data()
        if not lsblk_data:
            return controller_disks

        # Match disks
        matched_disks = []
        seen_wwns: Set[str] = set()

        for block_device in lsblk_data.get("blockdevices", []):
            dev_name = block_device.get("name", "")
            wwn = block_device.get("wwn", "")
            serial = block_device.get("serial", "")

            # Normalize WWN
            my_wwn = wwn.replace("0x", "").lower() if wwn else ""

            # Find matching disk from controller
            matched_disk = None
            for disk in controller_disks:
                disk_wwn = disk.wwn.replace("0x", "").lower() if disk.wwn else ""
                disk_serial = disk.serial

                # Try to match by WWN or serial
                if (disk_wwn and disk_wwn == my_wwn) or (disk_serial and disk_serial == serial):
                    matched_disk = disk
                    break

            if matched_disk:
                # Check for duplicates using slot identifier
                slot_id = f"{matched_disk.controller}_{matched_disk.enclosure}_{matched_disk.slot}"

                # Skip duplicates unless this is a multipath device
                if slot_id in seen_wwns:
                    if dev_name.startswith("/dev/dm-"):
                        # Prefer multipath device names
                        matched_disks = [d for d in matched_disks
                                       if not (d.controller == matched_disk.controller and
                                             d.enclosure == matched_disk.enclosure and
                                             d.slot == matched_disk.slot)]
                        seen_wwns.discard(slot_id)
                        self.logger.debug(f"Replacing with multipath device {dev_name} for slot {slot_id}")
                    else:
                        self.logger.debug(f"Skipping duplicate path {dev_name} for slot {slot_id}")
                        continue

                # Create new disk with updated device name
                updated_disk = Disk(
                    dev_name=dev_name,
                    serial=matched_disk.serial,
                    model=matched_disk.model,
                    wwn=matched_disk.wwn,
                    controller=matched_disk.controller,
                    enclosure=matched_disk.enclosure,
                    slot=matched_disk.slot,
                    manufacturer=matched_disk.manufacturer,
                    size=block_device.get("size", ""),
                    vendor=block_device.get("vendor", "")
                )

                matched_disks.append(updated_disk)
                seen_wwns.add(slot_id)

        return matched_disks

    def map_locations(self, disks: List[Disk], enclosures: List[Enclosure]) -> List[Disk]:
        """Map physical locations for all disks

        Args:
            disks: List of disks to map
            enclosures: List of enclosures

        Returns:
            List of disks with updated location information
        """
        self.logger.info("Mapping physical locations")

        # Create enclosure lookup dictionary
        enclosure_map = {enc.key: enc for enc in enclosures}

        # Map each disk
        mapped_disks = []
        for disk in disks:
            mapped_disk = self._map_disk_location(disk, enclosure_map)
            mapped_disks.append(mapped_disk)

        return mapped_disks

    def _map_disk_location(self, disk: Disk, enclosure_map: Dict[str, Enclosure]) -> Disk:
        """Map location for a single disk

        Args:
            disk: Disk to map
            enclosure_map: Dictionary of enclosures keyed by controller_id_enclosure_id

        Returns:
            Disk with updated location information
        """
        # Check for custom mapping first
        custom_mapping = self.config_manager.get_disk_mapping(disk.serial)
        if custom_mapping:
            self.logger.debug(f"Using custom mapping for disk with serial {disk.serial}: {custom_mapping}")
            disk.enclosure_name = custom_mapping.enclosure
            disk.physical_slot = custom_mapping.slot
            disk.logical_disk = custom_mapping.disk
            return disk

        # Get enclosure information
        enclosure_key = f"{disk.controller}_{disk.enclosure}"
        enclosure = enclosure_map.get(enclosure_key)

        if not enclosure:
            # No enclosure found, use defaults
            disk.enclosure_name = f"Enclosure-{disk.enclosure}"
            disk.physical_slot = disk.slot + 1
            disk.logical_disk = disk.slot
            return disk

        # Get configuration for this enclosure
        config = self.config_manager.get_enclosure_config(
            logical_id=enclosure.logical_id,
            enclosure_id=enclosure.enclosure_id,
            product_id=enclosure.product_id
        )

        if config:
            # Use configured mapping
            disk.enclosure_name = config.name
            physical_slot, logical_disk = self._calculate_disk_position(
                disk.slot,
                enclosure.start_slot,
                config
            )
            disk.physical_slot = physical_slot
            disk.logical_disk = logical_disk

            self.logger.debug(
                f"Calculated position for {disk.dev_name}: "
                f"slot={disk.slot}, hw_start={enclosure.start_slot}, "
                f"physical_slot={physical_slot}, logical_disk={logical_disk}"
            )
        else:
            # Use default mapping
            disk.enclosure_name = enclosure.enclosure_type or f"Enclosure-{enclosure.enclosure_id}"
            disk.physical_slot = disk.slot + 1
            disk.logical_disk = disk.slot

        return disk

    def _calculate_disk_position(self, drive_num: int, hw_start_slot: int,
                                 config: EnclosureConfig) -> Tuple[int, int]:
        """Calculate the physical and logical position of a disk

        Args:
            drive_num: The raw drive number from controller (1-based)
            hw_start_slot: The hardware start slot number (usually 1)
            config: The enclosure configuration entry

        Returns:
            Tuple of (physical_slot, logical_disk)
        """
        start_slot = config.start_slot
        offset = config.offset

        # Default hw_start_slot to 1 if not provided or 0
        if hw_start_slot <= 0:
            hw_start_slot = 1

        # Calculate relative drive number (0-based index from hardware start)
        real_drive_num = drive_num - hw_start_slot
        if real_drive_num < 0:
            real_drive_num = 0

        # Calculate physical slot
        physical_slot = start_slot + real_drive_num + offset

        # Logical disk number is the same as physical slot
        logical_disk = physical_slot

        return physical_slot, logical_disk

    def _get_lsblk_data(self) -> Dict:
        """Get block device information from lsblk

        Returns:
            Dictionary with block device information
        """
        self.logger.info("Getting system block device information")

        try:
            cmd = ["lsblk", "-p", "-d", "-o",
                  "NAME,WWN,VENDOR,MODEL,REV,SERIAL,SIZE,PTUUID,HCTL,TRAN,TYPE", "-J"]
            output = subprocess.check_output(cmd, universal_newlines=True)
            data = json.loads(output)

            self.logger.debug(f"Found {len(data.get('blockdevices', []))} block devices")
            return data

        except subprocess.SubprocessError as e:
            self.logger.error(f"Failed to execute lsblk command: {e}")
            return {"blockdevices": []}
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse lsblk JSON output: {e}")
            return {"blockdevices": []}
