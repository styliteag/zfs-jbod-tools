# ZFS JBOD Tools

A collection of utilities for identifying and mapping physical disk locations in storage systems, particularly useful for ZFS environments with JBODs (Just a Bunch Of Disks).

## Storage Topology

The main component is `storage_topology.py`, a Python tool that identifies physical disk locations by matching controller information with system devices.

### Key Features

- Detects available storage controllers automatically (storcli, sas2ircu, sas3ircu)
- Matches physical disk locations with system block devices
- Supports JSON output for programmatic use
- Integrates with ZFS pools to show physical locations of pool devices
- Handles multipath devices
- Customizable through configuration files

### Usage

```bash
./storage_topology.py [OPTIONS]

Options:
  -h, --help           Display help message
  -j, --json           Output results in JSON format
  -z, --zpool          Display ZFS pool information
  -v, --verbose        Enable verbose output
  -c, --controller=X   Force use of specific controller (storcli, sas2ircu, sas3ircu)
  -f, --force          Force refresh of cached data
```

### Example Output

#### Standard Text Output
```
/dev/sda   0x50014ee058ffcee8  SATA_HDD  0     1     2      WD-WMAYP6774338        WDC WD5003ABYZ-011FA0  ATA           0x50014ee058ffcee8  BayFront      1        2        BayFront;SLOT:1
/dev/sdb   0x50014ee0ae5561af  SATA_HDD  0     1     3      WD-WMAYP6774881        WDC WD5003ABYZ-011FA0  ATA           0x50014ee0ae5561af  BayFront      2        3        BayFront;SLOT:2
/dev/sdc   0x5000cca03b02b27c  SAS_HDD   0     2     0      PBG1GZJX               HUS724040ALS640        HGST          0x5000cca03b02b27c  Front-Bay     0        0        Front-Bay;SLOT:0
```

#### JSON Output (with -j/--json option)
```json
[
  {
    "device": "/dev/sda",
    "name": "0x50014ee058ffcee8",
    "slot": "SATA_HDD",
    "controller": "0",
    "enclosure": "1",
    "drive": "2",
    "serial": "WD-WMAYP6776338",
    "model": "WDC WD5003ABYZ-011FA0",
    "manufacturer": "ATA",
    "wwn": "0x50014ee058ffcee8",
    "enclosure_name": "Internal",
    "physical_slot": "102",
    "logical_disk": "2",
    "location": "Internal;SLOT:102;DISK:2"
  },
  {
    "device": "/dev/sdb",
    "name": "0x50014ee0ae5561af",
    "slot": "SATA_HDD",
    "controller": "0",
    "enclosure": "1",
    "drive": "3",
    "serial": "WD-WMAYP6776881",
    "model": "WDC WD5003ABYZ-011FA0",
    "manufacturer": "ATA",
    "wwn": "0x50014ee0ae5561af",
    "enclosure_name": "Internal",
    "physical_slot": "103",
    "logical_disk": "3",
    "location": "Internal;SLOT:103;DISK:3"
  }
]
```

The output shows:
- System device path (`/dev/sd*`)
- Drive identifier (WWN or GUID)
- Drive type (SAS_HDD, SATA_HDD, etc.)
- Controller, enclosure, and drive numbers
- Serial number, model, and manufacturer
- Human-readable enclosure name (from configuration)
- Physical slot number (with any configured offset applied)
- Logical disk number
- Complete location string (useful for identification)

## Configuration

The `storage_topology.conf` file allows customization of enclosure mappings and disk locations. It uses YAML syntax to define:

- Enclosure configurations (mapping controller logical IDs to human-readable names)
- Custom slot numbering and offsets
- Special handling for specific disks by serial number

Example configuration:

```yaml
# Enclosure configuration
enclosures:
  - id: "500605b0:07459eb0"  # Logical ID from the controller
    name: "Internal"         # Human-readable name
    offset: 100              # Offset to add to the real slot number
    start_slot: 0            # Starting slot number

  - id: "50030480:00a0dabf"
    name: "BayFront"
    offset: 0
    start_slot: 0

# Custom disk mappings by serial number
disks:
  - serial: "ABCDEF123456"   # Disk serial number
    enclosure: "Custom"      # Custom enclosure name
    slot: 42                 # Custom slot number
    disk: 42                 # Custom disk number
```

## Legacy Shell Script

**Note**: The `storage-topology.sh` shell script is deprecated and has been replaced by the Python implementation (`storage_topology.py`). The Python version offers improved functionality, reliability, and configuration options.

## Requirements

- Python 3.6+
- Storage controller utilities (storcli, sas2ircu, or sas3ircu)
- lsblk (for block device information)
- ZFS utilities (optional, for pool integration) 