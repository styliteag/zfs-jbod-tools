"""Base controller abstraction"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging
import subprocess
import json

from ..models import Disk, Enclosure


class BaseController(ABC):
    """Abstract base class for storage controllers"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the controller

        Args:
            logger: Logger instance for output
        """
        self.logger = logger or logging.getLogger(__name__)

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this controller is available on the system

        Returns:
            bool: True if controller is available and accessible
        """
        pass

    @abstractmethod
    def get_disks(self) -> List[Disk]:
        """Get list of all disks managed by this controller

        Returns:
            List[Disk]: List of disk objects
        """
        pass

    @abstractmethod
    def get_enclosures(self) -> List[Enclosure]:
        """Get list of all enclosures managed by this controller

        Returns:
            List[Enclosure]: List of enclosure objects
        """
        pass

    @abstractmethod
    def locate_disk(self, disk: Disk, turn_off: bool = False, wait_seconds: Optional[int] = None) -> bool:
        """Turn on or off the identify LED for a disk

        Args:
            disk: Disk object to locate
            turn_off: Whether to turn off the LED (default is to turn it on)
            wait_seconds: Optional number of seconds the LED should blink

        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    def locate_all_disks(self, turn_off: bool = False, wait_seconds: Optional[int] = None) -> tuple[int, int]:
        """Turn on or off the identify LED for all disks

        Args:
            turn_off: Whether to turn off the LED (default is to turn it on)
            wait_seconds: Optional number of seconds the LED should blink

        Returns:
            tuple[int, int]: Number of successful and failed operations
        """
        pass

    @property
    @abstractmethod
    def controller_type(self) -> str:
        """Get the controller type identifier

        Returns:
            str: Controller type (e.g., 'storcli', 'sas2ircu')
        """
        pass

    # Helper methods that can be used by all controllers

    def _execute_command(self, cmd: List[str], handle_errors: bool = True,
                        decode_method: str = 'utf-8') -> str:
        """Execute a command and return its output

        Args:
            cmd: Command to execute as list of strings
            handle_errors: Whether to handle errors or let them propagate
            decode_method: Method to decode command output

        Returns:
            str: Command output as string

        Raises:
            subprocess.CalledProcessError: If command fails and handle_errors is False
        """
        self.logger.debug(f"Executing command: {' '.join(cmd)}")

        try:
            output_bytes = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            try:
                output = output_bytes.decode(decode_method)
            except UnicodeDecodeError:
                self.logger.debug(f"{decode_method} decoding failed, falling back to latin-1")
                output = output_bytes.decode('latin-1')

            return output

        except subprocess.CalledProcessError as e:
            if handle_errors:
                self.logger.error(f"Error executing command {' '.join(cmd)}: {e}")
                return ""
            else:
                raise

    def _parse_json_output(self, output: str, error_msg: str = "") -> Dict[str, Any]:
        """Parse JSON output with error handling

        Args:
            output: String output to parse as JSON
            error_msg: Error message to log if parsing fails

        Returns:
            Dict[str, Any]: Parsed JSON data or empty dict on failure
        """
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            if error_msg:
                self.logger.error(f"{error_msg}: {e}")
            self.logger.debug(f"Raw output: {output[:200]}...")
            return {}

    def _check_command_exists(self, cmd: str) -> bool:
        """Check if a command exists in the system PATH

        Args:
            cmd: Command to check

        Returns:
            bool: True if command exists, False otherwise
        """
        import shutil
        return shutil.which(cmd) is not None
