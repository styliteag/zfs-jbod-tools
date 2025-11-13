"""
Storage Controller abstraction for the Storage Topology Tool

This module provides abstract and concrete controller implementations
for different storage controller types (storcli, sas2ircu, sas3ircu).
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
import subprocess
import re
import json
import logging
from storage_models import DiskInfo, EnclosureInfo


class StorageController(ABC):
    """Abstract base class for storage controllers"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    @abstractmethod
    def get_command_name(self) -> str:
        """Get the command name for this controller"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this controller is available and has devices"""
        pass
    
    @abstractmethod
    def get_disks(self) -> List[DiskInfo]:
        """Get list of disks from this controller"""
        pass
    
    @abstractmethod
    def get_enclosures(self) -> List[EnclosureInfo]:
        """Get list of enclosures from this controller"""
        pass
    
    @abstractmethod
    def locate_disk(self, disk_info: DiskInfo, turn_off: bool, wait_seconds: Optional[int]) -> None:
        """Turn on/off the identify LED for a disk"""
        pass
    
    @abstractmethod
    def locate_all_disks(self, turn_off: bool, wait_seconds: Optional[int]) -> Tuple[int, int]:
        """Turn on/off LEDs for all disks. Returns (success_count, failed_count)"""
        pass
    
    def _execute_command(self, cmd: List[str], handle_errors: bool = True) -> str:
        """Execute a command and return its output"""
        self.logger.debug(f"Executing command: {' '.join(cmd)}")
        
        try:
            output_bytes = subprocess.check_output(cmd, stderr=subprocess.PIPE)
            
            try:
                output = output_bytes.decode('utf-8')
            except UnicodeDecodeError:
                self.logger.debug("UTF-8 decoding failed, falling back to latin-1")
                output = output_bytes.decode('latin-1')
                
            return output
            
        except subprocess.CalledProcessError as e:
            if handle_errors:
                self.logger.error(f"Error executing command {' '.join(cmd)}: {e}")
                return ""
            else:
                raise
    
    def _parse_json(self, output: str) -> Optional[Dict[str, Any]]:
        """Parse JSON output with error handling"""
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing JSON: {e}")
            return None


