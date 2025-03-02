#!/usr/bin/env python3
"""
Storage Topology - Identifies physical disk locations by matching controller information with system devices

This script helps identify physical disk locations by correlating storage controller information
with system block devices. It supports storcli, sas2ircu, and sas3ircu controllers.

Key Features:
- Detects available storage controllers automatically
- Matches physical disk locations with system devices
- Supports JSON output for programmatic use
- Integrates with ZFS pools
- Handles multipath devices
- Customizable through configuration files
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import yaml
from typing import Dict, List, Optional, Any, Tuple, Set, Union


class StorageTopology:
    """Main class for the Storage Topology tool
    
    This class provides functionality to identify and map physical disk locations
    by correlating storage controller information with system block devices.
    
    The tool supports multiple storage controllers:
    - LSI MegaRAID controllers via storcli
    - LSI SAS controllers via sas2ircu (SAS2 controllers)
    - LSI SAS controllers via sas3ircu (SAS3 controllers)
    
    Key features:
    - Automatic detection of available storage controllers
    - Matching of physical disk locations with system block devices
    - Support for multipath devices
    - Integration with ZFS pools to show physical locations of pool devices
    - Customizable configuration for enclosure naming and slot mapping
    - JSON output option for integration with other tools
    
    The workflow involves:
    1. Detecting and selecting a controller
    2. Gathering disk information from the controller
    3. Getting system block device information
    4. Combining and matching the information
    5. Applying custom mappings and configuration
    6. Displaying the results in a user-friendly format
    
    Attributes:
        json_output (bool): Flag for JSON output format
        show_zpool (bool): Flag to show ZFS pool information
        verbose (bool): Flag for verbose logging
        quiet (bool): Flag to suppress INFO messages
        controller (str): Detected controller type (storcli, sas2ircu, sas3ircu)
        disks_table_json (List[Dict]): Disk information from controller
        lsblk_json (Dict): System block device information
        combined_disk (List[List]): Combined disk information
        combined_disk_complete (List[List]): Complete disk information with locations
        enclosure_offsets (Dict): Custom enclosure configuration
        custom_mappings (Dict): Custom disk mappings
        logger (Logger): Application logger
    """

    def __init__(self):
        """Initialize the StorageTopology instance with default values"""
        self.json_output = False
        self.show_zpool = False
        self.verbose = False
        self.quiet = False
        self.controller = ""
        self.disks_table_json = {}
        self.lsblk_json = {}
        self.combined_disk = []
        self.combined_disk_complete = []
        self.enclosure_offsets = {}
        self.custom_mappings = {}
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Set up the logger for the application
        
        Returns:
            Logger: Configured logger instance
        """
        logger = logging.getLogger("serial-finder")
        logger.setLevel(logging.INFO)
        
        # Create console handler with standard output format
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Create formatter with consistent message format
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
        """Check if a command exists in the system PATH
        
        Args:
            cmd (str): Command to check
            
        Returns:
            bool: True if command exists, False otherwise
        """
        return shutil.which(cmd) is not None

    def check_controller_found(self, controller: str) -> bool:
        """Check if a controller is found and accessible
        
        Args:
            controller (str): Controller type to check (storcli, sas2ircu, sas3ircu)
            
        Returns:
            bool: True if controller is found and accessible, False otherwise
        """
        try:
            if controller == "storcli":
                # Check controller count using storcli
                # Use binary mode and handle decoding separately with error handling
                output_bytes = subprocess.check_output(["storcli", "show", "ctrlcount"])
                
                # Try to decode with error handling
                try:
                    output = output_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    # If UTF-8 decoding fails, try with 'latin-1' which can handle any byte value
                    self.logger.debug("UTF-8 decoding failed for controller check, falling back to latin-1")
                    output = output_bytes.decode('latin-1')
                
                controller_count_match = re.search(r"Controller Count = (\d+)", output)
                if controller_count_match and int(controller_count_match.group(1)) > 0:
                    return True
            elif controller in ["sas2ircu", "sas3ircu"]:
                # Check controller availability using LIST command
                subprocess.check_output([controller, "LIST"], stderr=subprocess.STDOUT, universal_newlines=True)
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
        
        try:
            # Run storcli command to get all disk information in JSON format
            # Use binary mode and handle decoding separately with error handling
            storcli_output_bytes = subprocess.check_output(["storcli", "/call", "show", "all", "J"])
            
            # Try to decode with error handling
            try:
                storcli_output = storcli_output_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # If UTF-8 decoding fails, try with 'latin-1' which can handle any byte value
                self.logger.debug("UTF-8 decoding failed, falling back to latin-1")
                storcli_output = storcli_output_bytes.decode('latin-1')
            
            storcli_json = json.loads(storcli_output)
            
            self.logger.debug(f"Got storcli output, controllers: {len(storcli_json.get('Controllers', []))}")
            
            disks_list = []
            
            # Process each controller
            for controller_idx, controller in enumerate(storcli_json.get("Controllers", [])):
                # Extract response data from the controller information
                response_data = controller.get("Response Data", {})
                
                self.logger.debug(f"Controller {controller_idx} response data keys: {list(response_data.keys())}")
                
                # Get the physical device information section
                physical_devices = response_data.get("Physical Device Information", {})
                
                if physical_devices:
                    self.logger.debug(f"Physical Device Information keys: {list(physical_devices.keys())}")
                    
                    # Find all drive keys (keys that start with "Drive /c" and don't contain "Detailed Information")
                    drive_keys = [k for k in physical_devices.keys() 
                                 if k.startswith("Drive /c") and "Detailed Information" not in k]
                    
                    self.logger.debug(f"Found drive keys: {drive_keys}")
                    
                    for drive_key in drive_keys:
                        # Extract controller number from the drive key (e.g., "/c0" -> "0")
                        controller_match = re.search(r"/c(\d+)", drive_key)
                        controller_num = controller_match.group(1) if controller_match else ""
                        
                        # Also extract enclosure and slot numbers
                        enclosure_slot_match = re.search(r"/e(\d+)/s(\d+)", drive_key)
                        if enclosure_slot_match:
                            enclosure = enclosure_slot_match.group(1)
                            slot = enclosure_slot_match.group(2)
                        else:
                            # Fallback to using the EID:Slt field
                            try:
                                drive_info = physical_devices[drive_key][0]
                                enclosure_slot = drive_info.get("EID:Slt", "")
                                enclosure, slot = enclosure_slot.split(":") if ":" in enclosure_slot else ("", "")
                            except (IndexError, KeyError):
                                self.logger.debug(f"Could not extract EID:Slt for drive {drive_key}")
                                enclosure = ""
                                slot = ""
                        
                        # Get basic drive info from the drive key entry
                        try:
                            basic_drive_info = physical_devices[drive_key][0]
                            model = basic_drive_info.get("Model", "")
                        except (IndexError, KeyError):
                            self.logger.debug(f"Could not extract basic info for drive {drive_key}")
                            model = ""
                        
                        # Get detailed drive info from the corresponding detailed information section
                        detailed_key = f"{drive_key} - Detailed Information"
                        detailed_info = physical_devices.get(detailed_key, {})
                        
                        # Initialize variables to store disk details
                        serial = ""
                        manufacturer = ""
                        wwn = ""
                        
                        # The detailed info is structured with nested sections
                        # Look for the "Device attributes" section which contains the serial, manufacturer, and WWN
                        device_attributes_key = f"{drive_key} Device attributes"
                        if device_attributes_key in detailed_info:
                            device_attributes = detailed_info[device_attributes_key]
                            serial = device_attributes.get("SN", "")
                            manufacturer = device_attributes.get("Manufacturer Id", "")
                            wwn = device_attributes.get("WWN", "")
                            # If model wasn't found in basic info, try to get it from detailed info
                            if not model:
                                model = device_attributes.get("Model Number", "")
                        
                        self.logger.debug(f"Drive {drive_key} details - SN: {serial}, Model: {model}, WWN: {wwn}")
                        
                        # Only add disks with a serial number to filter out non-disk devices
                        if serial:
                            disk_entry = {
                                "name": drive_key,                   # Full drive path 
                                "slot": f"{enclosure}:{slot}",       # Combined enclosure:slot format
                                "controller": controller_num,        # Controller number
                                "enclosure": enclosure,              # Enclosure ID
                                "drive": slot,                       # Slot number
                                "sn": serial,                        # Serial number
                                "model": model,                      # Model number
                                "manufacturer": manufacturer,        # Manufacturer
                                "wwn": wwn                           # World Wide Name
                            }
                            disks_list.append(disk_entry)
                            self.logger.debug(f"Found storcli disk: {disk_entry}")
            
            self.logger.debug(f"Total storcli disks found: {len(disks_list)}")
            return disks_list
        except Exception as e:
            self.logger.error(f"Error getting storcli disk information: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return []

    def get_sas2ircu_disks(self) -> List[Dict[str, Any]]:
        """Get disk information using sas2ircu"""
        self.logger.info("Getting sas2ircu disk information")
        disks_list = []
        
        try:
            # Get controller IDs
            list_output = subprocess.check_output(["sas2ircu", "list"], universal_newlines=True)
            controller_ids = []
            
            # Updated regex pattern to match controller IDs in the table format
            for line in list_output.splitlines():
                # Look for lines that start with a number followed by spaces and then text
                # This matches the format of the controller ID line in the output
                if re.match(r'^\s*\d+\s+\S', line):
                    # Extract just the number at the beginning
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
        """Get disk information from lsblk
        
        This method runs the lsblk command to retrieve detailed information about block devices
        in the system. It outputs the data in JSON format for easy parsing.
        
        Returns:
            Dict[str, Any]: A dictionary containing information about all block devices
        
        Raises:
            subprocess.SubprocessError: If the lsblk command fails
            json.JSONDecodeError: If the JSON output from lsblk cannot be parsed
        """
        self.logger.info("Getting system block device information")
        
        try:
            # Run lsblk command with JSON output
            # -p: show full device path
            # -d: don't show dependent devices (partitions)
            # -o: specify output columns
            # -J: output in JSON format
            lsblk_output = subprocess.check_output(
                ["lsblk", "-p", "-d", "-o", "NAME,WWN,VENDOR,MODEL,REV,SERIAL,SIZE,PTUUID,HCTL,TRAN,TYPE", "-J"],
                universal_newlines=True
            )
            
            # Parse JSON output
            try:
                lsblk_data = json.loads(lsblk_output)
                self.logger.debug(f"Found {len(lsblk_data.get('blockdevices', []))} block devices")
                return lsblk_data
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse lsblk JSON output: {e}")
                self.logger.debug(f"Raw lsblk output: {lsblk_output}")
                # Return empty dict structure to prevent errors downstream
                return {"blockdevices": []}
                
        except subprocess.SubprocessError as e:
            self.logger.error(f"Failed to execute lsblk command: {e}")
            if self.verbose:
                self.logger.debug(f"Command failed: lsblk -p -d -o NAME,WWN,VENDOR,MODEL,REV,SERIAL,SIZE,PTUUID,HCTL,TRAN,TYPE -J")
            # Return empty dict structure to prevent errors downstream
            return {"blockdevices": []}

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
                    disk_wwn = str(disk.get("wwn", ""))
                    disk_wwn_lower = disk_wwn.lower()
                    disk_serial = str(disk.get("sn", ""))
                    
                    # Normalize WWNs by removing any "0x" prefix and ensuring consistent case
                    my_wwn_norm = my_wwn.replace("0x", "").lower()
                    disk_wwn_norm = disk_wwn_lower.replace("0x", "").lower()
                    
                    # Debug logging for WWN matching
                    self.logger.debug(f"Comparing WWNs - System: '{my_wwn_norm}' vs Controller: '{disk_wwn_norm}'")
                    self.logger.debug(f"Comparing Serials - System: '{serial}' vs Controller: '{disk_serial}'")
                    
                    # Try to match by either WWN or serial number
                    # For WWN, both exact match and off-by-one match (storcli can report one digit differently)
                    if (disk_wwn_norm and (disk_wwn_norm == my_wwn_norm or 
                                          (len(disk_wwn_norm) == len(my_wwn_norm) and 
                                           sum(a != b for a, b in zip(disk_wwn_norm, my_wwn_norm)) <= 1))) \
                       or (disk_serial and disk_serial == serial):
                        self.logger.debug(f"Match found! WWN: {disk_wwn_norm} or Serial: {disk_serial}")
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
            # Use binary mode and handle decoding separately with error handling
            enclosure_info_bytes = subprocess.check_output(
                ["storcli", "/call/eall", "show", "all", "J"]
            )
            
            # Try to decode with error handling
            try:
                enclosure_info_output = enclosure_info_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # If UTF-8 decoding fails, try with 'latin-1' which can handle any byte value
                self.logger.debug("UTF-8 decoding failed for enclosure info, falling back to latin-1")
                enclosure_info_output = enclosure_info_bytes.decode('latin-1')
                
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
            self.logger.debug(f"Running {controller} list command")
            list_output = subprocess.check_output([controller, "list"], universal_newlines=True)
            self.logger.debug(f"List output: {list_output}")
            controller_ids = []
            
            # Updated regex pattern to match controller IDs in the table format
            for line in list_output.splitlines():
                # Look for lines that start with a number followed by spaces and then text
                # This matches the format of the controller ID line in the output
                if re.match(r'^\s*\d+\s+\S', line):
                    # Extract just the number at the beginning
                    controller_id = line.strip().split()[0]
                    controller_ids.append(controller_id)
            
            self.logger.debug(f"Found controller IDs: {controller_ids}")
            
            # Build a list of controllers and enclosures
            for ctrl_id in controller_ids:
                self.logger.debug(f"Running {controller} {ctrl_id} display command")
                display_output = subprocess.check_output(
                    [controller, ctrl_id, "display"],
                    universal_newlines=True
                )
                
                # Extract enclosure information
                encl_info = ""
                capture = False
                self.logger.debug(f"Searching for 'Enclosure information' section")
                for line in display_output.splitlines():
                    if "Enclosure information" in line:
                        self.logger.debug(f"Found 'Enclosure information' section")
                        capture = True
                        continue
                    if capture:
                        if re.match(r'^-+$', line):
                            if encl_info:  # We've reached the end of the enclosure section
                                self.logger.debug(f"End of enclosure section reached")
                                break
                            continue
                        encl_info += line + "\n"
                
                self.logger.debug(f"Extracted enclosure info: {encl_info}")
                
                # Process enclosure information
                encl_number = ""
                logical_id = ""
                num_slots = ""
                start_slot = ""
                
                for line in encl_info.splitlines():
                    self.logger.debug(f"Processing line: {line}")
                    if "Enclosure#" in line:
                        encl_number = line.split(':')[1].strip()
                        self.logger.debug(f"Found Enclosure#: {encl_number}")
                    elif "Logical ID" in line:
                        # Get everything after the first colon to preserve the full logical ID
                        logical_id = line.split(':', 1)[1].strip()
                        self.logger.debug(f"Found Logical ID: {logical_id}")
                    elif "Numslots" in line:
                        num_slots = line.split(':')[1].strip()
                        self.logger.debug(f"Found Numslots: {num_slots}")
                    elif "StartSlot" in line:
                        start_slot = line.split(':')[1].strip()
                        self.logger.debug(f"Found StartSlot: {start_slot}")
                        
                        # Determine enclosure type based on number of slots
                        encl_type = "Unknown"
                        if num_slots and num_slots.isdigit():
                            slots = int(num_slots)
                            if slots > 20:
                                encl_type = "JBOD"
                            elif slots <= 8:
                                encl_type = "Internal"
                        
                        self.logger.debug(f"Adding enclosure to map: controller={ctrl_id}, enclosure={encl_number}, type={encl_type}")
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
        
        self.logger.debug(f"Final enclosure map: {enclosure_map}")
        return enclosure_map

    def _get_enclosure_config(self, logical_id: str, enclosure: str, product_id: str = None) -> Dict[str, Any]:
        """Get the enclosure configuration from the loaded configuration
        
        This helper method looks up the configuration for an enclosure by either
        its logical ID, enclosure ID, or product ID.
        
        Args:
            logical_id (str): The logical ID of the enclosure
            enclosure (str): The enclosure ID
            product_id (str): The product ID of the enclosure
            
        Returns:
            Dict[str, Any]: The configuration entry for the enclosure, or None if not found
        """
        # First try to find configuration by product ID (for storcli)
        if product_id and product_id in self.enclosure_offsets:
            config_entry = self.enclosure_offsets[product_id]
            self.logger.debug(f"Found config for product ID {product_id}: {config_entry}")
            return config_entry
        # Then try by logical ID
        elif logical_id and logical_id in self.enclosure_offsets:
            config_entry = self.enclosure_offsets[logical_id]
            self.logger.debug(f"Found config for logical ID {logical_id}: {config_entry}")
            return config_entry
        # Finally try by enclosure ID
        elif enclosure and enclosure in self.enclosure_offsets:
            config_entry = self.enclosure_offsets[enclosure]
            self.logger.debug(f"Found config for enclosure ID {enclosure}: {config_entry}")
            return config_entry
        
        # No configuration found
        return None

    def _calculate_disk_position(self, drive_num: int, hw_start_slot: int, 
                                config_entry: Dict[str, Any]) -> Tuple[int, int]:
        """Calculate the physical and logical position of a disk
        
        Args:
            drive_num (int): The raw drive number from controller
            hw_start_slot (int): The hardware start slot number
            config_entry (Dict[str, Any]): The enclosure configuration entry
            
        Returns:
            Tuple[int, int]: The physical slot number and logical disk number
        """
        # Get configuration values
        offset = config_entry.get("offset", 0)
        start_slot = config_entry.get("start_slot", hw_start_slot)
        
        # Calculate the real drive number by subtracting the hardware start slot
        real_drive_num = drive_num - hw_start_slot
        if real_drive_num < 0:
            real_drive_num = drive_num  # Fallback if start_slot is incorrect
        
        # Calculate physical slot and logical disk numbers
        physical_slot = real_drive_num + offset + start_slot
        logical_disk = real_drive_num + start_slot
        
        return physical_slot, logical_disk

    def map_disk_locations(self, combined_disk: List[List[str]], controller: str) -> List[List[str]]:
        """Map enclosure and disk locations
        
        This method maps physical locations for each disk by combining controller 
        information with configuration settings. It handles custom mappings and 
        calculates the proper slot numbers.
        
        Args:
            combined_disk (List[List[str]]): The combined disk information
            controller (str): The controller type
            
        Returns:
            List[List[str]]: The disk information with mapped locations
        """
        self.logger.info("Mapping physical locations")
        
        # Get enclosure type mapping by detecting the enclosure types based on controller
        enclosure_map = self.detect_enclosure_types(self.disks_table_json, controller)
        
        # Create lookup dictionaries for enclosure information
        enclosure_info = {}
        
        # Process enclosure map to create a lookup dictionary keyed by "controller_id_enclosure_id"
        for encl in enclosure_map.get("Controllers", []):
            controller_id = encl.get("controller", "")
            enclosure_id = encl.get("enclosure", "")
            logical_id = encl.get("logicalid", "")
            encl_type = encl.get("type", "Unknown")
            slots = encl.get("slots", "0")
            start_slot = encl.get("start_slot", "0")
            
            # Create a key for the enclosure using controller_id and enclosure_id
            key = f"{controller_id}_{enclosure_id}"
            
            # Store all enclosure information in a dictionary for easy lookup
            enclosure_info[key] = {
                "controller_id": controller_id,
                "enclosure_id": enclosure_id,
                "logical_id": logical_id,
                "type": encl_type,
                "slots": int(slots) if isinstance(slots, str) and slots.isdigit() else (slots if isinstance(slots, int) else 0),
                "start_slot": int(start_slot) if isinstance(start_slot, str) and start_slot.isdigit() else (start_slot if isinstance(start_slot, int) else 0)
            }
            
            self.logger.debug(f"Enclosure info: {key} -> {enclosure_info[key]}")
        
        # Find all unique enclosures in the disk data to help with naming and organization
        unique_enclosures = set()
        for disk in combined_disk:
            enclosure = disk[4]  # Enclosure is at index 4
            # Make sure enclosure is a string before calling isdigit()
            if enclosure and enclosure != "null" and enclosure != "N/A" and str(enclosure).isdigit():
                unique_enclosures.add(enclosure)
        
        # Convert to sorted list for ordered access
        enclosures = sorted(list(unique_enclosures))
        self.logger.debug(f"Unique enclosures: {enclosures}")
        
        combined_disk_complete = []
        
        # Process all disks to map their physical locations
        for disk in combined_disk:
            # Extract disk information from the combined_disk list
            dev_name = disk[0]      # Device name (e.g., /dev/sda)
            name = disk[1]          # Name from controller
            slot = disk[2]          # Slot information
            controller_id = disk[3] # Controller ID
            enclosure = disk[4]     # Enclosure ID
            drive = disk[5]         # Drive/slot number
            serial = disk[6]        # Serial number
            model = disk[7]         # Model
            manufacturer = disk[8]  # Manufacturer
            wwn = disk[9]           # World Wide Name
            vendor = disk[10]       # Vendor
            
            # Initialize location variables
            enclosure_name = ""     # Human-readable enclosure name
            encslot = 0             # Physical slot number
            encdisk = 0             # Logical disk number
            
            # Skip if drive is not a valid slot number
            try:
                # Convert drive to integer if possible, otherwise set to 0
                drive_num = int(drive) if drive and drive not in ["null", "None", "N/A", "xxx"] else 0
            except (ValueError, TypeError):
                drive_num = 0
            
            # Check if we have a custom mapping for this drive by serial number
            # Custom mappings allow overriding the default location mapping
            if serial and serial in self.custom_mappings:
                # Use the custom mapping information
                custom_map = self.custom_mappings.get(serial, {})
                enclosure_name = custom_map.get("enclosure", "Custom")
                encslot = custom_map.get("slot", 0)
                encdisk = custom_map.get("disk", drive_num)
                
                self.logger.debug(f"Using custom mapping for drive with serial {serial}: {custom_map}")
            else:
                # Get enclosure information from our lookup dictionary
                enclosure_key = f"{controller_id}_{enclosure}"
                encl_info = enclosure_info.get(enclosure_key, {})
                
                # Get enclosure type and logical ID
                encl_type = encl_info.get("type", "Unknown")
                logical_id = encl_info.get("logical_id", "")
                hw_start_slot = encl_info.get("start_slot", 0)
                
                # Get configuration entry for this enclosure
                config_entry = self._get_enclosure_config(logical_id, enclosure, encl_type)
                
                # If we have a configuration entry, use it to map the disk location
                if config_entry:
                    # Use configured enclosure name or fallback to enclosure type
                    enclosure_name = config_entry.get("name", encl_type)
                    
                    # Calculate physical slot and logical disk numbers
                    encslot, encdisk = self._calculate_disk_position(
                        drive_num, hw_start_slot, config_entry
                    )
                    
                    self.logger.debug(f"Calculated position for {dev_name}: drive={drive_num}, "
                                     f"hw_start={hw_start_slot}, "
                                     f"encslot={encslot}, encdisk={encdisk}")
                else:
                    # No configuration found, use default naming and positioning
                    # Determine enclosure name based on type or position
                    if encl_type != "Unknown":
                        # Use the detected enclosure type (e.g., JBOD, Internal)
                        enclosure_name = encl_type
                    elif enclosure in enclosures:
                        # Name based on position in the list of enclosures
                        encl_idx = enclosures.index(enclosure)
                        if encl_idx == 0:
                            enclosure_name = "Local"  # First enclosure is typically local
                        else:
                            enclosure_name = f"Enclosure-{enclosure}"  # Others numbered by ID
                    else:
                        # Fallback for unknown enclosures
                        enclosure_name = f"Unknown-{enclosure}"
                    
                    # Default slot calculation (simple 1-based index)
                    encslot = drive_num + 1
                    encdisk = drive_num
            
            # Create the location string in a standardized format for output
            location = f"{enclosure_name};SLOT:{encslot};DISK:{encdisk}"
            
            # Create the complete entry with all information including the mapped location
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
        """Load configuration file
        
        This method loads the configuration file from ./storage_topology.conf (YAML format).
        The configuration file can contain:
        - Enclosure definitions with names, offsets, and slot mappings
        - Custom disk mappings by serial number
        
        Example config:
        ```yaml
        enclosures:
          - id: "SAS3x48Front"    # Enclosure ID, logical_id, or product ID for identification
            name: "Front JBOD"    # Human-readable name
            offset: 0             # Offset for physical slot numbering
            start_slot: 0         # Starting slot number for logical numbering
            max_slots: 48         # Maximum number of slots in this enclosure
          
        disks:
          - serial: "ABC123"      # Disk serial number
            enclosure: "Top"      # Custom enclosure name
            slot: 5               # Physical slot number
            disk: 1               # Logical disk number
        ```
        """
        config_file = os.path.expanduser("./storage_topology.conf")
        
        if os.path.exists(config_file):
            try:
                self.logger.info(f"Loading user configuration from {config_file}")
                with open(config_file, 'r') as f:
                    config = yaml.safe_load(f)
                
                if config:
                    # Load enclosure configuration
                    if 'enclosures' in config:
                        self.logger.info(f"Found {len(config['enclosures'])} enclosure configurations")
                        for encl_config in config['enclosures']:
                            # Validate that we have an ID
                            encl_id = encl_config.get('id')
                            if not encl_id:
                                self.logger.warning("Skipping enclosure config without ID")
                                continue
                                
                            # Store the enclosure configuration
                            self.enclosure_offsets[encl_id] = {
                                'name': encl_config.get('name', f"Enclosure-{encl_id}"),
                                'offset': int(encl_config.get('offset', 0)),
                                'start_slot': int(encl_config.get('start_slot', 0)),
                                'max_slots': int(encl_config.get('max_slots', 0))
                            }
                            self.logger.debug(f"Loaded enclosure config for {encl_id}: {self.enclosure_offsets[encl_id]}")
                    
                    # Load custom disk mappings by serial number
                    if 'disks' in config:
                        self.logger.info(f"Found {len(config['disks'])} custom disk mappings")
                        for disk_config in config['disks']:
                            # Validate that we have a serial number
                            serial = disk_config.get('serial')
                            if not serial:
                                self.logger.warning("Skipping disk mapping without serial number")
                                continue
                                
                            # Store the custom mapping
                            self.custom_mappings[serial] = {
                                'enclosure': disk_config.get('enclosure', 'Custom'),
                                'slot': int(disk_config.get('slot', 0)),
                                'disk': int(disk_config.get('disk', 0))
                            }
                            self.logger.debug(f"Loaded custom mapping for disk {serial}: {self.custom_mappings[serial]}")
                else:
                    self.logger.warning(f"Configuration file {config_file} is empty or invalid")
            
            except yaml.YAMLError as e:
                self.logger.error(f"Error parsing YAML in configuration file: {e}")
            except IOError as e:
                self.logger.error(f"Error reading configuration file: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error loading configuration: {e}")
                if self.verbose:
                    import traceback
                    traceback.print_exc()
        else:
            self.logger.warning(f"Configuration file {config_file} not found. Using default settings.")

    def run(self) -> None:
        """Main function to run the script
        
        This method orchestrates the entire workflow of the script:
        
        1. Parse command line arguments
        2. Check for required dependencies
        3. Load configuration file (if available)
        4. Detect and select a storage controller
        5. Collect disk information from the controller
        6. Get system block device information via lsblk
        7. Match controller devices with system devices
        8. Map physical locations for each disk
        9. Display results in the requested format
        10. Optionally show ZFS pool information
        
        The process handles various controller types (storcli, sas2ircu, sas3ircu)
        and works with different disk and enclosure configurations.
        """
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