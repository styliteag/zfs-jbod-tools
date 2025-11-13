"""
Data models for the Storage Topology Tool

This module defines dataclasses for representing storage-related information
in a type-safe and maintainable way.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
import json


@dataclass
class DiskInfo:
    """Information about a disk drive
    
    Attributes:
        dev_name: Device name (e.g., /dev/sda)
        serial: Disk serial number
        model: Disk model
        wwn: World Wide Name
        manufacturer: Disk manufacturer
        controller: Controller ID
        enclosure: Enclosure ID
        drive: Drive/slot number on controller
        slot: Combined enclosure:slot format
        name: Full drive path from controller
        vendor: Disk vendor
        multipath_name: Multipath device name if applicable
        enclosure_name: Human-readable enclosure name
        physical_slot: Physical slot number
        logical_disk: Logical disk number
    """
    dev_name: str = ""
    serial: str = ""
    model: str = ""
    wwn: str = ""
    manufacturer: str = ""
    controller: str = ""
    enclosure: str = ""
    drive: str = ""
    slot: str = ""
    name: str = ""
    vendor: str = ""
    multipath_name: str = "-"
    enclosure_name: str = ""
    physical_slot: int = 0
    logical_disk: int = 0
    
    @property
    def location(self) -> str:
        """Generate location string in standard format"""
        return f"{self.enclosure_name};SLOT:{self.physical_slot};DISK:{self.logical_disk}"
    
    def to_list(self) -> list:
        """Convert to legacy list format for backward compatibility
        
        Returns:
            List in the format expected by old code:
            [dev_name, name, slot, controller, enclosure, drive, serial, model, 
             manufacturer, wwn, enclosure_name, physical_slot, logical_disk, location]
        """
        return [
            self.dev_name,
            self.name,
            self.slot,
            self.controller,
            self.enclosure,
            self.drive,
            self.serial,
            self.model,
            self.manufacturer,
            self.wwn,
            self.enclosure_name,
            str(self.physical_slot),
            str(self.logical_disk),
            self.location
        ]
    
    @classmethod
    def from_list(cls, data: list) -> 'DiskInfo':
        """Create DiskInfo from legacy list format
        
        Args:
            data: List in legacy format
            
        Returns:
            DiskInfo instance
        """
        if len(data) < 14:
            raise ValueError(f"Expected at least 14 elements, got {len(data)}")
        
        return cls(
            dev_name=data[0],
            name=data[1],
            slot=data[2],
            controller=data[3],
            enclosure=data[4],
            drive=data[5],
            serial=data[6],
            model=data[7],
            manufacturer=data[8],
            wwn=data[9],
            enclosure_name=data[10],
            physical_slot=int(data[11]) if data[11] and data[11] != "null" else 0,
            logical_disk=int(data[12]) if data[12] and data[12] != "null" else 0
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output"""
        return {
            "dev_name": self.dev_name,
            "name": self.name,
            "slot": self.slot,
            "controller": self.controller,
            "enclosure": self.enclosure,
            "drive": self.drive,
            "serial": self.serial,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "wwn": self.wwn,
            "vendor": self.vendor,
            "multipath_name": self.multipath_name,
            "enclosure_name": self.enclosure_name,
            "physical_slot": self.physical_slot,
            "logical_disk": self.logical_disk,
            "location": self.location
        }


@dataclass
class EnclosureInfo:
    """Information about a disk enclosure
    
    Attributes:
        controller: Controller ID
        enclosure_id: Enclosure ID
        product_id: Product identification string
        logical_id: Logical ID (for SAS controllers)
        enclosure_type: Type of enclosure (JBOD, Internal, etc.)
        num_slots: Number of slots in enclosure
        hw_start_slot: Hardware starting slot number
        sas_address: SAS address of enclosure
        state: Enclosure state (OK, etc.)
    """
    controller: str = ""
    enclosure_id: str = ""
    product_id: str = ""
    logical_id: str = ""
    enclosure_type: str = "Unknown"
    num_slots: int = 0
    hw_start_slot: int = 1
    sas_address: str = ""
    state: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output"""
        return asdict(self)
    
    @property
    def key(self) -> str:
        """Generate a unique key for this enclosure"""
        return f"{self.controller}_{self.enclosure_id}"


@dataclass
class EnclosureConfig:
    """Configuration for an enclosure from the config file
    
    Attributes:
        id: Enclosure identifier (logical_id, product_id, or enclosure_id)
        name: Human-readable name
        start_slot: Starting slot number for logical numbering (1-based)
        max_slots: Maximum number of slots
        offset: Offset for slot calculation
    """
    id: str
    name: str
    start_slot: int = 1
    max_slots: int = 0
    offset: int = 0
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EnclosureConfig':
        """Create from dictionary (config file entry)"""
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            start_slot=int(data.get('start_slot', 1)),
            max_slots=int(data.get('max_slots', 0)),
            offset=int(data.get('offset', 0))
        )


@dataclass
class DiskMapping:
    """Custom disk mapping from configuration file
    
    Attributes:
        serial: Disk serial number
        enclosure: Custom enclosure name
        slot: Physical slot number
        disk: Logical disk number
    """
    serial: str
    enclosure: str = "Custom"
    slot: int = 0
    disk: int = 0
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DiskMapping':
        """Create from dictionary (config file entry)"""
        return cls(
            serial=data.get('serial', ''),
            enclosure=data.get('enclosure', 'Custom'),
            slot=int(data.get('slot', 0)),
            disk=int(data.get('disk', 0))
        )
