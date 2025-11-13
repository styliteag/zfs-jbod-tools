"""Data models for storage topology"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Disk:
    """Represents a physical disk in the storage system"""

    dev_name: str                    # Device name (e.g., /dev/sda)
    serial: str                      # Serial number
    model: str                       # Model number
    wwn: str                         # World Wide Name
    controller: str                  # Controller ID
    enclosure: str                   # Enclosure ID
    slot: int                        # Slot number within enclosure
    manufacturer: str = ""           # Manufacturer name
    size: str = ""                   # Disk size
    vendor: str = ""                 # Vendor information

    # Mapped location information
    enclosure_name: str = ""         # Human-readable enclosure name
    physical_slot: int = 0           # Physical slot number
    logical_disk: int = 0            # Logical disk number

    def __post_init__(self):
        """Validate and normalize disk data after initialization"""
        # Normalize empty strings to defaults
        if self.serial == "null" or self.serial is None:
            self.serial = ""
        if self.wwn == "null" or self.wwn is None:
            self.wwn = ""

    @property
    def location(self) -> str:
        """Generate location string in standardized format"""
        if self.enclosure_name and self.physical_slot:
            return f"{self.enclosure_name};SLOT:{self.physical_slot};DISK:{self.logical_disk}"
        return "-"

    @property
    def short_name(self) -> str:
        """Get short device name without /dev/ prefix"""
        return self.dev_name.replace("/dev/", "")

    def to_dict(self) -> dict:
        """Convert disk to dictionary representation"""
        return {
            "dev_name": self.dev_name,
            "serial": self.serial,
            "model": self.model,
            "wwn": self.wwn,
            "controller": self.controller,
            "enclosure": self.enclosure,
            "slot": self.slot,
            "manufacturer": self.manufacturer,
            "size": self.size,
            "vendor": self.vendor,
            "enclosure_name": self.enclosure_name,
            "physical_slot": self.physical_slot,
            "logical_disk": self.logical_disk,
            "location": self.location
        }


@dataclass
class Enclosure:
    """Represents a physical enclosure in the storage system"""

    controller_id: str               # Controller this enclosure is connected to
    enclosure_id: str                # Enclosure ID from controller
    logical_id: str = ""             # Logical ID (SAS address)
    product_id: str = ""             # Product identification
    enclosure_type: str = "Unknown"  # Type of enclosure (JBOD, Internal, etc.)
    slots: int = 0                   # Number of slots in enclosure
    start_slot: int = 1              # Starting slot number (hardware)

    @property
    def key(self) -> str:
        """Generate unique key for enclosure lookup"""
        return f"{self.controller_id}_{self.enclosure_id}"

    def to_dict(self) -> dict:
        """Convert enclosure to dictionary representation"""
        return {
            "controller": self.controller_id,
            "enclosure": self.enclosure_id,
            "logical_id": self.logical_id,
            "type": self.enclosure_type,
            "slots": self.slots,
            "start_slot": self.start_slot
        }


@dataclass
class EnclosureConfig:
    """Represents user configuration for an enclosure"""

    id: str                          # ID to match enclosure (logical_id, enclosure_id, or product_id)
    name: str                        # Human-readable name
    start_slot: int = 1              # Starting slot for numbering (1-based)
    max_slots: int = 0               # Maximum number of slots
    offset: int = 0                  # Offset for slot calculation

    def to_dict(self) -> dict:
        """Convert config to dictionary representation"""
        return {
            "id": self.id,
            "name": self.name,
            "start_slot": self.start_slot,
            "max_slots": self.max_slots,
            "offset": self.offset
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EnclosureConfig":
        """Create EnclosureConfig from dictionary"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            start_slot=int(data.get("start_slot", 1)),
            max_slots=int(data.get("max_slots", 0)),
            offset=int(data.get("offset", 0))
        )


@dataclass
class DiskMapping:
    """Represents a custom disk mapping"""

    serial: str                      # Disk serial number to match
    enclosure: str = "Custom"        # Custom enclosure name
    slot: int = 0                    # Physical slot number
    disk: int = 0                    # Logical disk number

    def to_dict(self) -> dict:
        """Convert mapping to dictionary representation"""
        return {
            "serial": self.serial,
            "enclosure": self.enclosure,
            "slot": self.slot,
            "disk": self.disk
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiskMapping":
        """Create DiskMapping from dictionary"""
        return cls(
            serial=data.get("serial", ""),
            enclosure=data.get("enclosure", "Custom"),
            slot=int(data.get("slot", 0)),
            disk=int(data.get("disk", 0))
        )