class StorcliController(StorageController):
    """Controller implementation for storcli/storcli2"""
    
    def __init__(self, logger: logging.Logger, prefer_storcli2: bool = True):
        super().__init__(logger)
        self.cmd_name = self._detect_command(prefer_storcli2)
    
    def _detect_command(self, prefer_storcli2: bool) -> str:
        """Detect whether to use storcli or storcli2"""
        import shutil
        
        if prefer_storcli2 and shutil.which("storcli2"):
            if self._check_has_controllers("storcli2"):
                return "storcli2"
        
        if shutil.which("storcli"):
            if self._check_has_controllers("storcli"):
                return "storcli"
        
        if not prefer_storcli2 and shutil.which("storcli2"):
            if self._check_has_controllers("storcli2"):
                return "storcli2"
        
        return ""
    
    def _check_has_controllers(self, cmd: str) -> bool:
        """Check if command can find controllers"""
        try:
            output = self._execute_command([cmd, "show", "ctrlcount"], handle_errors=False)
            match = re.search(r"Controller Count = (\d+)", output)
            return match and int(match.group(1)) > 0
        except:
            return False
    
    def get_command_name(self) -> str:
        return self.cmd_name
    
    def is_available(self) -> bool:
        return bool(self.cmd_name)
    
    def get_disks(self) -> List[DiskInfo]:
        """Get disk information using storcli/storcli2"""
        if not self.cmd_name:
            return []
        
        self.logger.info(f"Getting {self.cmd_name} disk information")
        
        try:
            output = self._execute_command([self.cmd_name, "/call", "show", "all", "J"])
            data = self._parse_json(output)
            if not data:
                return []
            
            return self._parse_storcli_disks(data)
        except Exception as e:
            self.logger.error(f"Error getting {self.cmd_name} disk information: {e}")
            return []
    
    def _parse_storcli_disks(self, json_data: Dict[str, Any]) -> List[DiskInfo]:
        """Parse disk information from storcli JSON"""
        disks = []
        
        for controller_idx, controller in enumerate(json_data.get("Controllers", [])):
            response_data = controller.get("Response Data", {})
            
            # Check format: storcli2 (PD LIST) or storcli (Physical Device Information)
            pd_list = response_data.get("PD LIST", [])
            
            if pd_list:
                disks.extend(self._parse_storcli2_format(controller, pd_list))
            else:
                disks.extend(self._parse_storcli_format(controller, response_data))
        
        return disks
    
    def _parse_storcli2_format(self, controller: Dict, pd_list: List[Dict]) -> List[DiskInfo]:
        """Parse storcli2 PD LIST format"""
        disks = []
        
        # Get controller number
        command_status = controller.get("Command Status", {})
        controller_num = str(command_status.get("Controller", ""))
        
        # Get detailed info for all drives
        pd_details_map = self._get_pd_details_map(controller_num)
        
        for pd_entry in pd_list:
            eid_slt = pd_entry.get("EID:Slt", "")
            if not eid_slt or ":" not in eid_slt:
                continue
            
            enclosure, slot = eid_slt.split(":", 1)
            model = pd_entry.get("Model", "").strip()
            
            # Get detailed information
            pd_detail = pd_details_map.get(eid_slt, {})
            serial = pd_detail.get("SN", "").strip()
            manufacturer = pd_detail.get("Manufacturer Id", "").strip()
            wwn = pd_detail.get("WWN", "").strip()
            
            if not model and pd_detail.get("Model Number"):
                model = pd_detail.get("Model Number", "").strip()
            
            drive_key = f"/c{controller_num}/e{enclosure}/s{slot}"
            
            if enclosure and slot:
                disk = DiskInfo(
                    name=drive_key,
                    slot=f"{enclosure}:{slot}",
                    controller=controller_num,
                    enclosure=enclosure,
                    drive=slot,
                    serial=serial,
                    model=model,
                    manufacturer=manufacturer,
                    wwn=wwn
                )
                disks.append(disk)
        
        return disks
    
    def _parse_storcli_format(self, controller: Dict, response_data: Dict) -> List[DiskInfo]:
        """Parse storcli Physical Device Information format"""
        disks = []
        physical_devices = response_data.get("Physical Device Information", {})
        
        drive_keys = [k for k in physical_devices.keys() 
                     if k.startswith("Drive /c") and "Detailed Information" not in k]
        
        for drive_key in drive_keys:
            controller_match = re.search(r"/c(\d+)", drive_key)
            controller_num = controller_match.group(1) if controller_match else ""
            
            enclosure_slot_match = re.search(r"/e(\d+)/s(\d+)", drive_key)
            if enclosure_slot_match:
                enclosure = enclosure_slot_match.group(1)
                slot = enclosure_slot_match.group(2)
            else:
                continue
            
            # Get basic info
            try:
                basic_info = physical_devices[drive_key][0]
                model = basic_info.get("Model", "").strip()
            except (IndexError, KeyError):
                model = ""
            
            # Get detailed info
            detailed_key = f"{drive_key} - Detailed Information"
            detailed_info = physical_devices.get(detailed_key, {})
            device_attrs_key = f"{drive_key} Device attributes"
            
            serial = ""
            manufacturer = ""
            wwn = ""
            
            if device_attrs_key in detailed_info:
                attrs = detailed_info[device_attrs_key]
                serial = attrs.get("SN", "").strip()
                manufacturer = attrs.get("Manufacturer Id", "").strip()
                wwn = attrs.get("WWN", "").strip()
                if not model:
                    model = attrs.get("Model Number", "").strip()
            
            if serial:
                disk = DiskInfo(
                    name=drive_key,
                    slot=f"{enclosure}:{slot}",
                    controller=controller_num,
                    enclosure=enclosure,
                    drive=slot,
                    serial=serial,
                    model=model,
                    manufacturer=manufacturer,
                    wwn=wwn
                )
                disks.append(disk)
        
        return disks
    
    def _get_pd_details_map(self, controller_num: str) -> Dict[str, Dict]:
        """Get detailed PD information for all drives"""
        pd_details_map = {}
        
        # Try /call/eall/sall first
        try:
            output = self._execute_command(
                [self.cmd_name, "/call/eall/sall", "show", "all", "J"],
                handle_errors=False
            )
            data = self._parse_json(output)
            if data:
                self._extract_pd_details(data, pd_details_map)
        except:
            pass
        
        # If that didn't work, try /c{controller}/eall/sall
        if not pd_details_map and controller_num:
            try:
                output = self._execute_command(
                    [self.cmd_name, f"/c{controller_num}/eall/sall", "show", "all", "J"],
                    handle_errors=False
                )
                data = self._parse_json(output)
                if data:
                    self._extract_pd_details(data, pd_details_map)
            except:
                pass
        
        return pd_details_map
    
    def _extract_pd_details(self, json_data: Dict, pd_details_map: Dict) -> None:
        """Extract PD details from JSON response"""
        for controller in json_data.get("Controllers", []):
            response = controller.get("Response Data", {})
            
            # Check for storcli2 "Drives List" format
            drives_list = response.get("Drives List", [])
            if drives_list:
                for drive_entry in drives_list:
                    drive_info = drive_entry.get("Drive Information", {})
                    eid_slt = drive_info.get("EID:Slt", "")
                    if eid_slt:
                        detailed_info = drive_entry.get("Drive Detailed Information", {})
                        if detailed_info:
                            pd_details_map[eid_slt] = {
                                "SN": detailed_info.get("Serial Number", "").strip(),
                                "Manufacturer Id": detailed_info.get("Vendor", "").strip(),
                                "WWN": detailed_info.get("WWN", "").strip(),
                                "Model Number": detailed_info.get("Model", "").strip()
                            }
                continue
            
            # Check for storcli "Physical Device Information" format
            physical_devices = response.get("Physical Device Information", {})
            if physical_devices:
                for drive_key, drive_data in physical_devices.items():
                    if isinstance(drive_data, list) and len(drive_data) > 0:
                        eid_slt = drive_data[0].get("EID:Slt", "")
                        if not eid_slt:
                            match = re.search(r"/e(\d+)/s(\d+)", drive_key)
                            if match:
                                eid_slt = f"{match.group(1)}:{match.group(2)}"
                        
                        detailed_key = f"{drive_key} - Detailed Information"
                        detailed_info = physical_devices.get(detailed_key, {})
                        device_attrs_key = f"{drive_key} Device attributes"
                        if device_attrs_key in detailed_info:
                            pd_details_map[eid_slt] = detailed_info[device_attrs_key]
    
    def get_enclosures(self) -> List[EnclosureInfo]:
        """Get enclosure information from storcli/storcli2"""
        if not self.cmd_name:
            return []
        
        try:
            output = self._execute_command([self.cmd_name, "/call/eall", "show", "all", "J"])
            data = self._parse_json(output)
            if not data:
                return []
            
            return self._parse_enclosures(data)
        except Exception as e:
            self.logger.error(f"Error getting enclosure information: {e}")
            return []
    
    def _parse_enclosures(self, json_data: Dict) -> List[EnclosureInfo]:
        """Parse enclosure information from JSON"""
        enclosures = []
        
        for controller_data in json_data.get("Controllers", []):
            response_data = controller_data.get("Response Data", {})
            command_status = controller_data.get("Command Status", {})
            controller_num = str(command_status.get("Controller", ""))
            
            # Check for storcli2 format
            enclosure_list = response_data.get("Enclosures", [])
            if not enclosure_list:
                enclosure_list = response_data.get("Enclosure List", [])
            
            if enclosure_list:
                for encl_entry in enclosure_list:
                    properties = encl_entry.get("Properties", [])
                    if properties and isinstance(properties, list) and len(properties) > 0:
                        props = properties[0]
                        eid = str(props.get("EID", ""))
                        product_id = props.get("ProdID", "").strip()
                        slots = str(props.get("Slots", "0"))
                        state = props.get("State", "")
                    else:
                        eid = str(encl_entry.get("EID", ""))
                        product_id = encl_entry.get("ProdID", "").strip()
                        slots = str(encl_entry.get("Slots", "0"))
                        state = encl_entry.get("State", "")
                    
                    if eid:
                        enclosure = EnclosureInfo(
                            controller=controller_num,
                            enclosure_id=eid,
                            product_id=product_id,
                            enclosure_type=product_id,
                            num_slots=int(slots) if slots.isdigit() else 0,
                            state=state
                        )
                        enclosures.append(enclosure)
            else:
                # storcli format
                enclosure_keys = [k for k in response_data.keys() if k.startswith("Enclosure")]
                for enclosure_key in enclosure_keys:
                    match = re.search(r"/c(\d+)/e(\d+)", enclosure_key)
                    if match:
                        ctrl_num = match.group(1)
                        eid = match.group(2)
                        
                        encl_data = response_data.get(enclosure_key, {})
                        inquiry = encl_data.get("Inquiry Data", {})
                        product_id = inquiry.get("Product Identification", "").rstrip()
                        properties = encl_data.get("Properties", [{}])[0] if encl_data.get("Properties") else {}
                        slots = str(properties.get("Slots", "0"))
                        
                        enclosure = EnclosureInfo(
                            controller=ctrl_num,
                            enclosure_id=eid,
                            product_id=product_id,
                            enclosure_type=product_id,
                            num_slots=int(slots) if slots.isdigit() else 0,
                            state=properties.get("State", "")
                        )
                        enclosures.append(enclosure)
        
        return enclosures
    
    def locate_disk(self, disk_info: DiskInfo, turn_off: bool, wait_seconds: Optional[int]) -> None:
        """Turn on/off the identify LED for a disk"""
        action = "stop" if turn_off else "start"
        cmd = [self.cmd_name, 
               f"/c{disk_info.controller}/e{disk_info.enclosure}/s{disk_info.drive}",
               action, "locate"]
        
        self._execute_command(cmd, handle_errors=False)
        
        if not turn_off and wait_seconds:
            import time
            time.sleep(wait_seconds)
            off_cmd = [self.cmd_name,
                      f"/c{disk_info.controller}/e{disk_info.enclosure}/s{disk_info.drive}",
                      "stop", "locate"]
            self._execute_command(off_cmd, handle_errors=False)
    
    def locate_all_disks(self, turn_off: bool, wait_seconds: Optional[int]) -> Tuple[int, int]:
        """Turn on/off LEDs for all disks"""
        disks = self.get_disks()
        success = 0
        failed = 0
        
        action = "stop" if turn_off else "start"
        
        successful_disks = []
        for disk in disks:
            try:
                cmd = [self.cmd_name,
                      f"/c{disk.controller}/e{disk.enclosure}/s{disk.drive}",
                      action, "locate"]
                self._execute_command(cmd, handle_errors=False)
                success += 1
                if not turn_off:
                    successful_disks.append(disk)
            except:
                failed += 1
        
        # Handle wait and auto-off
        if not turn_off and wait_seconds and successful_disks:
            import time
            time.sleep(wait_seconds)
            for disk in successful_disks:
                try:
                    cmd = [self.cmd_name,
                          f"/c{disk.controller}/e{disk.enclosure}/s{disk.drive}",
                          "stop", "locate"]
                    self._execute_command(cmd, handle_errors=False)
                except:
                    pass
        
        return success, failed


