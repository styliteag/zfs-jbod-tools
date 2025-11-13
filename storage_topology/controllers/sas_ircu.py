"""SAS2IRCU/SAS3IRCU controller implementation"""

from typing import List, Dict, Any, Optional
import re
import time

from .base import BaseController
from ..models import Disk, Enclosure


class SasIrcuController(BaseController):
    """Controller for LSI SAS controllers using sas2ircu/sas3ircu"""

    def __init__(self, logger=None, controller_type: str = "sas2ircu"):
        """Initialize SasIrcuController

        Args:
            logger: Logger instance
            controller_type: Either 'sas2ircu' or 'sas3ircu'
        """
        super().__init__(logger)
        self.cmd = controller_type
        self._controller_type = controller_type

    @property
    def controller_type(self) -> str:
        """Get controller type identifier"""
        return self._controller_type

    def is_available(self) -> bool:
        """Check if sas2ircu/sas3ircu controller is available"""
        if not self._check_command_exists(self.cmd):
            return False

        try:
            self._execute_command([self.cmd, "LIST"], handle_errors=False)
            return True
        except Exception:
            return False

    def get_disks(self) -> List[Disk]:
        """Get all disks from sas2ircu/sas3ircu controller"""
        self.logger.info(f"Getting {self.cmd} disk information")
        disks = []

        try:
            # Get controller IDs
            list_output = self._execute_command([self.cmd, "list"])
            controller_ids = self._extract_controller_ids(list_output)

            self.logger.debug(f"Found controller IDs: {controller_ids}")

            # Loop over each controller
            for controller_id in controller_ids:
                display_output = self._execute_command([self.cmd, controller_id, "display"])
                disks.extend(self._parse_display_output(display_output, controller_id))

            self.logger.debug(f"Found {len(disks)} disks using {self.cmd}")

        except Exception as e:
            self.logger.error(f"Error getting {self.cmd} disk information: {e}")

        return disks

    def _extract_controller_ids(self, output: str) -> List[str]:
        """Extract controller IDs from LIST command output"""
        controller_ids = []

        for line in output.splitlines():
            # Look for lines starting with a number
            if re.match(r'^\s*\d+\s+\S', line):
                controller_id = line.strip().split()[0]
                controller_ids.append(controller_id)

        return controller_ids

    def _parse_display_output(self, output: str, controller_id: str) -> List[Disk]:
        """Parse DISPLAY command output to extract disk information"""
        disks = []
        lines = output.splitlines()
        i = 0

        while i < len(lines):
            line = lines[i]

            # Look for the start of a disk entry
            if "Device is a Hard disk" in line:
                disk = self._parse_disk_entry(lines, i + 1, controller_id)
                if disk:
                    disks.append(disk)
                    self.logger.debug(f"Found disk: {disk}")

            i += 1

        return disks

    def _parse_disk_entry(self, lines: List[str], start_idx: int, controller_id: str) -> Optional[Disk]:
        """Parse a single disk entry from display output"""
        enclosure = ""
        slot = ""
        sasaddr = ""
        manufacturer = ""
        model = ""
        serial = ""
        guid = ""
        drive_type = ""

        j = start_idx
        while j < len(lines) and "Device is a" not in lines[j]:
            disk_line = lines[j]

            if "Enclosure #" in disk_line:
                enclosure = disk_line.split(':')[1].strip()
            elif "Slot #" in disk_line:
                slot = disk_line.split(':')[1].strip()
            elif "SAS Address" in disk_line:
                sasaddr = disk_line.split(':')[1].strip()
            elif "Manufacturer" in disk_line:
                manufacturer = disk_line.split(':')[1].strip()
            elif "Model Number" in disk_line:
                model = disk_line.split(':')[1].strip()
            elif "Serial No" in disk_line:
                serial = disk_line.split(':')[1].strip()
            elif "GUID" in disk_line:
                guid = disk_line.split(':')[1].strip()
            elif "Drive Type" in disk_line:
                drive_type = disk_line.split(':')[1].strip()

            j += 1

        # Skip controller entries (typically have Manufacturer "LSI")
        if manufacturer and manufacturer.strip() != "LSI":
            return Disk(
                dev_name="",  # Will be filled later
                serial=serial,
                model=model,
                wwn=guid,
                controller=controller_id,
                enclosure=enclosure,
                slot=int(slot) if slot.isdigit() else 0,
                manufacturer=manufacturer.strip()
            )

        return None

    def get_enclosures(self) -> List[Enclosure]:
        """Get all enclosures from sas2ircu/sas3ircu controller"""
        self.logger.info(f"Getting {self.cmd} enclosure information")
        enclosures = []

        try:
            list_output = self._execute_command([self.cmd, "list"])
            controller_ids = self._extract_controller_ids(list_output)

            self.logger.debug(f"Found controller IDs: {controller_ids}")

            for ctrl_id in controller_ids:
                display_output = self._execute_command([self.cmd, ctrl_id, "display"])
                enclosures.extend(self._parse_enclosures(display_output, ctrl_id))

        except Exception as e:
            self.logger.warning(f"Error getting {self.cmd} enclosure information: {e}")

        return enclosures

    def _parse_enclosures(self, output: str, controller_id: str) -> List[Enclosure]:
        """Parse enclosure information from display output"""
        enclosures = []

        # Extract enclosure information section
        encl_info = ""
        capture = False

        for line in output.splitlines():
            if "Enclosure information" in line:
                capture = True
                continue
            if capture:
                if re.match(r'^-+$', line):
                    if encl_info:  # End of enclosure section
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
                logical_id = line.split(':', 1)[1].strip()
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

                enclosure = Enclosure(
                    controller_id=controller_id,
                    enclosure_id=encl_number,
                    logical_id=logical_id,
                    enclosure_type=encl_type,
                    slots=int(num_slots) if num_slots.isdigit() else 0,
                    start_slot=int(start_slot) if start_slot.isdigit() else 1
                )
                enclosures.append(enclosure)

                # Reset for next enclosure
                encl_number = logical_id = num_slots = start_slot = ""

        return enclosures

    def locate_disk(self, disk: Disk, turn_off: bool = False, wait_seconds: Optional[int] = None) -> bool:
        """Turn on or off the identify LED for a disk"""
        try:
            encl_slot = f"{disk.enclosure}:{disk.slot}"
            led_action = "OFF" if turn_off else "ON"

            # Build command based on wait parameter
            if wait_seconds is not None and not turn_off:
                cmd = [self.cmd, "0", "LOCATE", encl_slot, led_action, "wait", str(wait_seconds)]
            else:
                cmd = [self.cmd, "0", "LOCATE", encl_slot, led_action]

            self._execute_command(cmd, handle_errors=False)
            return True

        except Exception as e:
            self.logger.error(f"Error executing {self.cmd} locate command: {e}")
            return False

    def locate_all_disks(self, turn_off: bool = False, wait_seconds: Optional[int] = None) -> tuple[int, int]:
        """Turn on or off the identify LED for all disks"""
        try:
            display_output = self._execute_command([self.cmd, "0", "DISPLAY"])
            encl_slots = self._extract_enclosure_slots(display_output)

            if not encl_slots:
                self.logger.error("No disks found in controller output")
                return 0, 0

            success_count = 0
            failed_count = 0
            led_action = "OFF" if turn_off else "ON"

            # Check if controller supports wait parameter
            supports_wait = self._controller_type == "sas3ircu"

            # Turn on/off LEDs
            successful_slots = []
            for encl_slot in encl_slots:
                try:
                    if wait_seconds is not None and not turn_off and supports_wait:
                        cmd = [self.cmd, "0", "LOCATE", encl_slot, led_action, "wait", str(wait_seconds)]
                    else:
                        cmd = [self.cmd, "0", "LOCATE", encl_slot, led_action]

                    self._execute_command(cmd)
                    success_count += 1
                    if not turn_off:
                        successful_slots.append(encl_slot)

                except Exception as e:
                    self.logger.warning(f"Failed to {led_action} LED for {encl_slot}: {e}")
                    failed_count += 1

            # If turning on with wait and controller doesn't support it, wait and turn off manually
            if not turn_off and wait_seconds is not None and not supports_wait and successful_slots:
                time.sleep(wait_seconds)

                off_success = 0
                off_failed = 0
                for encl_slot in successful_slots:
                    try:
                        cmd = [self.cmd, "0", "LOCATE", encl_slot, "OFF"]
                        self._execute_command(cmd)
                        off_success += 1
                    except Exception:
                        off_failed += 1

                self.logger.info(f"Turned off {off_success} LEDs after wait period")
                if off_failed > 0:
                    self.logger.warning(f"Failed to turn off {off_failed} LEDs")

            return success_count, failed_count

        except Exception as e:
            self.logger.error(f"Error executing {self.cmd} command: {e}")
            return 0, 0

    def _extract_enclosure_slots(self, output: str) -> List[str]:
        """Extract all enclosure:slot combinations from display output"""
        encl_slots = []
        enclosure_pattern = re.compile(r'Enclosure #\s+:\s+(\d+)')
        slot_pattern = re.compile(r'Slot #\s+:\s+(\d+)')

        current_encl = None
        current_slot = None

        for line in output.splitlines():
            encl_match = enclosure_pattern.search(line)
            if encl_match:
                current_encl = encl_match.group(1)
                current_slot = None
                continue

            slot_match = slot_pattern.search(line)
            if slot_match and current_encl is not None:
                current_slot = slot_match.group(1)
                if current_encl and current_slot:
                    encl_slots.append(f"{current_encl}:{current_slot}")

        return encl_slots
