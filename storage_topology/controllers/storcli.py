"""Storcli/Storcli2 controller implementation"""

from typing import List, Dict, Any, Optional
import re
import time

from .base import BaseController
from ..models import Disk, Enclosure


class StorcliController(BaseController):
    """Controller for LSI MegaRAID controllers using storcli/storcli2"""

    def __init__(self, logger=None):
        """Initialize StorcliController"""
        super().__init__(logger)
        self.cmd = self._detect_storcli_command()

    def _detect_storcli_command(self) -> str:
        """Detect which storcli command is available (prefer storcli2)

        Returns:
            str: Command name ('storcli2' or 'storcli')
        """
        if self._check_command_exists("storcli2"):
            self.logger.debug("Found storcli2 command")
            return "storcli2"
        elif self._check_command_exists("storcli"):
            self.logger.debug("Found storcli command")
            return "storcli"
        return ""

    @property
    def controller_type(self) -> str:
        """Get controller type identifier"""
        return "storcli"

    def is_available(self) -> bool:
        """Check if storcli/storcli2 controller is available"""
        if not self.cmd:
            self.logger.debug("No storcli command found")
            return False

        try:
            output = self._execute_command([self.cmd, "show", "ctrlcount"], handle_errors=False)
            self.logger.debug(f"storcli output: {output[:200]}")
            controller_count_match = re.search(r"Controller Count = (\d+)", output)
            if controller_count_match:
                count = int(controller_count_match.group(1))
                self.logger.debug(f"Found {count} controllers")
                if count > 0:
                    return True
                else:
                    self.logger.debug("Controller count is 0")
            else:
                self.logger.debug("Could not find 'Controller Count' pattern in output")
        except Exception as e:
            self.logger.debug(f"Error checking storcli availability: {e}")

        return False

    def get_disks(self) -> List[Disk]:
        """Get all disks from storcli/storcli2 controller"""
        self.logger.info(f"Getting {self.cmd} disk information")

        try:
            output = self._execute_command([self.cmd, "/call", "show", "all", "J"])
            json_data = self._parse_json_output(output, "Failed to parse storcli JSON output")

            if not json_data:
                return []

            self.logger.debug(f"Got {self.cmd} output, controllers: {len(json_data.get('Controllers', []))}")

            disks = []
            for controller_idx, controller in enumerate(json_data.get("Controllers", [])):
                response_data = controller.get("Response Data", {})

                # Check format: storcli2 (PD LIST) or storcli (Physical Device Information)
                if "PD LIST" in response_data:
                    disks.extend(self._parse_storcli2_format(controller, response_data))
                elif "Physical Device Information" in response_data:
                    disks.extend(self._parse_storcli_format(controller, response_data))

            self.logger.debug(f"Total {self.cmd} disks found: {len(disks)}")
            return disks

        except Exception as e:
            self.logger.error(f"Error getting {self.cmd} disk information: {e}")
            return []

    def _parse_storcli2_format(self, controller: Dict, response_data: Dict) -> List[Disk]:
        """Parse storcli2 format (PD LIST array)"""
        disks = []
        pd_list = response_data.get("PD LIST", [])

        self.logger.debug(f"Detected storcli2 format with {len(pd_list)} drives in PD LIST")

        # Get controller number
        controller_num = str(controller.get("Command Status", {}).get("Controller", ""))

        # Get detailed information for all drives
        pd_details_map = self._get_pd_details_map(controller_num)

        # Process each PD entry
        for pd_entry in pd_list:
            eid_slt = pd_entry.get("EID:Slt", "")
            if not eid_slt or ":" not in eid_slt:
                continue

            enclosure, slot = eid_slt.split(":", 1)
            model = pd_entry.get("Model", "").strip()

            # Get detailed info from map
            pd_detail = pd_details_map.get(eid_slt, {})
            serial = pd_detail.get("SN", "").strip()
            manufacturer = pd_detail.get("Manufacturer Id", "").strip()
            wwn = pd_detail.get("WWN", "").strip()

            if not model and pd_detail.get("Model Number"):
                model = pd_detail.get("Model Number", "").strip()

            # Only add disks with at least enclosure and slot info
            if enclosure and slot:
                disk = Disk(
                    dev_name="",  # Will be filled later when matching with lsblk
                    serial=serial or "",
                    model=model or "",
                    wwn=wwn or "",
                    controller=controller_num,
                    enclosure=enclosure,
                    slot=int(slot) if slot.isdigit() else 0,
                    manufacturer=manufacturer or ""
                )
                disks.append(disk)
                self.logger.debug(f"Found {self.cmd} disk: {disk}")

        return disks

    def _parse_storcli_format(self, controller: Dict, response_data: Dict) -> List[Disk]:
        """Parse original storcli format (Physical Device Information)"""
        disks = []
        physical_devices = response_data.get("Physical Device Information", {})

        self.logger.debug("Detected storcli format with Physical Device Information")

        # Find all drive keys
        drive_keys = [k for k in physical_devices.keys()
                     if k.startswith("Drive /c") and "Detailed Information" not in k]

        self.logger.debug(f"Found drive keys: {drive_keys}")

        for drive_key in drive_keys:
            # Extract controller, enclosure, and slot from key
            controller_match = re.search(r"/c(\d+)", drive_key)
            controller_num = controller_match.group(1) if controller_match else ""

            enclosure_slot_match = re.search(r"/e(\d+)/s(\d+)", drive_key)
            if enclosure_slot_match:
                enclosure = enclosure_slot_match.group(1)
                slot = enclosure_slot_match.group(2)
            else:
                # Fallback to EID:Slt field
                try:
                    drive_info = physical_devices[drive_key][0]
                    enclosure_slot = drive_info.get("EID:Slt", "")
                    enclosure, slot = enclosure_slot.split(":") if ":" in enclosure_slot else ("", "")
                except (IndexError, KeyError):
                    self.logger.debug(f"Could not extract EID:Slt for drive {drive_key}")
                    continue

            # Get basic drive info
            try:
                basic_drive_info = physical_devices[drive_key][0]
                model = basic_drive_info.get("Model", "").strip()
            except (IndexError, KeyError):
                model = ""

            # Get detailed info
            detailed_key = f"{drive_key} - Detailed Information"
            detailed_info = physical_devices.get(detailed_key, {})

            device_attributes_key = f"{drive_key} Device attributes"
            if device_attributes_key in detailed_info:
                device_attributes = detailed_info[device_attributes_key]
                serial = device_attributes.get("SN", "").strip()
                manufacturer = device_attributes.get("Manufacturer Id", "").strip()
                wwn = device_attributes.get("WWN", "").strip()

                if not model and device_attributes.get("Model Number"):
                    model = device_attributes.get("Model Number", "").strip()
            else:
                serial = manufacturer = wwn = ""

            # Only add disks with a serial number
            if serial:
                disk = Disk(
                    dev_name="",  # Will be filled later
                    serial=serial,
                    model=model or "",
                    wwn=wwn or "",
                    controller=controller_num,
                    enclosure=enclosure,
                    slot=int(slot) if slot.isdigit() else 0,
                    manufacturer=manufacturer or ""
                )
                disks.append(disk)
                self.logger.debug(f"Found {self.cmd} disk: {disk}")

        return disks

    def _get_pd_details_map(self, controller_num: str) -> Dict[str, Dict]:
        """Get detailed PD information for all drives

        Args:
            controller_num: Controller number

        Returns:
            Dict mapping EID:Slt to detailed disk information
        """
        pd_details_map = {}

        # Try /call/eall/sall first
        try:
            output = self._execute_command(
                [self.cmd, "/call/eall/sall", "show", "all", "J"],
                handle_errors=False
            )
            json_data = self._parse_json_output(output)
            if json_data:
                self._extract_pd_details(json_data, pd_details_map)
        except Exception as e:
            self.logger.debug(f"Could not get PD details from /call/eall/sall: {e}")

        # If that didn't work, try /c{controller}/eall/sall
        if not pd_details_map and controller_num:
            try:
                output = self._execute_command(
                    [self.cmd, f"/c{controller_num}/eall/sall", "show", "all", "J"],
                    handle_errors=False
                )
                json_data = self._parse_json_output(output)
                if json_data:
                    self._extract_pd_details(json_data, pd_details_map)
            except Exception as e:
                self.logger.debug(f"Could not get PD details from /c{controller_num}/eall/sall: {e}")

        return pd_details_map

    def _extract_pd_details(self, json_data: Dict, pd_details_map: Dict) -> None:
        """Extract PD details from JSON response into the details map"""
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

            # Check for Physical Device Information (storcli format)
            physical_devices = response.get("Physical Device Information", {})
            if physical_devices:
                for drive_key, drive_data in physical_devices.items():
                    if isinstance(drive_data, list) and len(drive_data) > 0:
                        eid_slt = drive_data[0].get("EID:Slt", "")
                        if not eid_slt:
                            # Try to extract from key
                            eid_match = re.search(r"/e(\d+)/s(\d+)", drive_key)
                            if eid_match:
                                eid_slt = f"{eid_match.group(1)}:{eid_match.group(2)}"

                        detailed_key = f"{drive_key} - Detailed Information"
                        detailed_info = physical_devices.get(detailed_key, {})
                        device_attrs_key = f"{drive_key} Device attributes"
                        if device_attrs_key in detailed_info:
                            pd_details_map[eid_slt] = detailed_info[device_attrs_key]

    def get_enclosures(self) -> List[Enclosure]:
        """Get all enclosures from storcli/storcli2 controller"""
        self.logger.info("Getting enclosure information")
        enclosures = []

        try:
            output = self._execute_command([self.cmd, "/call/eall", "show", "all", "J"])
            json_data = self._parse_json_output(output, "Error parsing storcli enclosure information")

            if not json_data:
                return enclosures

            for controller_data in json_data.get("Controllers", []):
                response_data = controller_data.get("Response Data", {})
                command_status = controller_data.get("Command Status", {})
                controller_num = str(command_status.get("Controller", ""))

                # Check for storcli2 format: "Enclosures" or "Enclosure List"
                enclosure_list = response_data.get("Enclosures", [])
                if not enclosure_list:
                    enclosure_list = response_data.get("Enclosure List", [])

                if enclosure_list:
                    enclosures.extend(self._parse_storcli2_enclosures(enclosure_list, controller_num))
                else:
                    # storcli format: "Enclosure" keys
                    enclosures.extend(self._parse_storcli_enclosures(response_data, controller_num))

        except Exception as e:
            self.logger.warning(f"Error getting {self.cmd} enclosure information: {e}")

        return enclosures

    def _parse_storcli2_enclosures(self, enclosure_list: List, controller_num: str) -> List[Enclosure]:
        """Parse storcli2 enclosure format"""
        enclosures = []

        for enclosure_entry in enclosure_list:
            # Handle both formats: direct properties or Properties array
            properties = enclosure_entry.get("Properties", [])
            if properties and isinstance(properties, list) and len(properties) > 0:
                props = properties[0]
                eid = str(props.get("EID", ""))
                product_id = props.get("ProdID", "").strip()
                slots = str(props.get("Slots", "0"))
            else:
                eid = str(enclosure_entry.get("EID", ""))
                product_id = enclosure_entry.get("ProdID", "").strip()
                slots = str(enclosure_entry.get("Slots", "0"))

            if eid:
                enclosure = Enclosure(
                    controller_id=controller_num,
                    enclosure_id=eid,
                    product_id=product_id,
                    enclosure_type=product_id,
                    slots=int(slots) if slots.isdigit() else 0
                )
                enclosures.append(enclosure)

        return enclosures

    def _parse_storcli_enclosures(self, response_data: Dict, controller_num: str) -> List[Enclosure]:
        """Parse original storcli enclosure format"""
        enclosures = []
        enclosure_keys = [k for k in response_data.keys() if k.startswith("Enclosure")]

        for enclosure_key in enclosure_keys:
            controller_match = re.search(r"/c(\d+)/e(\d+)", enclosure_key)
            if controller_match:
                ctrl_num = controller_match.group(1)
                eid = controller_match.group(2)

                enclosure_data = response_data.get(enclosure_key, {})
                inquiry_data = enclosure_data.get("Inquiry Data", {})
                product_id = inquiry_data.get("Product Identification", "").rstrip()

                properties = enclosure_data.get("Properties", [{}])[0] if enclosure_data.get("Properties") else {}
                num_slots = str(properties.get("Slots", "0"))

                enclosure = Enclosure(
                    controller_id=ctrl_num,
                    enclosure_id=eid,
                    product_id=product_id,
                    enclosure_type=product_id,
                    slots=int(num_slots) if num_slots.isdigit() else 0
                )
                enclosures.append(enclosure)

        return enclosures

    def locate_disk(self, disk: Disk, turn_off: bool = False, wait_seconds: Optional[int] = None) -> bool:
        """Turn on or off the identify LED for a disk"""
        try:
            action = "stop" if turn_off else "start"
            cmd = [self.cmd, f"/c{disk.controller}/e{disk.enclosure}/s{disk.slot}", action, "locate"]
            self._execute_command(cmd, handle_errors=False)

            if not turn_off and wait_seconds is not None:
                # Auto turn-off after wait period
                time.sleep(wait_seconds)
                off_cmd = [self.cmd, f"/c{disk.controller}/e{disk.enclosure}/s{disk.slot}", "stop", "locate"]
                self._execute_command(off_cmd, handle_errors=False)

            return True

        except Exception as e:
            self.logger.error(f"Error executing {self.cmd} locate command: {e}")
            return False

    def locate_all_disks(self, turn_off: bool = False, wait_seconds: Optional[int] = None) -> tuple[int, int]:
        """Turn on or off the identify LED for all disks"""
        disks = self.get_disks()
        success_count = 0
        failed_count = 0

        action = "stop" if turn_off else "start"

        # Turn on/off all LEDs
        successful_disks = []
        for disk in disks:
            try:
                cmd = [self.cmd, f"/c{disk.controller}/e{disk.enclosure}/s{disk.slot}", action, "locate"]
                self._execute_command(cmd)
                success_count += 1
                if not turn_off:
                    successful_disks.append(disk)
            except Exception as e:
                self.logger.warning(f"Failed to {action} LED for disk {disk.dev_name}: {e}")
                failed_count += 1

        # If turning on and wait is specified, wait and then turn off
        if not turn_off and wait_seconds is not None and successful_disks:
            time.sleep(wait_seconds)

            off_success = 0
            off_failed = 0
            for disk in successful_disks:
                try:
                    cmd = [self.cmd, f"/c{disk.controller}/e{disk.enclosure}/s{disk.slot}", "stop", "locate"]
                    self._execute_command(cmd)
                    off_success += 1
                except Exception:
                    off_failed += 1

            self.logger.info(f"Turned off {off_success} LEDs after wait period")
            if off_failed > 0:
                self.logger.warning(f"Failed to turn off {off_failed} LEDs")

        return success_count, failed_count
