"""Main StorageTopology class - refactored version"""

import argparse
import json
import logging
import sys
from typing import List, Optional, Dict, Any

from .controllers import BaseController, StorcliController, SasIrcuController
from .models import Disk
from .config import ConfigManager
from .disk_mapper import DiskMapper
from .truenas_api import TrueNASAPI


class StorageTopology:
    """Main class for the Storage Topology tool (refactored)

    This class provides a high-level interface for disk topology operations.
    It orchestrates the work of specialized components:
    - Controllers (storcli, sas2ircu, sas3ircu)
    - Configuration management
    - Disk-to-location mapping
    - TrueNAS API integration
    """

    def __init__(self):
        """Initialize the StorageTopology instance"""
        # Options
        self.json_output = False
        self.show_zpool = False
        self.long_output = False
        self.verbose = False
        self.quiet = False
        self.query_disk = None
        self.update_disk = None
        self.update_all_disks = False
        self.sort_by = "pool"
        self.pool_disks_only = False
        self.pool_name = None
        self.locate_disk_name = None
        self.locate_off_disk_name = None
        self.locate_all = False
        self.locate_all_off = False
        self.wait_seconds = None
        self.enclosure_id = None

        # Components (initialized later)
        self.logger = self._setup_logger()
        self.controller: Optional[BaseController] = None
        self.config_manager: Optional[ConfigManager] = None
        self.disk_mapper: Optional[DiskMapper] = None
        self.truenas_api: Optional[TrueNASAPI] = None

        # Data
        self.disks: List[Disk] = []

    def _setup_logger(self) -> logging.Logger:
        """Set up the logger for the application"""
        logger = logging.getLogger("storage-topology")
        logger.setLevel(logging.INFO)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        ch.setFormatter(formatter)

        logger.addHandler(ch)

        return logger

    def parse_arguments(self) -> None:
        """Parse command line arguments"""
        parser = argparse.ArgumentParser(
            description="Identifies physical disk locations by matching controller information with system devices."
        )

        parser.add_argument("-j", "--json", action="store_true", help="Output results in JSON format")
        parser.add_argument("-z", "--zpool", action="store_true", help="Display ZFS pool information")
        parser.add_argument("-l", "--long", action="store_true", help="Display all available disk information")
        parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
        parser.add_argument("-q", "--quiet", action="store_true", help="Suppress INFO messages")
        parser.add_argument("--query", nargs='?', const='all', metavar="DISK_NAME",
                          help="Query disk information from TrueNAS")
        parser.add_argument("--sort-by", choices=["disk", "serial", "model", "size", "description", "pool"],
                          default="pool", help="Sort query results by specified field")
        parser.add_argument("--pool-disks-only", action="store_true",
                          help="Show only disks that are part of ZFS pools")
        parser.add_argument("--pool", metavar="POOL_NAME",
                          help="Show only disks in the specified ZFS pool")
        parser.add_argument("--update", metavar="DISK_NAME",
                          help="Update disk description in TrueNAS")
        parser.add_argument("--update-all", action="store_true",
                          help="Update all disk descriptions in TrueNAS")
        parser.add_argument("--locate", metavar="DISK_NAME",
                          help="Turn on the identify LED for the specified disk")
        parser.add_argument("--locate-off", metavar="DISK_NAME",
                          help="Turn off the identify LED for the specified disk")
        parser.add_argument("--locate-all", action="store_true",
                          help="Turn on the identify LED for all disks")
        parser.add_argument("--locate-all-off", action="store_true",
                          help="Turn off the identify LED for all disks")
        parser.add_argument("--wait", type=int, metavar="SECONDS",
                          help="LED blink duration in seconds (1-60)")
        parser.add_argument("-e", "--enclosure", nargs='?', const='all', metavar="ENCLOSURE_ID",
                          help="Show enclosure information and generate config snippet")

        args = parser.parse_args()

        # Set instance variables
        self.json_output = args.json
        self.show_zpool = args.zpool
        self.long_output = args.long
        self.verbose = args.verbose
        self.quiet = args.quiet
        self.query_disk = args.query
        self.update_disk = args.update
        self.update_all_disks = args.update_all
        self.sort_by = args.sort_by
        self.locate_disk_name = args.locate
        self.locate_off_disk_name = args.locate_off
        self.locate_all = args.locate_all
        self.locate_all_off = args.locate_all_off
        self.wait_seconds = args.wait
        self.pool_disks_only = args.pool_disks_only
        self.pool_name = args.pool
        self.enclosure_id = args.enclosure

        # Configure logger
        if self.verbose:
            self.logger.setLevel(logging.DEBUG)
            for handler in self.logger.handlers:
                handler.setLevel(logging.DEBUG)
        elif self.quiet:
            self.logger.setLevel(logging.WARNING)
            for handler in self.logger.handlers:
                handler.setLevel(logging.WARNING)

        # Validate wait seconds
        if self.wait_seconds is not None:
            if self.wait_seconds < 1 or self.wait_seconds > 60:
                self.logger.error("Wait time must be between 1 and 60 seconds")
                sys.exit(1)

    def detect_controller(self) -> BaseController:
        """Detect and return available controller

        Returns:
            BaseController instance

        Raises:
            SystemExit: If no controller is found
        """
        self.logger.info("Detecting available controllers...")

        # Try storcli2/storcli
        storcli_controller = StorcliController(logger=self.logger)
        if storcli_controller.is_available():
            self.logger.info(f"Selected controller: storcli ({storcli_controller.cmd})")
            return storcli_controller

        # Try sas2ircu
        sas2_controller = SasIrcuController(logger=self.logger, controller_type="sas2ircu")
        if sas2_controller.is_available():
            self.logger.info("Selected controller: sas2ircu")
            return sas2_controller

        # Try sas3ircu
        sas3_controller = SasIrcuController(logger=self.logger, controller_type="sas3ircu")
        if sas3_controller.is_available():
            self.logger.info("Selected controller: sas3ircu")
            return sas3_controller

        self.logger.error("No controller found. Please install storcli, storcli2, sas2ircu, or sas3ircu.")
        sys.exit(1)

    def run(self) -> None:
        """Main entry point for the application"""
        # Parse arguments
        self.parse_arguments()

        # Initialize TrueNAS API
        self.truenas_api = TrueNASAPI(logger=self.logger)

        # Handle query operations (no controller needed)
        if self.query_disk:
            self._handle_query()
            return

        # Handle enclosure info
        if self.enclosure_id is not None:
            self._handle_enclosure_info()
            return

        # Detect controller
        self.controller = self.detect_controller()

        # Handle LED operations
        if self.locate_disk_name:
            self._handle_locate_disk(self.locate_disk_name, False)
            return

        if self.locate_off_disk_name:
            self._handle_locate_disk(self.locate_off_disk_name, True)
            return

        if self.locate_all:
            self._handle_locate_all_disks(False)
            return

        if self.locate_all_off:
            self._handle_locate_all_disks(True)
            return

        # Load configuration
        self.config_manager = ConfigManager(logger=self.logger)
        self.disk_mapper = DiskMapper(self.config_manager, logger=self.logger)

        # Get disks and enclosures from controller
        self.logger.info("Collecting disk information from controller...")
        controller_disks = self.controller.get_disks()

        self.logger.info("Getting enclosure information...")
        enclosures = self.controller.get_enclosures()

        # Match with system devices
        self.disks = self.disk_mapper.match_with_system_devices(controller_disks)

        # Map locations
        self.disks = self.disk_mapper.map_locations(self.disks, enclosures)

        # Handle update operations
        if self.update_disk:
            self._handle_update_disk()
            return

        if self.update_all_disks:
            self._handle_update_all_disks()
            return

        # Display results
        self._display_results()

    def _handle_query(self) -> None:
        """Handle disk query operation"""
        disk_info = self.truenas_api.query_disk(
            None if self.query_disk == 'all' else self.query_disk
        )

        # Get pool mapping
        pool_disk_mapping = self.truenas_api.get_pool_disk_mapping()

        # Filter by pool if requested
        if self.pool_disks_only:
            disk_info = [d for d in disk_info if d.get("name") in pool_disk_mapping]

        if self.pool_name:
            disk_info = [d for d in disk_info
                        if d.get("name") in pool_disk_mapping and
                        pool_disk_mapping[d.get("name")].get("pool") == self.pool_name]

        # Display
        if self.json_output:
            print(json.dumps(disk_info, indent=2))
        else:
            self._display_query_results(disk_info, pool_disk_mapping)

    def _display_query_results(self, disk_info: List[Dict], pool_disk_mapping: Dict) -> None:
        """Display query results in table format"""
        if not disk_info:
            print("No disks found")
            return

        print(f"\nFound {len(disk_info)} disks")

        headers = ["Disk", "Pool", "Serial", "Model", "Size", "Description"]
        table_data = []

        for disk in disk_info:
            disk_name = disk.get("name", "N/A")
            size_bytes = disk.get("size", 0)

            if size_bytes:
                if size_bytes >= 1000000000000:
                    size_str = f"{size_bytes / 1000000000000:.2f} TB"
                else:
                    size_str = f"{size_bytes / 1000000000:.2f} GB"
            else:
                size_str = "N/A"

            pool_name = pool_disk_mapping.get(disk_name, {}).get("pool", "Not in pool")

            row = [disk_name, pool_name, disk.get("serial", "N/A"),
                  disk.get("model", "N/A"), size_str, disk.get("description", "")]
            table_data.append(row)

        # Sort
        sort_map = {"disk": 0, "pool": 1, "serial": 2, "model": 3, "size": 4, "description": 5}
        table_data.sort(key=lambda x: x[sort_map.get(self.sort_by, 0)])

        # Print table
        self._print_table(headers, table_data)

    def _handle_enclosure_info(self) -> None:
        """Handle enclosure information display"""
        # Detect controller and get enclosures
        controller = self.detect_controller()
        enclosures = controller.get_enclosures()

        if not enclosures:
            print("No enclosures found")
            return

        # Filter by enclosure_id if specified
        if self.enclosure_id and self.enclosure_id != 'all':
            enclosures = [e for e in enclosures if e.enclosure_id == self.enclosure_id]
            if not enclosures:
                print(f"No enclosure found with ID: {self.enclosure_id}")
                return

        # Display enclosure information
        print("\n" + "=" * 80)
        print("Enclosure Information")
        print("=" * 80)

        for enc in enclosures:
            print(f"\nController: {enc.controller_id}")
            print(f"Enclosure ID: {enc.enclosure_id}")
            if enc.product_id:
                print(f"Product ID: {enc.product_id}")
            if enc.logical_id:
                print(f"Logical ID: {enc.logical_id}")
            print(f"Slots: {enc.slots}")
            print(f"State: OK")  # Could be enhanced with actual state if available

        # Display config snippet
        print("\n" + "=" * 80)
        print("Config Snippet for storage_topology.conf")
        print("=" * 80)
        print("\n# Add to 'enclosures:' section:\n")

        for enc in enclosures:
            # Use product_id or logical_id as the config ID, fallback to enclosure_type
            config_id = enc.product_id or enc.logical_id or enc.enclosure_type or f"Enclosure-{enc.enclosure_id}"
            config_name = config_id  # Use same as name by default

            # Strip whitespace from config_id
            config_id = config_id.strip()

            print(f'  - id: "{config_id}"')
            print(f'    name: "{config_name}"')
            print(f'    start_slot: 1')
            print()

    def _handle_locate_disk(self, disk_name: str, turn_off: bool) -> None:
        """Handle single disk LED operation"""
        # Find disk by name
        disk_name_short = disk_name.replace("/dev/", "")

        for disk in self.controller.get_disks():
            if disk.dev_name.endswith(disk_name_short):
                success = self.controller.locate_disk(disk, turn_off, self.wait_seconds)
                if success:
                    action = "off" if turn_off else "on"
                    print(f"Successfully turned {action} LED for disk {disk_name}")
                    return

        self.logger.error(f"Disk not found: {disk_name}")
        sys.exit(1)

    def _handle_locate_all_disks(self, turn_off: bool) -> None:
        """Handle all disks LED operation"""
        wait_time = self.wait_seconds if self.wait_seconds is not None else (0 if turn_off else 5)
        success_count, failed_count = self.controller.locate_all_disks(turn_off, wait_time if not turn_off else None)

        action = "off" if turn_off else "on"
        print(f"Successfully turned {action} {success_count} disk LEDs")
        if failed_count > 0:
            print(f"Failed to turn {action} {failed_count} disk LEDs")

    def _handle_update_disk(self) -> None:
        """Handle single disk update operation"""
        # Find disk
        for disk in self.disks:
            if disk.short_name == self.update_disk or disk.dev_name == self.update_disk:
                if disk.enclosure_name and disk.physical_slot:
                    success = self.truenas_api.update_disk_description(
                        disk.short_name,
                        disk.enclosure_name,
                        str(disk.physical_slot),
                        str(disk.logical_disk)
                    )
                    if success:
                        print(f"Successfully updated disk: {disk.short_name}")
                    return

        self.logger.error(f"Disk not found or no location info: {self.update_disk}")
        sys.exit(1)

    def _handle_update_all_disks(self) -> None:
        """Handle update all disks operation"""
        self.truenas_api.update_all_disks(self.disks)

    def _display_results(self) -> None:
        """Display disk inventory results"""
        # Sort disks
        self.disks.sort(key=lambda d: (d.enclosure_name, d.physical_slot))

        if self.json_output:
            output = [disk.to_dict() for disk in self.disks]
            print(json.dumps(output, indent=2))
        else:
            self._display_table()

        # Show ZFS pool information if requested
        if self.show_zpool:
            self._display_zpool_info()

    def _display_table(self) -> None:
        """Display disks in table format"""
        if self.long_output:
            # Long format: show all available disk information
            headers = ["Device", "Name", "Slot", "Ctrl", "Enc", "Drive",
                      "Serial", "Model", "Manufacturer", "WWN", "Size",
                      "Enclosure", "PhysSlot", "LogDisk", "Location"]

            table_data = []
            for disk in self.disks:
                row = [
                    disk.dev_name,
                    disk.short_name,
                    f"{disk.enclosure}:{disk.slot}",
                    disk.controller,
                    disk.enclosure,
                    str(disk.slot),
                    disk.serial,
                    disk.model,
                    disk.manufacturer,
                    disk.wwn,
                    disk.size,
                    disk.enclosure_name,
                    str(disk.physical_slot),
                    str(disk.logical_disk),
                    disk.location
                ]
                table_data.append(row)
        else:
            # Short format: show essential information only
            headers = ["Device", "Serial", "Model", "Controller", "Enclosure",
                      "Slot", "Location"]

            table_data = []
            for disk in self.disks:
                row = [
                    disk.dev_name,
                    disk.serial,
                    disk.model,
                    disk.controller,
                    disk.enclosure_name,
                    str(disk.physical_slot),
                    disk.location
                ]
                table_data.append(row)

        self._print_table(headers, table_data)

    def _print_table(self, headers: List[str], data: List[List[str]]) -> None:
        """Print a formatted table"""
        # Calculate column widths
        widths = [len(h) for h in headers]
        for row in data:
            for i, val in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(str(val)))

        # Print header
        header_parts = [h.ljust(widths[i]) for i, h in enumerate(headers)]
        header_line = "  ".join(header_parts)
        print("-" * len(header_line))
        print(header_line)
        print("-" * len(header_line))

        # Print data
        for row in data:
            row_parts = [str(val).ljust(widths[i]) for i, val in enumerate(row)]
            print("  ".join(row_parts))

        print("-" * len(header_line))

    def _display_zpool_info(self) -> None:
        """Display ZFS pool information with disk locations"""
        import subprocess
        import re

        self.logger.info("Displaying ZFS pool information")

        # Create disk lookup dictionary
        disk_info = {disk.dev_name: disk for disk in self.disks}

        # Get zpool status
        try:
            zpool_output = subprocess.check_output(["zpool", "status", "-LP"], universal_newlines=True)

            print("\n" + "="*80)
            print("ZFS Pool Status with Disk Locations")
            print("="*80 + "\n")

            # Process each line
            for line in zpool_output.splitlines():
                # If the line contains "/dev/" then it's a disk
                if "/dev/" in line:
                    # Extract the device name and status from the line
                    indentation = re.match(r"^(\s*)", line).group(1)
                    parts = line.strip().split()
                    if not parts:
                        print(line)
                        continue

                    dev = parts[0]
                    status = parts[1] if len(parts) > 1 else ""

                    # If the last character is a digit, then it's a partition
                    # and we need to find the disk name
                    if re.search(r"(p|)[0-9]+$", dev):
                        dev = self._get_disk_from_partition(dev)

                    # Find the device in our disk info
                    disk = disk_info.get(dev)
                    if disk:
                        print(f"{indentation}{parts[0]} {status} {disk.location} (S/N: {disk.serial})")
                    else:
                        print(line)
                else:
                    print(line)

        except subprocess.SubprocessError as e:
            self.logger.error(f"Error getting ZFS pool information: {e}")

    def _get_disk_from_partition(self, dev: str) -> str:
        """Get disk name from partition name

        Args:
            dev: Device path (e.g., /dev/sda1, /dev/nvme0n1p1)

        Returns:
            Base disk device path
        """
        import re

        # Handle NVMe partitions (nvme0n1p1 -> nvme0n1)
        if re.search(r"nvme.*p[0-9]+$", dev):
            return re.sub(r"p[0-9]+$", "", dev)
        # Handle traditional partitions (sda1 -> sda)
        else:
            return re.sub(r"[0-9]+$", "", dev)
