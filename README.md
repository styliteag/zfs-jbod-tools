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

#### ZFS Pool Integration (with -z/--zpool option)
```
  pool: storage_pool
 state: ONLINE
status: Some supported and requested features are not enabled on the pool.
        The pool can still be used, but some features are unavailable.
action: Enable all features using 'zpool upgrade'. Once this is done,
        the pool may no longer be accessible by software that does not support
        the features. See zpool-features(7) for details.
  scan: resilvered 33.0G in 01:06:08 with 0 errors on Wed Jan 15 10:57:18 2023
config:

        NAME            STATE     READ WRITE CKSUM
        storage_pool    ONLINE       0     0     0
          raidz2-0      ONLINE       0     0     0
            /dev/sdad ONLINE BayRear;SLOT:27 (S/N: DISK123XX)
            /dev/sdh ONLINE BayFront;SLOT:5 (S/N: DISK456XX)
            /dev/sdj ONLINE BayFront;SLOT:7 (S/N: DISK789XX)
            /dev/sdf ONLINE BayFront;SLOT:3 (S/N: DISKA12XX)
            /dev/sdo ONLINE BayFront;SLOT:12 (S/N: DISKB34XX)
            /dev/sdc ONLINE BayFront;SLOT:0 (S/N: DISKC56XX)
            /dev/sdd ONLINE BayFront;SLOT:1 (S/N: DISKD78XX)
            /dev/sdn ONLINE BayFront;SLOT:11 (S/N: DISKE90XX)
            /dev/sdk ONLINE BayFront;SLOT:8 (S/N: DISKF12XX)
            /dev/sdg ONLINE BayFront;SLOT:4 (S/N: DISKG34XX)
            /dev/sdak ONLINE BayRear;SLOT:34 (S/N: DISKH56XX)
            /dev/sdx ONLINE BayFront;SLOT:21 (S/N: DISKI78XX)
            /dev/sdi ONLINE BayFront;SLOT:6 (S/N: DISKJ90XX)
            /dev/sdq ONLINE BayFront;SLOT:14 (S/N: DISKK12XX)
            /dev/sdp ONLINE BayFront;SLOT:13 (S/N: DISKL34XX)
            /dev/sde ONLINE BayFront;SLOT:2 (S/N: DISKM56XX)
            /dev/sds ONLINE BayFront;SLOT:16 (S/N: DISKN78XX)
          raidz2-1      ONLINE       0     0     0
            /dev/sdu ONLINE BayFront;SLOT:18 (S/N: DISKO90XX)
            /dev/sdac ONLINE BayRear;SLOT:26 (S/N: DISKP12XX)
            /dev/sdv ONLINE BayFront;SLOT:19 (S/N: DISKQ34XX)
            /dev/sdal ONLINE BayRear;SLOT:35 (S/N: DISKR56XX)
            /dev/sdae ONLINE BayRear;SLOT:28 (S/N: DISKS78XX)
            /dev/sdaj ONLINE BayRear;SLOT:33 (S/N: DISKT90XX)
            /dev/sdt ONLINE BayFront;SLOT:17 (S/N: DISKU12XX)
            /dev/sdy ONLINE BayFront;SLOT:22 (S/N: DISKV34XX)
            /dev/sdz ONLINE BayFront;SLOT:23 (S/N: DISKW56XX)
            /dev/sdab ONLINE BayRear;SLOT:25 (S/N: DISKX78XX)
            /dev/sdaa ONLINE BayRear;SLOT:24 (S/N: DISKY90XX)
            /dev/sdaf ONLINE BayRear;SLOT:29 (S/N: DISKZ12XX)
            /dev/sdag ONLINE BayRear;SLOT:30 (S/N: DISK1ABXX)
            /dev/sdl ONLINE BayFront;SLOT:9 (S/N: DISK2CDXX)
            /dev/sdah ONLINE BayRear;SLOT:31 (S/N: DISK3EFXX)
            /dev/sdr ONLINE BayFront;SLOT:15 (S/N: DISK4GHXX)
            /dev/sdw ONLINE BayFront;SLOT:20 (S/N: DISK5IJXX)
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