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