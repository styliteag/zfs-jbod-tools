"""
TrueNAS API Client for the Storage Topology Tool

This module provides a client for interacting with TrueNAS via midclt.
"""

from typing import List, Dict, Any, Optional
import subprocess
import json
import logging
import re


class TrueNASClient:
    """Client for TrueNAS API via midclt"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def is_available(self) -> bool:
        """Check if midclt is available"""
        import shutil
        return shutil.which("midclt") is not None
    
    def query_disk(self, disk_name: str) -> Optional[Dict[str, Any]]:
        """Query information for a single disk
        
        Args:
            disk_name: Name of the disk (e.g., ada0)
            
        Returns:
            Dictionary with disk information or None if not found
        """
        disk_name = self._normalize_disk_name(disk_name)
        
        try:
            cmd = ["midclt", "call", "disk.query", f'[["name", "=", "{disk_name}"]]']
            output = self._execute_command(cmd)
            disks = json.loads(output)
            
            if disks:
                return disks[0]
            return None
        except Exception as e:
            self.logger.error(f"Error querying disk {disk_name}: {e}")
            return None
    
    def query_all_disks(self) -> List[Dict[str, Any]]:
        """Query information for all disks
        
        Returns:
            List of disk information dictionaries
        """
        try:
            cmd = ["midclt", "call", "disk.query", "[]"]
            output = self._execute_command(cmd)
            return json.loads(output)
        except Exception as e:
            self.logger.error(f"Error querying all disks: {e}")
            return []
    
    def update_disk_description(self, disk_identifier: str, description: str) -> bool:
        """Update disk description
        
        Args:
            disk_identifier: Disk identifier (not name)
            description: New description
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cmd = ["midclt", "call", "disk.update", disk_identifier,
                  f'{{"description": "{description}"}}']
            self._execute_command(cmd)
            return True
        except Exception as e:
            self.logger.error(f"Error updating disk description: {e}")
            return False
    
    def get_pool_disk_mapping(self) -> Dict[str, Dict[str, str]]:
        """Get mapping of disks to their ZFS pools
        
        Returns:
            Dictionary mapping disk names to pool info (pool name and state)
        """
        pool_mapping = {}
        
        # Try via zpool status first
        if self._check_command("zpool"):
            pool_mapping = self._get_pool_mapping_from_zpool()
        
        # If that didn't work, try TrueNAS API
        if not pool_mapping:
            pool_mapping = self._get_pool_mapping_from_api()
        
        return pool_mapping
    
    def _get_pool_mapping_from_zpool(self) -> Dict[str, Dict[str, str]]:
        """Get pool mapping from zpool status"""
        pool_mapping = {}
        
        try:
            # Try JSON format first
            try:
                cmd = ["zpool", "status", "-L", "-j"]
                output = self._execute_command(cmd)
                data = json.loads(output)
                
                if "pools" in data:
                    for pool_name, pool_info in data["pools"].items():
                        pool_state = pool_info.get("state", "UNKNOWN")
                        self._process_vdevs(pool_info.get("vdevs", {}), 
                                          pool_name, pool_state, pool_mapping)
            except:
                # Fall back to text parsing
                cmd = ["zpool", "status"]
                output = self._execute_command(cmd)
                pool_mapping = self._parse_zpool_text(output)
        except Exception as e:
            self.logger.warning(f"Error getting pool mapping from zpool: {e}")
        
        return pool_mapping
    
    def _get_pool_mapping_from_api(self) -> Dict[str, Dict[str, str]]:
        """Get pool mapping from TrueNAS API"""
        pool_mapping = {}
        
        try:
            cmd = ["midclt", "call", "pool.query", "[]"]
            output = self._execute_command(cmd)
            pools = json.loads(output)
            
            for pool in pools:
                pool_name = pool.get("name")
                if not pool_name:
                    continue
                
                try:
                    disk_cmd = ["midclt", "call", "pool.get_disks", f'["{pool_name}"]']
                    disk_output = self._execute_command(disk_cmd)
                    pool_disks = json.loads(disk_output)
                    
                    for disk in pool_disks:
                        base_disk = self._extract_base_disk_name(disk)
                        pool_mapping[base_disk] = {
                            "pool": pool_name,
                            "state": pool.get("status", "UNKNOWN")
                        }
                except Exception as e:
                    self.logger.warning(f"Error getting disks for pool {pool_name}: {e}")
        except Exception as e:
            self.logger.warning(f"Error getting pool mapping from API: {e}")
        
        return pool_mapping
    
    def _process_vdevs(self, vdevs: Dict, pool_name: str, pool_state: str,
                      pool_mapping: Dict[str, Dict[str, str]]) -> None:
        """Recursively process vdevs to find disks"""
        for vdev_name, vdev_info in vdevs.items():
            if "vdevs" in vdev_info:
                self._process_vdevs(vdev_info["vdevs"], pool_name, pool_state, pool_mapping)
            else:
                base_device = self._extract_base_disk_name(vdev_name)
                pool_mapping[base_device] = {
                    "pool": pool_name,
                    "state": pool_state
                }
    
    def _parse_zpool_text(self, output: str) -> Dict[str, Dict[str, str]]:
        """Parse text output from zpool status"""
        pool_mapping = {}
        current_pool = None
        in_config = False
        
        for line in output.splitlines():
            line_stripped = line.strip()
            
            if line_stripped.startswith("pool:"):
                current_pool = line_stripped.split(":", 1)[1].strip()
            elif line_stripped.startswith("config:"):
                in_config = True
            elif in_config and current_pool and line_stripped:
                if not line_stripped.startswith("NAME") and not line_stripped.startswith("state:"):
                    parts = line_stripped.split()
                    if len(parts) >= 1:
                        device = parts[0]
                        state = parts[1] if len(parts) > 1 else "UNKNOWN"
                        
                        if device != current_pool and not any(x in device for x in 
                                                             ["mirror", "raidz", "spare", "log", "cache"]):
                            base_device = self._extract_base_disk_name(device)
                            pool_mapping[base_device] = {
                                "pool": current_pool,
                                "state": state
                            }
        
        return pool_mapping
    
    def _extract_base_disk_name(self, device: str) -> str:
        """Extract base disk name from device path"""
        # Remove path prefix
        base = device.split("/")[-1].split("-")[0]
        # Remove partition numbers
        base = re.sub(r'(\D+)\d+$', r'\1', base)
        return base
    
    def _normalize_disk_name(self, disk_name: str) -> str:
        """Normalize disk name by removing /dev/ prefix"""
        if disk_name and disk_name.startswith('/dev/'):
            disk_name = disk_name.replace('/dev/', '')
        return disk_name
    
    def _check_command(self, cmd: str) -> bool:
        """Check if a command is available"""
        import shutil
        return shutil.which(cmd) is not None
    
    def _execute_command(self, cmd: List[str]) -> str:
        """Execute a command and return its output"""
        self.logger.debug(f"Executing command: {' '.join(cmd)}")
        
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.PIPE, 
                                           universal_newlines=True)
            return output
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed: {' '.join(cmd)}")
            raise
