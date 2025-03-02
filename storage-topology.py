#!/usr/bin/env python3
"""
Serial Finder - Identifies physical disk locations by matching controller information with system devices

This script helps identify physical disk locations by correlating storage controller information
with system block devices. It supports storcli, sas2ircu, and sas3ircu controllers.
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Any, Tuple, Set


class StorageTopology:
    """Main class for the Serial Finder tool"""

    def __init__(self):
        self.json_output = False
        self.show_zpool = False
        self.verbose = False
        self.quiet = False
        self.controller = ""
        self.disks_table_json = {}
        self.lsblk_json = {}
        self.combined_disk = []
        self.combined_disk_complete = []
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Set up the logger for the application"""
        logger = logging.getLogger("serial-finder")
        logger.setLevel(logging.INFO)
        
        # Create console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        ch.setFormatter(formatter)
        
        # Add handler to logger
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
        
        args = parser.parse_args()
        
        # Set instance variables from parsed arguments
        self.json_output = args.json
        self.show_zpool = args.zpool
        self.verbose = args.verbose
        self.quiet = args.quiet
        
        # Configure logger based on verbosity/quiet settings
        if self.verbose:
            self.logger.setLevel(logging.DEBUG)
            for handler in self.logger.handlers:
                handler.setLevel(logging.DEBUG)
        elif self.quiet:
            self.logger.setLevel(logging.WARNING)
            for handler in self.logger.handlers:
                handler.setLevel(logging.WARNING)

    def check_command_exists(self, cmd: str) -> bool:
        """Check if a command exists in the system PATH"""
        return shutil.which(cmd) is not None

    def check_controller_found(self, controller: str) -> bool:
        """Check if a controller is found"""
        try:
            if controller == "storcli":
                # Check if a controller is found
                output = subprocess.check_output(["storcli", "show", "ctrlcount"], universal_newlines=True)
                controller_count_match = re.search(r"Controller Count = (\d+)", output)
                if controller_count_match and int(controller_count_match.group(1)) > 0:
                    return True
            elif controller == "sas2ircu":
                # Check if a controller is found
                subprocess.check_output(["sas2ircu", "LIST"], stderr=subprocess.STDOUT, universal_newlines=True)
                return True
            elif controller == "sas3ircu":
                # Check if a controller is found
                subprocess.check_output(["sas3ircu", "LIST"], stderr=subprocess.STDOUT, universal_newlines=True)
                return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        return False

    def detect_controllers(self) -> str:
        """Detect available controllers and select one to use"""
        storcli_found = self.check_command_exists("storcli")
        sas2ircu_found = self.check_command_exists("sas2ircu")
        sas3ircu_found = self.check_command_exists("sas3ircu")
        
        if not any([storcli_found, sas2ircu_found, sas3ircu_found]):
            self.logger.error("storcli, sas2ircu, and sas3ircu could not be found. Please install one of them first.")
            sys.exit(1)
        
        storcli_found_controller = False
        sas2ircu_found_controller = False
        sas3ircu_found_controller = False
        
        if storcli_found:
            storcli_found_controller = self.check_controller_found("storcli")
        
        if sas2ircu_found:
            sas2ircu_found_controller = self.check_controller_found("sas2ircu")
        
        if sas3ircu_found:
            sas3ircu_found_controller = self.check_controller_found("sas3ircu")
        
        if not any([storcli_found_controller, sas2ircu_found_controller, sas3ircu_found_controller]):
            self.logger.error("No controller found. Please check your storcli, sas2ircu, or sas3ircu installation.")
            sys.exit(1)
        
        # Select the controller to use
        if storcli_found_controller:
            return "storcli"
        elif sas2ircu_found_controller:
            return "sas2ircu"
        elif sas3ircu_found_controller:
            return "sas3ircu"
        
        return ""

    def get_storcli_disks(self) -> List[Dict[str, Any]]:
        """Get disk information using storcli"""
        self.logger.info("Getting storcli disk information")
        
        # Run storcli command to get all disk information in JSON format
        storcli_output = subprocess.check_output(["storcli", "/call", "show", "all", "J"], universal_newlines=True)
        storcli_json = json.loads(storcli_output)
        
        disks_list = []
        
        # Process each controller
        for controller in storcli_json.get("Controllers", []):
            response_data = controller.get("Response Data", {})
            physical_devices = response_data.get("Physical Device Information", {})
            
            # Find all drive keys (keys that start with "Drive /c" and don't contain "Detailed Information")
            drive_keys = [k for k in physical_devices.keys() 
                         if k.startswith("Drive /c") and "Detailed Information" not in k]
            
            for drive_key in drive_keys:
                # Extract controller number
                controller_match = re.search(r"/c(\d+)", drive_key)
                controller_num = controller_match.group(1) if controller_match else ""
                
                # Get basic drive info
                drive_info = physical_devices[drive_key][0]
                enclosure_slot = drive_info.get("EID:Slt", "")
                enclosure, slot = enclosure_slot.split(":") if ":" in enclosure_slot else ("", "")
                
                # Get detailed drive info
                detailed_key = f"{drive_key} - Detailed Information"
                detailed_info = physical_devices.get(detailed_key, {})
                
                # Extract useful fields from detailed info
                serial = ""
                model = ""
                manufacturer = ""
                wwn = ""
                
                # Navigate through the detailed info to find the fields
                for section in detailed_info:
                    for item in section:
                        if isinstance(item, dict):
                            serial = item.get("SN", serial)
                            model = item.get("Model Number", model)
                            manufacturer = item.get("Manufacturer Id", manufacturer)
                            wwn = item.get("WWN", wwn)
                
                # Only add disks with a serial number
                if serial:
                    disks_list.append({
                        "name": drive_key.split(" ")[1],
                        "slot": enclosure_slot,
                        "controller": controller_num,
                        "enclosure": enclosure,
                        "drive": slot,
                        "sn": serial,
                        "model": model,
                        "manufacturer": manufacturer,
                        "wwn": wwn
                    })
        
        return disks_list

    def get_sas2ircu_disks(self) -> List[Dict[str, Any]]:
        """Get disk information using sas2ircu"""
        self.logger.info("Getting sas2ircu disk information")
        disks_list = []
        
        try:
            # Get controller IDs
            list_output = subprocess.check_output(["sas2ircu", "list"], universal_newlines=True)
            controller_ids = []
            
            # Extract controller IDs from the output
            for line in list_output.splitlines():
                if re.match(r'^\s*\d+\s+SAS\d+', line):
                    controller_id = line.strip().split()[0]
                    controller_ids.append(controller_id)
            
            self.logger.debug(f"Found controller IDs: {controller_ids}")
            
            # Loop over each controller
            for controller_id in controller_ids:
                # Run sas2ircu display command
                display_output = subprocess.check_output(
                    ["sas2ircu", controller_id, "display"], 
                    universal_newlines=True
                )
                
                # Process the output to extract disk information
                lines = display_output.splitlines()
                i = 0
                while i < len(lines):
                    line = lines[i]
                    
                    # Look for the start of a disk entry
                    if "Device is a Hard disk" in line:
                        # Initialize disk variables
                        enclosure = ""
                        slot = ""
                        sasaddr = ""
                        state = ""
                        size = ""
                        manufacturer = ""
                        model = ""
                        firmware = ""
                        serial = ""
                        guid = ""
                        protocol = ""
                        drive_type = ""
                        
                        # Parse the disk information
                        j = i + 1
                        while j < len(lines) and not "Device is a" in lines[j]:
                            disk_line = lines[j]
                            
                            if "Enclosure #" in disk_line:
                                enclosure = disk_line.split(':')[1].strip()
                            elif "Slot #" in disk_line:
                                slot = disk_line.split(':')[1].strip()
                            elif "SAS Address" in disk_line:
                                sasaddr = disk_line.split(':')[1].strip()
                            elif "State" in disk_line:
                                state = disk_line.split(':')[1].strip()
                            elif "Size" in disk_line:
                                size = disk_line.split(':')[1].strip()
                            elif "Manufacturer" in disk_line:
                                manufacturer = disk_line.split(':')[1].strip()
                            elif "Model Number" in disk_line:
                                model = disk_line.split(':')[1].strip()
                            elif "Firmware Revision" in disk_line:
                                firmware = disk_line.split(':')[1].strip()
                            elif "Serial No" in disk_line:
                                serial = disk_line.split(':')[1].strip()
                            elif "GUID" in disk_line:
                                guid = disk_line.split(':')[1].strip()
                            elif "Protocol" in disk_line:
                                protocol = disk_line.split(':')[1].strip()
                            elif "Drive Type" in disk_line:
                                drive_type = disk_line.split(':')[1].strip()
                            
                            j += 1
                        
                        # Skip controller entries (typically have Manufacturer "LSI")
                        if manufacturer and manufacturer.strip() != "LSI":
                            disk_entry = {
                                "name": guid,
                                "wwn": guid,
                                "slot": drive_type,  # Using drive_type for the slot column
                                "controller": controller_id,
                                "enclosure": enclosure,
                                "drive": slot,
                                "sn": serial,
                                "model": model,
                                "manufacturer": manufacturer.strip(),
                                "sasaddr": sasaddr
                            }
                            disks_list.append(disk_entry)
                            
                            self.logger.debug(f"Found disk: {disk_entry}")
                        
                        # Move the index past this disk entry
                        i = j - 1
                    
                    i += 1
            
            self.logger.debug(f"Found {len(disks_list)} disks using sas2ircu")
            
        except Exception as e:
            self.logger.error(f"Error getting sas2ircu disk information: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
        
        return disks_list

    def get_lsblk_disks(self) -> Dict[str, Any]:
        """Get disk information from lsblk"""
        self.logger.info("Getting system block device information")
        
        # Run lsblk command with JSON output
        lsblk_output = subprocess.check_output(
            ["lsblk", "-p", "-d", "-o", "NAME,WWN,VENDOR,MODEL,REV,SERIAL,SIZE,PTUUID,HCTL,TRAN,TYPE", "-J"],
            universal_newlines=True
        )
        
        return json.loads(lsblk_output)

    def detect_multipath_disks(self) -> Tuple[str, bool]:
        """Detect multipath disks and return mapping"""
        # Check if multipath is available
        if (self.check_command_exists("multipath") and 
            self.check_command_exists("multipathd")):
            try:
                # Check if multipath is active
                paths_output = subprocess.check_output(
                    ["multipathd", "show", "paths", "format", "%d %w"],
                    stderr=subprocess.DEVNULL,
                    universal_newlines=True
                )
                
                if "." in paths_output:
                    # Multipath is active, get the mapping
                    maps_output = subprocess.check_output(
                        ["multipathd", "show", "maps", "format", "%w %d"],
                        stderr=subprocess.DEVNULL,
                        universal_newlines=True
                    )
                    return maps_output, True
            except subprocess.SubprocessError:
                pass
        
        # No multipath detected
        return "", False

    def combine_disk_info(self, disks_table_json: List[Dict[str, Any]], lsblk: Dict[str, Any]) -> List[List[str]]:
        """Combine disk information from controller and lsblk"""
        self.logger.info("Matching controller devices with system devices")
        
        # Get multipath mapping if available
        multipath_map, has_multipath = self.detect_multipath_disks()
        
        combined_disk = []
        
        # Process each block device from lsblk
        for block_device in lsblk.get("blockdevices", []):
            dev_name = block_device.get("name", "")
            wwn = block_device.get("wwn", "")
            vendor = block_device.get("vendor", "")
            model = block_device.get("model", "")
            rev = block_device.get("rev", "")
            serial = block_device.get("serial", "")
            size = block_device.get("size", "")
            ptuuid = block_device.get("ptuuid", "")
            hctl = block_device.get("hctl", "")
            tran = block_device.get("tran", "")
            dev_type = block_device.get("type", "")
            
            # Handle multipath devices
            multipath_name = ""
            if has_multipath and wwn:
                for line in multipath_map.splitlines():
                    if wwn in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            multipath_name = parts[1]
            
            # Look for matching disk in DISKS_TABLE_JSON by serial or WWN
            # Remove the "0x" from the WWN and convert to lowercase
            my_wwn = wwn.replace("0x", "").lower() if wwn else ""
            
            # Default values if no match is found
            name = "None"
            slot = "N/A"
            controller = "N/A"
            enclosure = "N/A"
            drive = "None"
            disk_serial = "N/A"
            disk_model = "N/A"
            manufacturer = "N/A"
            disk_wwn = "N/A"
            
            # Find matching disk
            disk_found = False
            if my_wwn:
                for disk in disks_table_json:
                    # Compare wwn or serial
                    disk_wwn_lower = str(disk.get("wwn", "")).lower()
                    disk_serial = str(disk.get("sn", ""))
                    
                    # Try to match by either WWN or serial number
                    if (disk_wwn_lower and disk_wwn_lower == my_wwn) or (disk_serial and disk_serial == serial):
                        name = disk.get("name", "None")
                        slot = disk.get("slot", "N/A")
                        controller = disk.get("controller", "N/A")
                        enclosure = disk.get("enclosure", "N/A")
                        drive = disk.get("drive", "None")
                        disk_serial = disk.get("sn", "N/A")
                        disk_model = disk.get("model", "N/A")
                        manufacturer = disk.get("manufacturer", "N/A")
                        disk_wwn = disk.get("wwn", "N/A")
                        disk_found = True
                        break
            
            # Handle special cases
            if drive == "n/a":
                drive = vendor
            if not drive:
                drive = "xxx"
            
            # For devices that weren't matched with controller info
            if not disk_found:
                # For ZD devices, add them with null values
                if "zd" in dev_name:
                    wwn = "null"
                    slot = "null"
                    controller = "null"
                    enclosure = "null"
                    drive = "null"
                    serial = "null" if not serial else serial
                    model = "null" if not model else model
                    manufacturer = "null" if not manufacturer else manufacturer
                    vendor = "null" if not vendor else vendor
            
            # Create the combined entry
            entry = [
                dev_name, wwn, slot, controller, enclosure, drive,
                serial, model, manufacturer, wwn, vendor,
                multipath_name if multipath_name else "-"
            ]
            
            combined_disk.append(entry)
        
        return combined_disk

    def detect_enclosure_types(self, disks_table_json: List[Dict[str, Any]], controller: str) -> Dict[str, Any]:
        """Detect enclosure types"""
        enclosure_map = {"Controllers": []}
        
        if controller == "storcli":
            enclosure_map = self.detect_storcli_enclosure_types()
        elif controller in ["sas2ircu", "sas3ircu"]:
            enclosure_map = self.detect_sas_enclosure_types(controller)
        
        return enclosure_map

    def detect_storcli_enclosure_types(self) -> Dict[str, Any]:
        """Detect enclosure types for storcli controllers"""
        enclosure_map = {"Controllers": []}
        
        try:
            # Get enclosure information
            enclosure_info_output = subprocess.check_output(
                ["storcli", "/call/eall", "show", "all", "J"],
                universal_newlines=True
            )
            enclosure_info = json.loads(enclosure_info_output)
            
            # Process each controller
            for controller_data in enclosure_info.get("Controllers", []):
                response_data = controller_data.get("Response Data", {})
                
                # Find enclosure keys
                enclosure_keys = [k for k in response_data.keys() if k.startswith("Enclosure")]
                
                for enclosure_key in enclosure_keys:
                    # Extract controller and enclosure numbers
                    controller_match = re.search(r"/c(\d+)/e(\d+)", enclosure_key)
                    if controller_match:
                        controller_num = controller_match.group(1)
                        enclosure_num = controller_match.group(2)
                        
                        # Get product identification
                        enclosure_data = response_data.get(enclosure_key, {})
                        inquiry_data = enclosure_data.get("Inquiry Data", {})
                        product_id = inquiry_data.get("Product Identification", "").rstrip()
                        
                        # Get number of slots
                        properties = enclosure_data.get("Properties", [{}])[0] if enclosure_data.get("Properties") else {}
                        num_slots = properties.get("Slots", "0")
                        
                        enclosure_map["Controllers"].append({
                            "controller": controller_num,
                            "enclosure": enclosure_num,
                            "type": product_id,
                            "slots": num_slots
                        })
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as e:
            self.logger.warning(f"Error getting storcli enclosure information: {e}")
        
        return enclosure_map

    def detect_sas_enclosure_types(self, controller: str) -> Dict[str, Any]:
        """Detect enclosure types for sas2ircu/sas3ircu controllers"""
        enclosure_map = {"Controllers": []}
        
        try:
            # Get list of controller IDs
            list_output = subprocess.check_output([controller, "list"], universal_newlines=True)
            controller_ids = []
            
            for line in list_output.splitlines():
                if re.match(r'^\d+$', line.strip()):
                    controller_ids.append(line.strip())
            
            # Build a list of controllers and enclosures
            for ctrl_id in controller_ids:
                display_output = subprocess.check_output(
                    [controller, ctrl_id, "display"],
                    universal_newlines=True
                )
                
                # Extract enclosure information
                encl_info = ""
                capture = False
                for line in display_output.splitlines():
                    if "Enclosure information" in line:
                        capture = True
                        continue
                    if capture:
                        if re.match(r'^-+$', line):
                            if encl_info:  # We've reached the end of the enclosure section
                                break
                            continue
                        encl_info += line + "\n"
                
                # Process enclosure information
                encl_number = ""
                logical_id = ""
                num_slots = ""
                start_slot = ""
                
                for line in encl_info.splitlines():
                    if "Enclosure#" in line:
                        encl_number = line.split(':')[1].strip()
                    elif "Logical ID" in line:
                        logical_id = line.split(':')[1].strip()
                    elif "Numslots" in line:
                        num_slots = line.split(':')[1].strip()
                    elif "StartSlot" in line:
                        start_slot = line.split(':')[1].strip()
                        
                        # Determine enclosure type based on number of slots
                        encl_type = "Unknown"
                        if num_slots and num_slots.isdigit():
                            slots = int(num_slots)
                            if slots > 20:
                                encl_type = "JBOD"
                            elif slots <= 8:
                                encl_type = "Internal"
                        
                        enclosure_map["Controllers"].append({
                            "controller": ctrl_id,
                            "enclosure": encl_number,
                            "logicalid": logical_id,
                            "type": encl_type,
                            "slots": num_slots,
                            "start_slot": start_slot
                        })
                        
                        # Reset for next enclosure
                        encl_number = logical_id = num_slots = start_slot = ""
        
        except (subprocess.SubprocessError, ValueError) as e:
            self.logger.warning(f"Error getting {controller} enclosure information: {e}")
        
        return enclosure_map

    def map_disk_locations(self, combined_disk: List[List[str]], controller: str) -> List[List[str]]:
        """Map enclosure and disk locations"""
        self.logger.info("Mapping physical locations")
        
        # Get enclosure type mapping
        enclosure_map = self.detect_enclosure_types(self.disks_table_json, controller)
        
        # Create a lookup dictionary for enclosure types
        enclosure_types = {}
        for encl in enclosure_map.get("Controllers", []):
            controller_id = encl.get("controller", "")
            enclosure = encl.get("enclosure", "")
            encl_type = encl.get("type", "Unknown")
            enclosure_types[f"{controller_id}_{enclosure}"] = encl_type
        
        # Find all unique enclosures
        unique_enclosures = set()
        for disk in combined_disk:
            enclosure = disk[4]  # Enclosure is at index 4
            if enclosure and enclosure != "null" and enclosure != "N/A" and enclosure.isdigit():
                unique_enclosures.add(enclosure)
        
        # Convert to sorted list for ordered access
        enclosures = sorted(list(unique_enclosures))
        
        combined_disk_complete = []
        
        # Process all disks
        for disk in combined_disk:
            dev_name = disk[0]
            name = disk[1]
            slot = disk[2]
            controller_id = disk[3]
            enclosure = disk[4]
            drive = disk[5]
            serial = disk[6]
            model = disk[7]
            manufacturer = disk[8]
            wwn = disk[9]
            vendor = disk[10]
            
            enclosure_name = ""
            encslot = 0
            encdisk = 0
            
            # Get enclosure type from lookup dictionary
            enclosure_key = f"{controller_id}_{enclosure}"
            enclosure_type = enclosure_types.get(enclosure_key, "Unknown")
            
            # Determine physical location based on enclosure position
            if enclosures and enclosure in enclosures:
                encl_idx = enclosures.index(enclosure)
                
                if encl_idx == 0:
                    enclosure_name = "Local"
                    try:
                        encslot = int(drive) + 1
                        encdisk = int(drive) + 0
                    except (ValueError, TypeError):
                        encslot = 0
                        encdisk = 0
                elif encl_idx == 1:
                    enclosure_name = enclosure_type
                    try:
                        encslot = int(drive) + 1
                        encdisk = int(drive) + 0
                    except (ValueError, TypeError):
                        encslot = 0
                        encdisk = 0
                elif encl_idx == 2:
                    enclosure_name = enclosure_type
                    try:
                        encslot = int(drive) + 31
                        encdisk = int(drive) + 30
                    except (ValueError, TypeError):
                        encslot = 0
                        encdisk = 0
                else:
                    enclosure_name = f"{enclosure_type}-{enclosure}"
                    try:
                        encslot = int(drive) + 1
                        encdisk = int(drive) + 0
                    except (ValueError, TypeError):
                        encslot = 0
                        encdisk = 0
            else:
                # Handle devices without enclosure information
                enclosure_name = f"Unknown-{enclosure}"
                try:
                    encslot = int(drive) + 1 if drive and drive != "null" and drive != "None" else 1
                    encdisk = int(drive) + 0 if drive and drive != "null" and drive != "None" else 0
                except (ValueError, TypeError):
                    encslot = 1
                    encdisk = 0
            
            location = f"{enclosure_name};SLOT:{encslot};DISK:{encdisk}"
            
            # Create the complete entry
            entry = [
                dev_name, name, slot, controller_id, enclosure, drive,
                serial, model, manufacturer, wwn, enclosure_name,
                str(encslot), str(encdisk), location
            ]
            
            combined_disk_complete.append(entry)
        
        return combined_disk_complete

    def get_disk_from_partition(self, dev: str) -> str:
        """Get disk from partition name"""
        # Handle NVMe partitions (nvme0n1p1 -> nvme0n1)
        if re.search(r"nvme.*p[0-9]+$", dev):
            return re.sub(r"p[0-9]+$", "", dev)
        # Handle traditional partitions (sda1 -> sda)
        else:
            return re.sub(r"[0-9]+$", "", dev)

    def display_zpool_info(self, combined_disk_complete: List[List[str]]) -> None:
        """Display ZFS pool disk information"""
        self.logger.info("Displaying ZFS pool information")
        
        # Convert combined_disk_complete to dictionary for easier lookup
        disk_info = {}
        for disk in combined_disk_complete:
            if len(disk) >= 14:
                disk_info[disk[0]] = {
                    "dev_name": disk[0],
                    "name": disk[1],
                    "slot": disk[2],
                    "controller": disk[3],
                    "enclosure": disk[4],
                    "drive": disk[5],
                    "serial": disk[6],
                    "model": disk[7],
                    "manufacturer": disk[8],
                    "wwn": disk[9],
                    "enclosure_name": disk[10],
                    "encslot": disk[11],
                    "encdisk": disk[12],
                    "location": disk[13]
                }
        
        # Get zpool status
        try:
            zpool_output = subprocess.check_output(["zpool", "status", "-LP"], universal_newlines=True)
            
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
                        dev = self.get_disk_from_partition(dev)
                    
                    # Find the device in our combined disk info
                    disk_data = disk_info.get(dev)
                    if disk_data:
                        disk_serial = disk_data.get("serial", "")
                        disk_location = disk_data.get("location", "")
                        print(f"{indentation}{dev} {status} {disk_location} (S/N: {disk_serial})")
                    else:
                        print(line)
                else:
                    print(line)
        
        except subprocess.SubprocessError as e:
            self.logger.error(f"Error getting ZFS pool information: {e}")

    def check_dependencies(self) -> None:
        """Check for required dependencies"""
        missing_deps = False
        
        for cmd in ["jq", "awk", "grep", "sed"]:
            if not self.check_command_exists(cmd):
                self.logger.error(f"Required dependency '{cmd}' is not installed.")
                missing_deps = True
        
        if missing_deps:
            self.logger.error("Please install the missing dependencies and try again.")
            sys.exit(1)

    def load_config(self) -> None:
        """Load configuration file"""
        config_file = os.path.expanduser("~/.config/serial-finder.conf")
        system_config = "/etc/serial-finder.conf"
        
        # Default configuration
        self.custom_mappings = {}
        
        # Try user config first, then system config
        if os.path.isfile(config_file):
            self.logger.info(f"Loading user configuration from {config_file}")
            # Implementation would depend on config file format
        elif os.path.isfile(system_config):
            self.logger.info(f"Loading system configuration from {system_config}")
            # Implementation would depend on config file format
        else:
            self.logger.debug("No configuration file found, using defaults")

    def run(self) -> None:
        """Main function to run the script"""
        # Parse command line arguments
        self.parse_arguments()
        
        # Check for required dependencies
        self.check_dependencies()
        
        # Load configuration if available
        self.load_config()
        
        # Detect and select controller
        self.logger.info("Detecting available controllers...")
        self.controller = self.detect_controllers()
        self.logger.info(f"Selected controller: {self.controller}")
        
        # Get disk information based on the selected controller
        self.logger.info(f"Collecting disk information from {self.controller}...")
        if self.controller == "storcli":
            self.disks_table_json = self.get_storcli_disks()
        elif self.controller == "sas2ircu":
            self.disks_table_json = self.get_sas2ircu_disks()
        elif self.controller == "sas3ircu":
            # For now, use the same function as sas2ircu (modify as needed)
            self.disks_table_json = self.get_sas2ircu_disks()
        else:
            self.logger.error(f"Unknown controller: {self.controller}")
            sys.exit(1)
        
        # Get lsblk information
        self.logger.info("Getting system block device information...")
        self.lsblk_json = self.get_lsblk_disks()
        
        # Combine disk information
        self.logger.info("Matching controller devices with system devices...")
        self.combined_disk = self.combine_disk_info(self.disks_table_json, self.lsblk_json)
        
        # Map disk locations
        self.logger.info("Mapping physical locations...")
        self.combined_disk_complete = self.map_disk_locations(self.combined_disk, self.controller)
        
        # Display the results
        if self.json_output:
            # Output as JSON
            result = []
            for disk in self.combined_disk_complete:
                if len(disk) >= 14:
                    result.append({
                        "device": disk[0],
                        "name": disk[1],
                        "slot": disk[2],
                        "controller": disk[3],
                        "enclosure": disk[4],
                        "drive": disk[5],
                        "serial": disk[6],
                        "model": disk[7],
                        "manufacturer": disk[8],
                        "wwn": disk[9],
                        "enclosure_name": disk[10],
                        "physical_slot": disk[11],
                        "logical_disk": disk[12],
                        "location": disk[13]
                    })
            print(json.dumps(result, indent=2))
        else:
            # Display as formatted table
            # Create column headers
            headers = ["Device", "Name", "Slot", "Ctrl", "Enc", "Drive", "Serial", 
                      "Model", "Manufacturer", "WWN", "Enc Name", "PhySlot", "LogDisk", "Location"]
            
            # Calculate column widths
            widths = [len(h) for h in headers]
            for disk in self.combined_disk_complete:
                for i, val in enumerate(disk):
                    if i < len(widths):
                        widths[i] = max(widths[i], len(str(val)))
            
            # Print header
            header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers) if i < len(widths))
            print(header_line)
            print("-" * len(header_line))
            
            # Print data
            for disk in self.combined_disk_complete:
                line = "  ".join(str(val).ljust(widths[i]) for i, val in enumerate(disk) if i < len(widths))
                print(line)
        
        # Display ZFS pool information if requested
        if self.show_zpool:
            self.logger.info("Displaying ZFS pool information...")
            self.display_zpool_info(self.combined_disk_complete)


if __name__ == "__main__":
    try:
        finder = StorageTopology()
        finder.run()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if logging.getLogger("serial-finder").level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1) 