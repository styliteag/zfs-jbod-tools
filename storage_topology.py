#!/usr/bin/env python3
"""
Storage Topology Tool

This script identifies physical disk locations by matching controller information with system devices.
It supports LSI MegaRAID controllers via storcli/storcli2 and LSI SAS controllers via sas2ircu/sas3ircu.

Refactored version with improved architecture:
- Modular design with separate concerns
- Type hints throughout
- Dataclasses instead of lists/dicts
- Strategy pattern for controllers
- Better testability

The old monolithic version (3091 lines) has been preserved as storage_topology_legacy.py
See REFACTORING.md for details on the improvements.

Usage:
    ./storage_topology.py                    # Show all disks with locations
    ./storage_topology.py -j                 # JSON output
    ./storage_topology.py --query            # Query TrueNAS disks
    ./storage_topology.py --locate sda       # Turn on LED for disk sda
    ./storage_topology.py --update-all       # Update all disk descriptions in TrueNAS
"""

import sys
import logging

from storage_topology import StorageTopology


def main():
    """Main entry point"""
    try:
        app = StorageTopology()
        app.run()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if logging.getLogger("storage-topology").level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
