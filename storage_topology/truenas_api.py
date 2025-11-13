"""TrueNAS API integration"""

import json
import logging
import subprocess
import re
from typing import List, Dict, Any, Optional

from .models import Disk


class TrueNASAPI:
    """Interface to TrueNAS API using midclt command"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize TrueNAS API interface

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

    def query_disk(self, disk_name: str = None) -> List[Dict[str, Any]]:
        """Query disk information from TrueNAS

        Args:
            disk_name: Name of the disk to query (e.g., ada0) or None for all disks

        Returns:
            List of disk information dictionaries
        """
        # Normalize disk name
        if disk_name:
            disk_name = self._normalize_disk_name(disk_name)

        try:
            # Build query command
            if disk_name:
                query_cmd = ["midclt", "call", "disk.query", f'[["name", "=", "{disk_name}"]]']
                self.logger.info(f"Querying disk: {disk_name}")
            else:
                query_cmd = ["midclt", "call", "disk.query", "[]"]
                self.logger.info("Querying all disks in TrueNAS")

            # Execute command
            result = self._execute_command(query_cmd)
            disk_info = json.loads(result)

            return disk_info

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error querying TrueNAS: {e}")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing JSON response from TrueNAS API: {e}")
            return []

    def update_disk_description(self, disk_name: str, enclosure: str,
                               slot: str, disk: str) -> bool:
        """Update a disk description in TrueNAS

        Args:
            disk_name: Name of the disk to update
            enclosure: Enclosure name/location
            slot: Slot number
            disk: Disk number

        Returns:
            bool: True if successful, False otherwise
        """
        # Normalize disk name
        disk_name = self._normalize_disk_name(disk_name)

        try:
            # Query current disk information
            query_cmd = ["midclt", "call", "disk.query", f'[["name", "=", "{disk_name}"]]']
            result = self._execute_command(query_cmd)
            disk_info_list = json.loads(result)

            if not disk_info_list:
                self.logger.error(f"No disk found with name: {disk_name}")
                return False

            disk_info = disk_info_list[0]

            # Update the disk
            return self._update_disk_description_internal(disk_info, enclosure, slot, disk)

        except Exception as e:
            self.logger.error(f"Error updating TrueNAS disk: {e}")
            return False

    def update_all_disks(self, disks: List[Disk]) -> tuple[int, int]:
        """Update all disk descriptions in TrueNAS with location information

        Args:
            disks: List of disks with location information

        Returns:
            tuple[int, int]: Number of updated and skipped disks
        """
        self.logger.info("Updating all TrueNAS disk descriptions with location information")

        # Get all disks from TrueNAS
        try:
            all_disks = self.query_disk()

            updated_count = 0
            skipped_count = 0

            # Process each TrueNAS disk
            for truenas_disk in all_disks:
                disk_name = truenas_disk.get("name")

                # Find matching disk in our list
                matching_disk = None
                for disk in disks:
                    if disk.short_name == disk_name:
                        matching_disk = disk
                        break

                if matching_disk and matching_disk.enclosure_name and matching_disk.physical_slot:
                    self.logger.info(
                        f"Updating disk {disk_name} with location: {matching_disk.enclosure_name}, "
                        f"slot {matching_disk.physical_slot}"
                    )

                    if self._update_disk_description_internal(
                        truenas_disk,
                        matching_disk.enclosure_name,
                        str(matching_disk.physical_slot),
                        str(matching_disk.logical_disk)
                    ):
                        updated_count += 1
                        print(f"Updated disk: {disk_name}")
                    else:
                        skipped_count += 1
                else:
                    self.logger.debug(f"Skipping disk {disk_name}: No location information available")
                    skipped_count += 1

            print(f"\nSummary: Updated {updated_count} disks, skipped {skipped_count} disks")
            return updated_count, skipped_count

        except Exception as e:
            self.logger.error(f"Error updating TrueNAS disks: {e}")
            return 0, 0

    def get_pool_disk_mapping(self) -> Dict[str, Dict[str, str]]:
        """Get mapping of disks to their ZFS pools

        Returns:
            Dict mapping disk names to pool information
        """
        pool_disk_mapping = {}

        try:
            # Try JSON output first
            try:
                zpool_cmd = ["zpool", "status", "-L", "-j"]
                zpool_output = subprocess.check_output(zpool_cmd, universal_newlines=True)
                zpool_data = json.loads(zpool_output)

                if "pools" in zpool_data:
                    for pool_name, pool_info in zpool_data["pools"].items():
                        pool_state = pool_info.get("state", "UNKNOWN")
                        self._process_vdevs(pool_info.get("vdevs", {}), pool_name, pool_state, pool_disk_mapping)

            except (json.JSONDecodeError, subprocess.CalledProcessError):
                # Fall back to text parsing
                self._parse_zpool_text_output(pool_disk_mapping)

            # If still no results, try TrueNAS API
            if not pool_disk_mapping:
                self._get_pools_from_truenas_api(pool_disk_mapping)

        except Exception as e:
            self.logger.warning(f"Error getting pool information: {e}")

        return pool_disk_mapping

    def _update_disk_description_internal(self, disk_info: Dict[str, Any], enclosure: str,
                                         slot: str, disk: str) -> bool:
        """Internal method to update a single disk's description

        Args:
            disk_info: Dictionary containing disk information
            enclosure: Enclosure name/location
            slot: Slot number
            disk: Disk number

        Returns:
            bool: True if successful, False otherwise
        """
        # Get disk identifier
        disk_identifier = disk_info.get("identifier")
        if not disk_identifier:
            self.logger.error(f"Could not get identifier for disk: {disk_info.get('name')}")
            return False

        # Get current description
        current_description = disk_info.get("description", "").strip()

        # Create location information string
        location_info = f"Loc:{enclosure};SLOT:{slot};DISK:{disk}"

        # Remove any existing location information
        new_description = re.sub(r'Loc:\S+', '', current_description).strip()

        # Append new location
        if new_description:
            updated_description = f"{new_description} {location_info}"
        else:
            updated_description = location_info

        self.logger.info(f"Updating disk {disk_info.get('name')} with description: {updated_description}")

        # Build update command
        update_cmd = [
            "midclt", "call", "disk.update", disk_identifier,
            f'{{"description": "{updated_description}"}}'
        ]

        try:
            self._execute_command(update_cmd)
            return True
        except Exception as e:
            self.logger.error(f"Error updating disk {disk_info.get('name')}: {e}")
            return False

    def _process_vdevs(self, vdevs: Dict, pool_name: str, pool_state: str,
                      pool_disk_mapping: Dict[str, Dict[str, str]]) -> None:
        """Recursively process vdevs to find all disks in a pool"""
        for vdev_name, vdev_info in vdevs.items():
            if "vdevs" in vdev_info:
                self._process_vdevs(vdev_info["vdevs"], pool_name, pool_state, pool_disk_mapping)
            else:
                # Leaf vdev (disk)
                base_device = re.sub(r'(\D+)\d+$', r'\1', vdev_name)
                self.logger.debug(f"Mapping disk {base_device} (from {vdev_name}) to pool {pool_name}")
                pool_disk_mapping[base_device] = {
                    "pool": pool_name,
                    "state": pool_state
                }

    def _parse_zpool_text_output(self, pool_disk_mapping: Dict[str, Dict[str, str]]) -> None:
        """Parse zpool status text output"""
        try:
            zpool_cmd = ["zpool", "status"]
            zpool_output = subprocess.check_output(zpool_cmd, universal_newlines=True)

            current_pool = None
            in_config_section = False

            for line in zpool_output.splitlines():
                line = line.strip()

                if line.startswith("pool:"):
                    current_pool = line.split(":", 1)[1].strip()
                    self.logger.debug(f"Found pool: {current_pool}")
                elif line.startswith("config:"):
                    in_config_section = True
                elif in_config_section and current_pool and line:
                    parts = line.split()
                    if len(parts) >= 1:
                        device = parts[0]
                        state = parts[1] if len(parts) > 1 else "UNKNOWN"

                        # Skip pool name and special devices
                        if device != current_pool and not any(x in device for x in
                                                             ["mirror", "raidz", "spare", "log", "cache"]):
                            base_device = device.split("/")[-1].split("-")[0]
                            base_device = re.sub(r'(\D+)\d+$', r'\1', base_device)

                            self.logger.debug(f"Mapping disk {base_device} to pool {current_pool}")
                            pool_disk_mapping[base_device] = {"pool": current_pool, "state": state}

        except Exception as e:
            self.logger.warning(f"Error parsing zpool text output: {e}")

    def _get_pools_from_truenas_api(self, pool_disk_mapping: Dict[str, Dict[str, str]]) -> None:
        """Get pool information from TrueNAS API"""
        try:
            pools_cmd = ["midclt", "call", "pool.query", "[]"]
            pools_result = subprocess.check_output(pools_cmd, universal_newlines=True)
            pools_info = json.loads(pools_result)

            if pools_info:
                self.logger.debug(f"Found {len(pools_info)} pools via API")

                for pool in pools_info:
                    pool_name = pool.get("name")
                    if not pool_name:
                        continue

                    # Get pool disks
                    topology_cmd = ["midclt", "call", "pool.get_disks", f'["{pool_name}"]']
                    try:
                        topology_result = subprocess.check_output(topology_cmd, universal_newlines=True)
                        pool_disks = json.loads(topology_result)

                        self.logger.debug(f"Pool {pool_name} has disks: {pool_disks}")

                        for disk in pool_disks:
                            base_disk = disk.split("/")[-1].split("-")[0]
                            base_disk = re.sub(r'(\D+)\d+$', r'\1', base_disk)

                            pool_disk_mapping[base_disk] = {
                                "pool": pool_name,
                                "state": pool.get("status", "UNKNOWN")
                            }
                    except Exception as e:
                        self.logger.warning(f"Error getting disks for pool {pool_name}: {e}")
            else:
                self.logger.info("No pools found in the system")

        except Exception as e:
            self.logger.warning(f"Error getting pool information from TrueNAS API: {e}")

    def _normalize_disk_name(self, disk_name: str) -> str:
        """Normalize disk name by removing /dev/ prefix if present"""
        if disk_name and disk_name.startswith('/dev/'):
            disk_name = disk_name.replace('/dev/', '')
            self.logger.debug(f"Removed /dev/ prefix, using disk name: {disk_name}")
        return disk_name

    def _execute_command(self, cmd: List[str]) -> str:
        """Execute a command and return output"""
        self.logger.debug(f"Executing command: {' '.join(cmd)}")
        try:
            output = subprocess.check_output(cmd, universal_newlines=True)
            return output
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed: {' '.join(cmd)}")
            raise
