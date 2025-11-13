#!/usr/bin/env python3
"""
Storage Topology Tool - Refactored Version

This script identifies physical disk locations by matching controller information with system devices.
It supports LSI MegaRAID controllers via storcli/storcli2 and LSI SAS controllers via sas2ircu/sas3ircu.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import yaml
from typing import List, Dict, Any, Optional, Tuple, Set

# Import our new modules
from storage_models import DiskInfo, EnclosureConfig, DiskMapping
from storage_controllers import detect_controller, StorageController
from location_mapper import LocationMapper
from truenas_client import TrueNASClient


class StorageTopology:
    """Main class for the Storage Topology tool
    
    Refactored to use modular components for better maintainability.
    """

    def __init__(self):
        self.json_output = False
        self.show_zpool = False
        self.verbose = False
        self.quiet = False
        self.logger = self._setup_logger()
        
        # Components
        self.controller: Optional[StorageController] = None
        self.location_mapper = LocationMapper(self.logger)
        self.truenas_client = TrueNASClient(self.logger)
        
        # Data
        self.disks: List[DiskInfo] = []
        self.system_disks: Dict[str, Any] = {}
        
        # Arguments
        self.query_disk = None
        self.update_disk = None
        self.update_all_disks = False
        self.sort_by = "pool"
        self.pool_disks_only = False
        self.pool_name = None
        self.enclosure_id = None
        self.locate_disk_name = None
        self.locate_off_disk_name = None
        self.locate_all = False
        self.locate_all_off = False
        self.wait_seconds = None

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
        parser.add_argument("--enclosure", nargs='?', const='all', metavar="ENCLOSURE_ID",
                          help="Show enclosure information")
        
        args = parser.parse_args()
        
        self.json_output = args.json
        self.show_zpool = args.zpool
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

    def load_config(self) -> None:
        """Load configuration file"""
        config_file = os.path.expanduser("./storage_topology.conf")
        
        if not os.path.exists(config_file):
            self.logger.warning(f"Configuration file {config_file} not found. Using default settings.")
            return
        
        try:
            self.logger.info(f"Loading configuration from {config_file}")
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            if not config:
                self.logger.warning(f"Configuration file {config_file} is empty or invalid")
                return
            
            # Load enclosure configurations
            if 'enclosures' in config:
                self.logger.info(f"Found {len(config['enclosures'])} enclosure configurations")
                for encl_data in config['enclosures']:
                    try:
                        encl_config = EnclosureConfig.from_dict(encl_data)
                        self.location_mapper.add_enclosure_config(encl_config)
                    except Exception as e:
                        self.logger.warning(f"Error loading enclosure config: {e}")
            
            # Load custom disk mappings
            if 'disks' in config:
                self.logger.info(f"Found {len(config['disks'])} custom disk mappings")
                for disk_data in config['disks']:
                    try:
                        disk_mapping = DiskMapping.from_dict(disk_data)
                        self.location_mapper.add_disk_mapping(disk_mapping)
                    except Exception as e:
                        self.logger.warning(f"Error loading disk mapping: {e}")
        
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing YAML in configuration file: {e}")
        except IOError as e:
            self.logger.error(f"Error reading configuration file: {e}")

    def get_lsblk_disks(self) -> Dict[str, Any]:
        """Get disk information from lsblk"""
        self.logger.info("Getting system block device information")
        
        try:
            cmd = ["lsblk", "-p", "-d", "-o", 
                  "NAME,WWN,VENDOR,MODEL,REV,SERIAL,SIZE,PTUUID,HCTL,TRAN,TYPE", "-J"]
            output = subprocess.check_output(cmd, universal_newlines=True)
            data = json.loads(output)
            
            self.logger.debug(f"Found {len(data.get('blockdevices', []))} block devices")
            return data
        except Exception as e:
            self.logger.error(f"Error getting lsblk information: {e}")
            return {"blockdevices": []}

    def combine_disk_info(self, controller_disks: List[DiskInfo], 
                         lsblk_data: Dict[str, Any]) -> List[DiskInfo]:
        """Combine controller disk info with system block device info"""
        self.logger.info("Matching controller devices with system devices")
        
        combined_disks = []
        seen_slots = set()  # Track by slot to avoid duplicates
        
        for block_device in lsblk_data.get("blockdevices", []):
            dev_name = block_device.get("name", "")
            wwn = block_device.get("wwn", "")
            serial = block_device.get("serial", "")
            
            # Normalize WWN
            my_wwn = wwn.replace("0x", "").lower() if wwn else ""
            
            # Find matching disk from controller
            matched_disk = None
            for ctrl_disk in controller_disks:
                ctrl_wwn = ctrl_disk.wwn.replace("0x", "").lower() if ctrl_disk.wwn else ""
                
                # Match by WWN or serial
                if (ctrl_wwn and ctrl_wwn == my_wwn) or (ctrl_disk.serial and ctrl_disk.serial == serial):
                    matched_disk = ctrl_disk
                    break
            
            if matched_disk:
                # Check for duplicates
                if matched_disk.slot in seen_slots:
                    # Prefer multipath devices (dm-*)
                    if dev_name.startswith("/dev/dm-"):
                        # Remove the previous entry
                        combined_disks = [d for d in combined_disks if d.slot != matched_disk.slot]
                        seen_slots.discard(matched_disk.slot)
                    else:
                        continue
                
                # Create new disk with combined info
                disk = DiskInfo(
                    dev_name=dev_name,
                    name=matched_disk.name,
                    slot=matched_disk.slot,
                    controller=matched_disk.controller,
                    enclosure=matched_disk.enclosure,
                    drive=matched_disk.drive,
                    serial=matched_disk.serial or serial,
                    model=matched_disk.model or block_device.get("model", ""),
                    manufacturer=matched_disk.manufacturer or block_device.get("vendor", ""),
                    wwn=matched_disk.wwn or wwn,
                    vendor=block_device.get("vendor", "")
                )
                
                combined_disks.append(disk)
                seen_slots.add(matched_disk.slot)
        
        return combined_disks

    def display_results(self, disks: List[DiskInfo]) -> None:
        """Display disk information"""
        if self.json_output:
            output = [disk.to_dict() for disk in disks]
            print(json.dumps(output, indent=2))
        else:
            self._display_table(disks)

    def _display_table(self, disks: List[DiskInfo]) -> None:
        """Display disks in table format"""
        # Compact format by default - only show essential columns
        if self.verbose:
            # Verbose: show all columns
            headers = ["Device", "Name", "Slot", "Ctrl", "Enc", "Drive", 
                      "Serial", "Model", "Manufacturer", "WWN", 
                      "Enclosure", "PhysSlot", "LogDisk", "Location"]
            rows = [disk.to_list() for disk in disks]
        else:
            # Compact: only show the most useful columns
            headers = ["Device", "Serial", "Model", "Enclosure", "Slot", "Location"]
            rows = []
            for disk in disks:
                rows.append([
                    disk.dev_name,
                    disk.serial,
                    disk.model,
                    disk.enclosure_name,
                    str(disk.physical_slot),
                    disk.location
                ])
        
        # Calculate column widths
        widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(str(val)))
        
        # Print header
        header_parts = [h.ljust(widths[i]) for i, h in enumerate(headers)]
        header_line = "  ".join(header_parts)
        print(header_line)
        
        # Print rows
        for row in rows:
            row_parts = [str(val).ljust(widths[i]) for i, val in enumerate(row) if i < len(widths)]
            print("  ".join(row_parts))

    def query_truenas_disks(self, disk_name: str) -> None:
        """Query disk information from TrueNAS"""
        if disk_name == 'all':
            disks = self.truenas_client.query_all_disks()
        else:
            disk = self.truenas_client.query_disk(disk_name)
            disks = [disk] if disk else []
        
        if not disks:
            print(f"No disk found: {disk_name}")
            return
        
        # Get pool mappings
        pool_mapping = self.truenas_client.get_pool_disk_mapping()
        
        # Filter by pool if requested
        if self.pool_disks_only:
            disks = [d for d in disks if d.get("name") in pool_mapping]
        
        if self.pool_name:
            disks = [d for d in disks if 
                    d.get("name") in pool_mapping and 
                    pool_mapping[d.get("name")].get("pool") == self.pool_name]
        
        # Display
        if self.json_output:
            print(json.dumps(disks, indent=2))
        else:
            self._display_truenas_table(disks, pool_mapping)

    def _display_truenas_table(self, disks: List[Dict], pool_mapping: Dict) -> None:
        """Display TrueNAS disks in table format"""
        headers = ["Disk", "Pool", "Serial", "Model", "Size", "Description"]
        
        rows = []
        for disk in disks:
            disk_name = disk.get("name", "N/A")
            
            # Format size
            size_bytes = disk.get("size", 0)
            if size_bytes >= 1000000000000:
                size_str = f"{size_bytes / 1000000000000:.2f} TB"
            else:
                size_str = f"{size_bytes / 1000000000:.2f} GB"
            
            # Get pool
            pool_name = "Not in pool"
            if disk_name in pool_mapping:
                pool_name = pool_mapping[disk_name]["pool"]
            
            rows.append([
                disk_name,
                pool_name,
                disk.get("serial", "N/A"),
                disk.get("model", "N/A"),
                size_str,
                disk.get("description", ""),
                size_bytes  # For sorting
            ])
        
        # Sort
        sort_idx = {"disk": 0, "pool": 1, "serial": 2, "model": 3, "size": 6, "description": 5}
        idx = sort_idx.get(self.sort_by, 0)
        
        if self.sort_by == "size":
            rows.sort(key=lambda x: x[idx], reverse=True)
        elif self.sort_by == "pool":
            rows.sort(key=lambda x: (x[idx] == "None", x[idx]))
        else:
            rows.sort(key=lambda x: (x[idx] is None, x[idx] == "", x[idx]))
        
        # Remove sort column
        for row in rows:
            row.pop()
        
        # Calculate widths
        widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                widths[i] = max(widths[i], len(str(val)))
        
        # Print
        header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
        print("-" * len(header_line))
        print(header_line)
        print("-" * len(header_line))
        
        for row in rows:
            print("  ".join(str(val).ljust(widths[i]) for i, val in enumerate(row)))
        
        print("-" * len(header_line))
        print(f"Sorted by: {self.sort_by.capitalize()}")

    def update_truenas_disk(self, disk_name: str, location: str, 
                           slot: str, disk_nr: str) -> None:
        """Update a disk description in TrueNAS"""
        disk = self.truenas_client.query_disk(disk_name)
        if not disk:
            self.logger.error(f"Disk not found: {disk_name}")
            return
        
        identifier = disk.get("identifier")
        if not identifier:
            self.logger.error(f"Could not get identifier for disk: {disk_name}")
            return
        
        # Build description
        current_desc = disk.get("description", "").strip()
        location_info = f"Loc:{location};SLOT:{slot};DISK:{disk_nr}"
        
        # Remove old location info
        new_desc = re.sub(r'Loc:\S+', '', current_desc).strip()
        
        # Add new location info
        if new_desc:
            updated_desc = f"{new_desc} {location_info}"
        else:
            updated_desc = location_info
        
        # Update
        if self.truenas_client.update_disk_description(identifier, updated_desc):
            print(f"Updated disk: {disk_name}")
        else:
            print(f"Failed to update disk: {disk_name}")

    def locate_disk(self, disk_name: str, turn_off: bool = False) -> None:
        """Locate a disk by turning on/off its LED"""
        # Get serial number
        try:
            cmd = ["lsblk", "-dno", "SERIAL", f"/dev/{disk_name}"]
            serial = subprocess.check_output(cmd, universal_newlines=True).strip()
            
            if not serial:
                self.logger.error(f"Could not get serial for disk: {disk_name}")
                return
            
            # Find disk in controller
            for disk in self.controller.get_disks():
                if disk.serial == serial:
                    self.controller.locate_disk(disk, turn_off, self.wait_seconds)
                    action = "off" if turn_off else "on"
                    print(f"Successfully turned {action} LED for disk {disk_name}")
                    return
            
            self.logger.error(f"Disk not found in controller: {disk_name}")
        except Exception as e:
            self.logger.error(f"Error locating disk: {e}")

    def run(self) -> None:
        """Main execution method"""
        self.parse_arguments()
        
        # Handle query-only operations
        if self.query_disk:
            if not self.truenas_client.is_available():
                self.logger.error("midclt not available for TrueNAS queries")
                sys.exit(1)
            self.query_truenas_disks(self.query_disk)
            return
        
        # Detect controller
        self.logger.info("Detecting controllers...")
        self.controller = detect_controller(self.logger)
        
        if not self.controller:
            self.logger.error("No controller found")
            sys.exit(1)
        
        self.logger.info(f"Using controller: {self.controller.get_command_name()}")
        
        # Handle enclosure info
        if self.enclosure_id is not None:
            self.show_enclosure_info()
            return
        
        # Handle locate operations
        if self.locate_disk_name:
            self.locate_disk(self.locate_disk_name, False)
            return
        
        if self.locate_off_disk_name:
            self.locate_disk(self.locate_off_disk_name, True)
            return
        
        if self.locate_all:
            success, failed = self.controller.locate_all_disks(False, self.wait_seconds or 5)
            print(f"Turned on {success} LEDs, {failed} failed")
            return
        
        if self.locate_all_off:
            success, failed = self.controller.locate_all_disks(True, None)
            print(f"Turned off {success} LEDs, {failed} failed")
            return
        
        # Load configuration
        self.load_config()
        
        # Get disks from controller
        self.logger.info("Getting disk information from controller...")
        controller_disks = self.controller.get_disks()
        
        # Get enclosures
        self.logger.info("Getting enclosure information...")
        enclosures = self.controller.get_enclosures()
        
        # Get system disks
        lsblk_data = self.get_lsblk_disks()
        
        # Combine information
        combined_disks = self.combine_disk_info(controller_disks, lsblk_data)
        
        # Map locations
        self.logger.info("Mapping physical locations...")
        self.disks = self.location_mapper.map_all_disks(combined_disks, enclosures)
        
        # Handle update operations
        if self.update_disk:
            disk_to_update = next((d for d in self.disks if d.dev_name.endswith(self.update_disk)), None)
            if disk_to_update:
                self.update_truenas_disk(
                    self.update_disk, 
                    disk_to_update.enclosure_name,
                    str(disk_to_update.physical_slot),
                    str(disk_to_update.logical_disk)
                )
            else:
                self.logger.error(f"Disk not found: {self.update_disk}")
            return
        
        if self.update_all_disks:
            updated = 0
            for disk in self.disks:
                if disk.enclosure_name and disk.physical_slot:
                    disk_name = disk.dev_name.replace("/dev/", "")
                    self.update_truenas_disk(
                        disk_name,
                        disk.enclosure_name,
                        str(disk.physical_slot),
                        str(disk.logical_disk)
                    )
                    updated += 1
            print(f"Updated {updated} disks")
            return
        
        # Display results
        self.display_results(self.disks)
        
        # Show ZFS info if requested
        if self.show_zpool:
            self.display_zpool_info()

    def show_enclosure_info(self) -> None:
        """Show enclosure information"""
        enclosures = self.controller.get_enclosures()
        
        if not enclosures:
            print("No enclosures found")
            return
        
        # Filter if specific enclosure requested
        if self.enclosure_id and self.enclosure_id != 'all':
            enclosures = [e for e in enclosures if e.enclosure_id == self.enclosure_id]
        
        # Display
        print("\n" + "="*80)
        print("Enclosure Information")
        print("="*80)
        
        for enc in enclosures:
            print(f"\nController: {enc.controller}")
            print(f"Enclosure ID: {enc.enclosure_id}")
            if enc.product_id:
                print(f"Product ID: {enc.product_id}")
            if enc.logical_id:
                print(f"Logical ID: {enc.logical_id}")
            print(f"Slots: {enc.num_slots}")
            if enc.state:
                print(f"State: {enc.state}")
        
        # Generate config snippet
        print("\n" + "="*80)
        print("Config Snippet for storage_topology.conf")
        print("="*80)
        print("\n# Add to 'enclosures:' section:\n")
        
        for enc in enclosures:
            id_val = enc.logical_id or enc.product_id or enc.enclosure_id
            name = enc.product_id.replace(" ", "-") if enc.product_id else f"Enclosure-{enc.enclosure_id}"
            
            print(f"  - id: \"{id_val}\"")
            print(f"    name: \"{name}\"")
            print(f"    start_slot: 1")
            print()

    def display_zpool_info(self) -> None:
        """Display ZFS pool information with disk locations"""
        try:
            output = subprocess.check_output(["zpool", "status", "-LP"], 
                                           universal_newlines=True)
            
            # Create disk lookup
            disk_map = {d.dev_name: d for d in self.disks}
            
            for line in output.splitlines():
                if "/dev/" in line:
                    parts = line.strip().split()
                    if not parts:
                        print(line)
                        continue
                    
                    dev = parts[0]
                    status = parts[1] if len(parts) > 1 else ""
                    
                    # Get base device
                    if re.search(r'(p|)[0-9]+$', dev):
                        base_dev = re.sub(r'p?[0-9]+$', '', dev)
                    else:
                        base_dev = dev
                    
                    # Find disk info
                    disk = disk_map.get(base_dev)
                    if disk:
                        indent = re.match(r"^(\s*)", line).group(1)
                        print(f"{indent}{dev} {status} {disk.location} (S/N: {disk.serial})")
                    else:
                        print(line)
                else:
                    print(line)
        
        except Exception as e:
            self.logger.error(f"Error displaying ZFS info: {e}")


if __name__ == "__main__":
    try:
        app = StorageTopology()
        app.run()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