class SasIrcuController(StorageController):
    """Base class for sas2ircu and sas3ircu controllers"""
    
    def __init__(self, logger: logging.Logger, cmd_name: str):
        super().__init__(logger)
        self.cmd_name = cmd_name
    
    def get_command_name(self) -> str:
        return self.cmd_name
    
    def is_available(self) -> bool:
        import shutil
        if not shutil.which(self.cmd_name):
            return False
        try:
            self._execute_command([self.cmd_name, "LIST"], handle_errors=False)
            return True
        except:
            return False
    
    def get_disks(self) -> List[DiskInfo]:
        """Get disk information using sas2ircu/sas3ircu"""
        self.logger.info(f"Getting {self.cmd_name} disk information")
        disks = []
        
        try:
            controller_ids = self._get_controller_ids()
            
            for controller_id in controller_ids:
                output = self._execute_command([self.cmd_name, controller_id, "display"])
                disks.extend(self._parse_sas_disks(output, controller_id))
        except Exception as e:
            self.logger.error(f"Error getting {self.cmd_name} disk information: {e}")
        
        return disks
    
    def _get_controller_ids(self) -> List[str]:
        """Get list of controller IDs"""
        output = self._execute_command([self.cmd_name, "list"])
        controller_ids = []
        
        for line in output.splitlines():
            if re.match(r'^\s*\d+\s+\S', line):
                controller_id = line.strip().split()[0]
                controller_ids.append(controller_id)
        
        return controller_ids
    
    def _parse_sas_disks(self, output: str, controller_id: str) -> List[DiskInfo]:
        """Parse disk information from sas2ircu/sas3ircu display output"""
        disks = []
        lines = output.splitlines()
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            if "Device is a Hard disk" in line:
                disk_info = self._parse_disk_entry(lines, i)
                if disk_info and disk_info.get("manufacturer", "").strip() != "LSI":
                    disk = DiskInfo(
                        name=disk_info.get("guid", ""),
                        wwn=disk_info.get("guid", ""),
                        slot=disk_info.get("drive_type", ""),
                        controller=controller_id,
                        enclosure=disk_info.get("enclosure", ""),
                        drive=disk_info.get("slot", ""),
                        serial=disk_info.get("serial", ""),
                        model=disk_info.get("model", ""),
                        manufacturer=disk_info.get("manufacturer", "").strip()
                    )
                    disks.append(disk)
                i = disk_info.get("next_line", i + 1)
            else:
                i += 1
        
        return disks
    
    def _parse_disk_entry(self, lines: List[str], start_idx: int) -> Dict[str, Any]:
        """Parse a single disk entry from display output"""
        info = {}
        j = start_idx + 1
        
        while j < len(lines) and "Device is a" not in lines[j]:
            line = lines[j]
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                
                if "Enclosure #" in key:
                    info["enclosure"] = value
                elif "Slot #" in key:
                    info["slot"] = value
                elif "Serial No" in key:
                    info["serial"] = value
                elif "Model Number" in key:
                    info["model"] = value
                elif "Manufacturer" in key:
                    info["manufacturer"] = value
                elif "GUID" in key:
                    info["guid"] = value
                elif "Drive Type" in key:
                    info["drive_type"] = value
            j += 1
        
        info["next_line"] = j
        return info
    
    def get_enclosures(self) -> List[EnclosureInfo]:
        """Get enclosure information from sas2ircu/sas3ircu"""
        enclosures = []
        
        try:
            controller_ids = self._get_controller_ids()
            
            for controller_id in controller_ids:
                output = self._execute_command([self.cmd_name, controller_id, "display"])
                enclosures.extend(self._parse_enclosures(output, controller_id))
        except Exception as e:
            self.logger.error(f"Error getting enclosure information: {e}")
        
        return enclosures
    
    def _parse_enclosures(self, output: str, controller_id: str) -> List[EnclosureInfo]:
        """Parse enclosure information from display output"""
        enclosures = []
        current_encl = None
        
        for line in output.splitlines():
            line = line.strip()
            
            if 'Enclosure#' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    current_encl = parts[1].strip().rstrip(':')
            elif 'Logical ID' in line and current_encl:
                parts = line.split(':')
                if len(parts) > 1:
                    logical_id = ':'.join(parts[1:]).strip()
                    
                    # Get slot count
                    slots = 0
                    for slot_line in output.split('\n'):
                        if 'Numslots' in slot_line and current_encl in slot_line:
                            slot_parts = slot_line.split(':')
                            if len(slot_parts) > 1:
                                try:
                                    slots = int(slot_parts[1].strip())
                                except:
                                    pass
                    
                    enclosure = EnclosureInfo(
                        controller=controller_id,
                        enclosure_id=current_encl,
                        logical_id=logical_id,
                        num_slots=slots,
                        state="OK"
                    )
                    enclosures.append(enclosure)
                    current_encl = None
        
        return enclosures
    
    def locate_disk(self, disk_info: DiskInfo, turn_off: bool, wait_seconds: Optional[int]) -> None:
        """Turn on/off the identify LED for a disk"""
        action = "OFF" if turn_off else "ON"
        encl_slot = f"{disk_info.enclosure}:{disk_info.drive}"
        
        if wait_seconds and not turn_off and self._supports_wait():
            cmd = [self.cmd_name, "0", "LOCATE", encl_slot, action, "wait", str(wait_seconds)]
        else:
            cmd = [self.cmd_name, "0", "LOCATE", encl_slot, action]
        
        self._execute_command(cmd, handle_errors=False)
    
    def locate_all_disks(self, turn_off: bool, wait_seconds: Optional[int]) -> Tuple[int, int]:
        """Turn on/off LEDs for all disks"""
        disks = self.get_disks()
        success = 0
        failed = 0
        
        action = "OFF" if turn_off else "ON"
        successful_slots = []
        
        for disk in disks:
            encl_slot = f"{disk.enclosure}:{disk.drive}"
            try:
                if wait_seconds and not turn_off and self._supports_wait():
                    cmd = [self.cmd_name, "0", "LOCATE", encl_slot, action, "wait", str(wait_seconds)]
                else:
                    cmd = [self.cmd_name, "0", "LOCATE", encl_slot, action]
                
                self._execute_command(cmd, handle_errors=False)
                success += 1
                if not turn_off:
                    successful_slots.append(encl_slot)
            except:
                failed += 1
        
        # Manual wait and turn off if controller doesn't support wait parameter
        if not turn_off and wait_seconds and successful_slots and not self._supports_wait():
            import time
            time.sleep(wait_seconds)
            for encl_slot in successful_slots:
                try:
                    cmd = [self.cmd_name, "0", "LOCATE", encl_slot, "OFF"]
                    self._execute_command(cmd, handle_errors=False)
                except:
                    pass
        
        return success, failed
    
    def _supports_wait(self) -> bool:
        """Check if controller supports wait parameter"""
        return self.cmd_name == "sas3ircu"


class Sas2IrcuController(SasIrcuController):
    """Controller implementation for sas2ircu"""
    
    def __init__(self, logger: logging.Logger):
        super().__init__(logger, "sas2ircu")


class Sas3IrcuController(SasIrcuController):
    """Controller implementation for sas3ircu"""
    
    def __init__(self, logger: logging.Logger):
        super().__init__(logger, "sas3ircu")


def detect_controller(logger: logging.Logger) -> Optional[StorageController]:
    """Detect and return the first available controller"""
    
    # Try storcli2 first (preferred)
    storcli = StorcliController(logger, prefer_storcli2=True)
    if storcli.is_available():
        logger.info(f"Detected controller: {storcli.get_command_name()}")
        return storcli
    
    # Try sas2ircu
    sas2 = Sas2IrcuController(logger)
    if sas2.is_available():
        logger.info(f"Detected controller: {sas2.get_command_name()}")
        return sas2
    
    # Try sas3ircu
    sas3 = Sas3IrcuController(logger)
    if sas3.is_available():
        logger.info(f"Detected controller: {sas3.get_command_name()}")
        return sas3
    
    return None
