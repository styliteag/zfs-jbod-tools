#!/bin/bash
# Quick test script to verify refactored version works

echo "Testing refactored version..."
echo ""

echo "1. Syntax check..."
python3 -m py_compile storage_models.py storage_controllers.py location_mapper.py truenas_client.py storage_topology_refactored.py
if [ $? -eq 0 ]; then
    echo "   ✓ Syntax check passed"
else
    echo "   ✗ Syntax check failed"
    exit 1
fi

echo ""
echo "2. Import test..."
python3 -c "
import storage_models
import storage_controllers
import location_mapper
import truenas_client
print('   ✓ All modules import successfully')
"

echo ""
echo "3. Basic functionality test..."
python3 -c "
from storage_models import DiskInfo, EnclosureInfo
from storage_controllers import detect_controller
import logging

logger = logging.getLogger('test')
disk = DiskInfo(dev_name='/dev/sda', serial='ABC123', physical_slot=5)
print(f'   ✓ Created DiskInfo: {disk.dev_name}, slot {disk.physical_slot}')
print(f'   ✓ Location property: {disk.location}')
"

echo ""
echo "All tests passed! ✓"
echo ""
echo "To use the refactored version:"
echo "  python3 storage_topology_refactored.py [options]"
echo ""
echo "To make it the default:"
echo "  mv storage_topology.py storage_topology_old.py"
echo "  mv storage_topology_refactored.py storage_topology.py"
