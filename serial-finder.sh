#!/bin/bash

# Function to display usage information
display_usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -h, --help           Display this help message
  -j, --json           Output results in JSON format
  -z, --zpool          Display ZFS pool information
  -v, --verbose        Enable verbose output
  -c, --controller=X   Force use of specific controller (storcli, sas2ircu, sas3ircu)

This script identifies physical disk locations by matching controller information with system devices.
EOF
    exit 0
}

# Function to parse command line arguments
parse_arguments() {
    # Default values
    JSON_OUTPUT=false
    SHOW_ZPOOL=false
    VERBOSE=false
    FORCE_CONTROLLER=""
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                display_usage
                ;;
            -j|--json)
                JSON_OUTPUT=true
                shift
                ;;
            -z|--zpool)
                SHOW_ZPOOL=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -c=*|--controller=*)
                FORCE_CONTROLLER="${1#*=}"
                shift
                ;;
            -c|--controller)
                FORCE_CONTROLLER="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1" >&2
                display_usage
                ;;
        esac
    done
}

# Function to log messages
log_message() {
    local level="$1"
    local message="$2"
    
    if [ "$VERBOSE" = true ] || [ "$level" != "DEBUG" ]; then
        case "$level" in
            "ERROR")
                echo "[ERROR] $message" >&2
                ;;
            "WARNING")
                echo "[WARNING] $message" >&2
                ;;
            "INFO")
                echo "[INFO] $message"
                ;;
            "DEBUG")
                [ "$VERBOSE" = true ] && echo "[DEBUG] $message"
                ;;
        esac
    fi
}

# Function to check if a command exists
check_command_exists() {
    local cmd="$1"
    if command -v "$cmd" &> /dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

# Function to check if a controller is found
check_controller_found() {
    local controller="$1"
    local found="false"
    
    case "$controller" in
        "storcli")
            # Check if a controller is found
            local controller_count=$(storcli show ctrlcount | grep "Controller Count = " | awk '{print $4}')
            if [ "$controller_count" != "0" ]; then
                found="true"
            fi
            ;;
        "sas2ircu")
            # Check if a controller is found
            if sas2ircu LIST > /dev/null 2>&1; then
                found="true"
            fi
            ;;
        "sas3ircu")
            # Check if a controller is found
            if sas3ircu LIST > /dev/null 2>&1; then
                found="true"
            fi
            ;;
    esac
    
    echo "$found"
}

# Function to detect available controllers
detect_controllers() {
    local storcli_found=$(check_command_exists "storcli")
    local sas2ircu_found=$(check_command_exists "sas2ircu")
    local sas3ircu_found=$(check_command_exists "sas3ircu")
    
    if [ "$storcli_found" == "false" ] && [ "$sas2ircu_found" == "false" ] && [ "$sas3ircu_found" == "false" ]; then
        echo "Error: storcli, sas2ircu, and sas3ircu could not be found. Please install one of them first." >&2
        exit 1
    fi
    
    local storcli_found_controller="false"
    local sas2ircu_found_controller="false"
    local sas3ircu_found_controller="false"
    
    if [ "$storcli_found" == "true" ]; then
        storcli_found_controller=$(check_controller_found "storcli")
    fi
    
    if [ "$sas2ircu_found" == "true" ]; then
        sas2ircu_found_controller=$(check_controller_found "sas2ircu")
    fi
    
    if [ "$sas3ircu_found" == "true" ]; then
        sas3ircu_found_controller=$(check_controller_found "sas3ircu")
    fi
    
    if [ "$storcli_found_controller" == "false" ] && [ "$sas2ircu_found_controller" == "false" ] && [ "$sas3ircu_found_controller" == "false" ]; then
        echo "Error: No controller found. Please check your storcli, sas2ircu, or sas3ircu installation." >&2
        exit 1
    fi
    
    # Select the controller to use
    if [ "$storcli_found_controller" == "true" ]; then
        echo "storcli"
    elif [ "$sas2ircu_found_controller" == "true" ]; then
        echo "sas2ircu"
    elif [ "$sas3ircu_found_controller" == "true" ]; then
        echo "sas3ircu"
    fi
}

# Function to add caching to avoid repeated expensive operations
cache_output() {
    local key="$1"
    local output="$2"
    local cache_dir="/tmp/serial-finder-cache"
    local cache_file="$cache_dir/$key"
    
    # Create cache directory if it doesn't exist
    mkdir -p "$cache_dir"
    
    # Write output to cache file
    echo "$output" > "$cache_file"
}

get_cached_output() {
    local key="$1"
    local max_age="$2" # in seconds
    local cache_dir="/tmp/serial-finder-cache"
    local cache_file="$cache_dir/$key"
    
    # Check if cache file exists and is recent enough
    if [ -f "$cache_file" ]; then
        local file_age=$(($(date +%s) - $(stat -c %Y "$cache_file")))
        if [ "$file_age" -lt "$max_age" ]; then
            cat "$cache_file"
            return 0
        fi
    fi
    
    return 1
}

# Function to get disk information using storcli
get_storcli_disks() {
    # Try to get cached output first (valid for 5 minutes)
    local cached_output=$(get_cached_output "storcli_disks" 300)
    if [ $? -eq 0 ]; then
        log_message "DEBUG" "Using cached storcli disk information"
        echo "$cached_output"
        return
    fi
    
    log_message "DEBUG" "Getting fresh storcli disk information"
    local storcli_all_json=$(storcli /call show all J)
    
    # Parse the JSON output
    local disks_table_json=$(
    echo "$storcli_all_json" | jq '[.Controllers[] | .["Response Data"]["Physical Device Information"] as $pdi | 
    ($pdi | keys[] | select(startswith("Drive /c") and (contains("Detailed Information") | not))) as $driveKey |
        {
            name:         ($driveKey | split(" ")[1]),
            slot:         $pdi[$driveKey][0]["EID:Slt"],
            controller:   ($driveKey | capture("/c(?<c>[^/]+)").c),
            enclosure:    $pdi[$driveKey][0]["EID:Slt"] | split(":")[0],
            drive:        $pdi[$driveKey][0]["EID:Slt"] | split(":")[1],
            sn:           ($pdi[$driveKey + " - Detailed Information"] | .. | objects | .SN? // empty),
            model:        ($pdi[$driveKey + " - Detailed Information"] | .. | objects | ."Model Number"? // empty),
            manufacturer: ($pdi[$driveKey + " - Detailed Information"] | .. | objects | ."Manufacturer Id"? // empty),
            wwn:          ($pdi[$driveKey + " - Detailed Information"] | .. | objects | .WWN? // empty)
        } | select(.sn != null)
    ]')
    
    # Cache the output
    cache_output "storcli_disks" "$disks_table_json"
    
    echo "$disks_table_json"
}

# Function to get disk information using sas2ircu
get_sas2ircu_disks() {
    local disks_table=""
    local disks_table_json=""
    
    # Get controller IDs
    declare -a controller_ids
    while read -r line; do
        if [[ $line =~ ^[0-9]+$ ]]; then
            controller_ids+=("$line")
        fi
    done < <(sas2ircu list | awk 'c-->0;$0~s{if(b)for(c=b+1;c>1;c--)print r[(NR-c+1)%b];print;c=a}b{r[NR%b]=$0}' b=0 a=1 s="-----" | egrep -v '(-----)' | awk '{print $1}')
    
    # Loop over each controller
    for controller_id in "${controller_ids[@]}"; do
        local sas2ircu_table=$(sas2ircu "$controller_id" display | awk -F: '
            /Enclosure #/ { enclosure = $2; sub(/^ +/, "", enclosure) }
            /Slot #/ { slot = $2; sub(/^ +/, "", slot) }
            /SAS Address/ { sasaddr = $2; sub(/^ +/, "", sasaddr) }
            /State/ { state = $2; sub(/^ +/, "", state) }
            /Model Number/ { model = $2; sub(/^ +/, "", model) }
            /Manufacturer/ { manufacturer = $2; sub(/^ +/, "", manufacturer) }
            /GUID/ { guid = $2; sub(/^ +/, "", guid) }
            /Serial No/ { serial = $2; sub(/^ +/, "", serial) }
            /Protocol/ { protocol = $2; sub(/^ +/, "", protocol) }
            /Drive Type/ { drive = $2; sub(/^ +/, "", drive)
                if (manufacturer != "LSI     ") {  # Exclude manufacturer LSI # this is the controller
                    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", guid, drive, '"$controller_id"', enclosure, slot, serial, model, manufacturer, sasaddr
                }
                enclosure = slot = sasaddr = state = model = serial = protocol =  manufacturer = drive = ""  # Reset for the next device
            }')
        disks_table+="$sas2ircu_table"
        # add a new line
        disks_table+=$'\n'
    done
    
    local disks_table_json=$(echo "$disks_table" | jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {name: .[0], wwn: .[0], slot: .[1], controller: .[2], enclosure: .[3], drive: .[4], sn: .[5], model: .[6], manufacturer: .[7], sasaddr: .[8]})')
    
    echo "$disks_table_json"
}

# Function to get disk information from lsblk
get_lsblk_disks() {
    local lsblk_output=$(lsblk -p -d -o NAME,WWN,VENDOR,MODEL,REV,SERIAL,SIZE,PTUUID,HCTL,TRAN,TYPE -J)
    echo "$lsblk_output"
}

# Function to detect multipath disks
detect_multipath_disks() {
    # Check if multipath is available
    if command -v multipath &> /dev/null && command -v multipathd &> /dev/null; then
        if multipathd show paths format "%d %w" 2>/dev/null | grep -q "."; then
            # Multipath is active, get the mapping
            local multipath_map=$(multipathd show maps format "%w %d" 2>/dev/null | awk '{print $1 " " $2}')
            echo "$multipath_map"
            return 0
        fi
    fi
    # No multipath detected
    echo ""
    return 1
}

# Function to combine disk information from controller and lsblk
combine_disk_info() {
    local disks_table_json="$1"
    local lsblk="$2"
    
    # Get multipath mapping if available
    local multipath_map=$(detect_multipath_disks)
    local has_multipath=$?
    
    local lsblk_table=$(echo "$lsblk" | jq -r '.blockdevices[] | "\(.name)\t\(.wwn)\t\(.vendor)\t\(.model)\t\(.rev)\t\(.serial)\t\(.size)\t\(.ptuuid)\t\(.hctl)\t\(.tran)\t\(.type)"')
    
    local combined_disk=$(
    echo "$lsblk_table" | while IFS=$'\t' read -r dev_name wwn vendor model rev serial size ptuuid hctl tran type; do
        # Handle multipath devices
        local multipath_name=""
        if [ $has_multipath -eq 0 ] && [ -n "$wwn" ]; then
            multipath_name=$(echo "$multipath_map" | grep "$wwn" | awk '{print $2}')
        fi
        
        # Look for matching disk in DISKS_TABLE_JSON by serial or WWN
        # Remove the "0x" from the WWN
        local my_wwn=$(echo "$wwn" | sed 's/^0x//')
        # Lowercase the WWN
        my_wwn=$(echo "$my_wwn" | tr '[:upper:]' '[:lower:]')
        
        if [ -n "$my_wwn" ]; then
            # Extract all values in one jq call
            local disk_info=$(echo "$disks_table_json" | jq -r --arg serial "$serial" --arg wwn "$my_wwn" '
                [.[] | select(.wwn == $wwn or .sn == $serial)][0] | 
                    "\(.name)\t\(.slot)\t\(.controller)\t\(.enclosure)\t\(.drive)\t\(.sn)\t\(.model)\t\(.manufacturer)\t\(.wwn)"
            ')
            # Parse the tab-delimited output
            IFS=$'\t' read -r name slot controller enclosure drive disk_serial disk_model manufacturer disk_wwn <<< "$disk_info"
            
            if [ "$drive" == "n/a" ]; then
                drive="$vendor"
            fi
            if [ "$drive" == "" ]; then
                drive="xxx"
            fi
        else
            # If no serial, set default values
            name="None"
            slot="N/A"
            controller="N/A"
            enclosure="N/A"
            drive="None"
            disk_serial="N/A"
            disk_model="N/A"
            manufacturer="N/A"
            disk_wwn="N/A"
        fi
        
        # Add multipath info if available
        if [ -n "$multipath_name" ]; then
            echo -e "$dev_name\t$wwn\t$slot\t$controller\t$enclosure\t$drive\t$serial\t$model\t$manufacturer\t$wwn\t$vendor\t$multipath_name"
        else
            echo -e "$dev_name\t$wwn\t$slot\t$controller\t$enclosure\t$drive\t$serial\t$model\t$manufacturer\t$wwn\t$vendor\t-"
        fi
    done
    )
    
    echo "$combined_disk"
}

# Function to detect enclosure types
detect_enclosure_types() {
    local disks_table_json="$1"
    local controller="$2"
    
    # Create a mapping of enclosure IDs to types
    local enclosure_map="{}"
    
    if [ "$controller" == "storcli" ]; then
        # For storcli, we can get enclosure information directly
        local enclosure_info=$(storcli /call/eall show all J)
        
        # Parse the enclosure information to get types
        enclosure_map=$(echo "$enclosure_info" | jq -c '{
            Controllers: [.Controllers[] | 
                .["Response Data"] | 
                to_entries[] | 
                select(.key | startswith("Enclosure")) | 
                {
                    controller: (.key | capture("/c(?<c>[0-9]+)/e(?<e>[0-9]+)").c),
                    enclosure: (.key | capture("/c(?<c>[0-9]+)/e(?<e>[0-9]+)").e),
                    type: .value.["Inquiry Data"]["Product Identification"] | sub("\\s+$"; "")
                }
            ]
        }')
    elif [ "$controller" == "sas2ircu" ] || [ "$controller" == "sas3ircu" ]; then
        # For sas2ircu and sas3ircu, we'll need to infer based on patterns
        
        # Get list of controller IDs
        declare -a controller_ids
        while read -r line; do
            if [[ $line =~ ^[0-9]+$ ]]; then
                controller_ids+=("$line")
            fi
        done < <(${controller} list | awk 'c-->0;$0~s{if(b)for(c=b+1;c>1;c--)print r[(NR-c+1)%b];print;c=a}b{r[NR%b]=$0}' b=0 a=1 s="-----" | egrep -v '(-----)' | awk '{print $1}')
        
        # Build a list of controllers and enclosures
        local enclosure_list="[]"
        for ctrl_id in "${controller_ids[@]}"; do
            local encl_info=$(${controller} "$ctrl_id" display | grep -A3 "Enclosure information" | grep -E "Enclosure#|Logical ID|Numslots")
            local encl_data=$(echo "$encl_info" | awk '
                /Enclosure#/ { enclosure = $2; sub(/^ +/, "", enclosure); sub(/:$/, "", enclosure) }
                /Logical ID/ { logicalid = $2 $3; sub(/^ +/, "", logicalid) }
                /Numslots/ { slots = $2; sub(/^ +/, "", slots); 
                    printf "{\"controller\":\"%s\",\"enclosure\":\"%s\",\"logicalid\":\"%s\",\"slots\":\"%s\"},", 
                    "'$ctrl_id'", enclosure, logicalid, slots 
                }
            ')
            enclosure_list=$(echo "[$encl_data]" | sed 's/,]/]/')
        done
        
        # Now infer enclosure types based on the number of slots
        enclosure_map=$(echo "{\"Controllers\": $enclosure_list}" | jq -c '
            .Controllers[] |= (
                if .slots | tonumber > 20 then
                    .type = "JBOD"
                elif .slots | tonumber <= 8 then
                    .type = "Internal"
                else
                    .type = "Unknown"
                end
            )
        ')
    fi
    
    echo "$enclosure_map"
}

# Function to map enclosure and disk locations
map_disk_locations() {
    local combined_disk="$1"
    local controller="$2"
    
    # Get enclosure type mapping
    local enclosure_map=$(detect_enclosure_types "$DISKS_TABLE_JSON" "$controller")
    
    # Find all enclosures from combined disk data
    declare -a enclosures
    while IFS=$'\t' read -r dev_name name slot controller enclosure drive serial model manufacturer wwn vendor; do
        if [ "$enclosure" != "null" ]; then
            # If ENCLOSURE is a number then it's a JBOD
            if [[ "$enclosure" =~ ^[0-9]+$ ]]; then
                # Add the enclosure to the list if it's not already there
                if [[ ! " ${enclosures[@]} " =~ " ${enclosure} " ]]; then
                    enclosures+=("$enclosure")
                fi
            fi
        fi
    done <<< "$combined_disk"
    
    # Map disks to their physical locations
    local combined_disk_complete=$(echo "$combined_disk" | while IFS=$'\t' read -r dev_name name slot controller_id enclosure drive serial model manufacturer wwn vendor; do
        local enclosure_name=""
        local encslot=""
        local encdisk=""
        
        # Try to determine enclosure type from our mapping
        enclosure_type=$(echo "$enclosure_map" | jq -r --arg ctrl "$controller_id" --arg encl "$enclosure" \
            '.Controllers[] | select(.controller == $ctrl and .enclosure == $encl) | .type // "Unknown"')
        
        if [ "$enclosure_type" == "null" ] || [ "$enclosure_type" == "" ]; then
            enclosure_type="Unknown"
        fi
        
        # If its the first Enclosure in the ARRAY ENCLOSURES then it's the Local
        if [ "$enclosure" == "${enclosures[0]}" ]; then
            enclosure_name="Local"
            encslot=$((drive + 1))
            encdisk=$((drive + 0))
        elif [ "$enclosure" == "${enclosures[1]}" ]; then
            enclosure_name="$enclosure_type"
            encslot=$((drive + 1))
            encdisk=$((drive + 0))
        elif [ "$enclosure" == "${enclosures[2]}" ]; then
            enclosure_name="$enclosure_type"
            encslot=$((drive + 31))
            encdisk=$((drive + 30))
        else
            enclosure_name="$enclosure_type-$enclosure"
            encslot=$((drive + 1))
            encdisk=$((drive + 0))
        fi
        
        local location="$enclosure_name;SLOT:$encslot;DISK:$encdisk"
        echo -e "$dev_name\t$name\t$slot\t$controller_id\t$enclosure\t$drive\t$serial\t$model\t$manufacturer\t$wwn\t$enclosure_name\t$encslot\t$encdisk\t$location"
    done
    )
    
    echo "$combined_disk_complete"
}

# Function to get disk from partition
get_disk_from_partition() {
    local dev="$1"
    
    # Handle NVMe partitions (nvme0n1p1 -> nvme0n1)
    if echo "$dev" | grep -q "nvme.*p[0-9]\+$"; then
        echo "$dev" | sed 's/p[0-9]\+$//'
    # Handle traditional partitions (sda1 -> sda)
    else
        echo "$dev" | sed 's/[0-9]\+$//'
    fi
}

# Function to display ZFS pool disk information
display_zpool_info() {
    local combined_disk_complete="$1"
    local combined_disk_complete_json=$(echo "$combined_disk_complete" | jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {dev_name: .[0], name: .[1], slot: .[2], controller: .[3], enclosure: .[4], drive: .[5], serial: .[6], model: .[7], manufacturer: .[8], wwn: .[9], enclosure_name: .[10], encslot: .[11], encdisk: .[12], location: .[13]})')
    
    zpool status -LP | while read line; do
        # If the line contains "/dev/" then it's a disk
        if echo "$line" | grep -q "/dev/"; then
            # Extract the device name and status from the line
            local indentation=$(echo "$line" | awk '{print substr($0, 1, index($0, $1)-1)}')
            local dev=$(echo "$line" | awk '{print $1}')
            local status=$(echo "$line" | awk '{print $2}')
            
            # If the last character is a digit, then it's a partition
            # and we need to find the disk name
            if echo "$dev" | grep -q -E '(p|)[0-9]+$'; then
                dev=$(get_disk_from_partition "$dev")
            fi
            
            # Find the device in our combined disk info
            local disk_serial=$(echo "$combined_disk_complete_json" | jq -r --arg dev "$dev" '.[] | select(.dev_name | contains($dev)) | .serial')
            local disk_slot=$(echo "$combined_disk_complete_json" | jq -r --arg dev "$dev" '.[] | select(.dev_name == "'$dev'") | .encslot')
            local disk_enclosure=$(echo "$combined_disk_complete_json" | jq -r --arg dev "$dev" '.[] | select(.dev_name == "'$dev'") | .enclosure_name')
            local disk_location=$(echo "$combined_disk_complete_json" | jq -r --arg dev "$dev" '.[] | select(.dev_name == "'$dev'") | .location')
            
            if [ -n "$disk_serial" ]; then
                echo "${indentation}${dev} ${status} ${disk_location} (S/N: ${disk_serial})"
            else
                echo "$line"
            fi
        else
            echo "$line"
        fi
    done
}

# Function to check for required dependencies
check_dependencies() {
    local missing_deps=false
    
    for cmd in jq awk grep sed; do
        if ! command -v "$cmd" &> /dev/null; then
            log_message "ERROR" "Required dependency '$cmd' is not installed."
            missing_deps=true
        fi
    done
    
    if [ "$missing_deps" = true ]; then
        log_message "ERROR" "Please install the missing dependencies and try again."
        exit 1
    fi
}

# Function to load configuration file
load_config() {
    local config_file="$HOME/.config/serial-finder.conf"
    local system_config="/etc/serial-finder.conf"
    
    # Default configuration
    CUSTOM_MAPPINGS="{}"
    
    # Try user config first, then system config
    if [ -f "$config_file" ]; then
        log_message "INFO" "Loading user configuration from $config_file"
        source "$config_file"
    elif [ -f "$system_config" ]; then
        log_message "INFO" "Loading system configuration from $system_config"
        source "$system_config"
    else
        log_message "DEBUG" "No configuration file found, using defaults"
    fi
}

# Main function
main() {
    # Parse command line arguments
    parse_arguments "$@"
    
    # Check for required dependencies
    check_dependencies
    
    # Detect and select controller
    if [ -n "$FORCE_CONTROLLER" ]; then
        log_message "INFO" "Using forced controller: $FORCE_CONTROLLER"
        CONTROLLER="$FORCE_CONTROLLER"
    else
        log_message "INFO" "Detecting available controllers..."
        CONTROLLER=$(detect_controllers)
        log_message "INFO" "Selected controller: $CONTROLLER"
    fi
    
    # Get disk information based on the selected controller
    log_message "INFO" "Collecting disk information from $CONTROLLER..."
    if [ "$CONTROLLER" == "storcli" ]; then
        DISKS_TABLE_JSON=$(get_storcli_disks)
    elif [ "$CONTROLLER" == "sas2ircu" ]; then
        DISKS_TABLE_JSON=$(get_sas2ircu_disks)
    elif [ "$CONTROLLER" == "sas3ircu" ]; then
        # For now, use the same function as sas2ircu (modify as needed)
        DISKS_TABLE_JSON=$(get_sas2ircu_disks)
    else
        log_message "ERROR" "Unknown controller: $CONTROLLER"
        exit 1
    fi
    
    # Get lsblk information
    log_message "INFO" "Getting system block device information..."
    LSBLK=$(get_lsblk_disks)
    
    # Combine disk information
    log_message "INFO" "Matching controller devices with system devices..."
    COMBINED_DISK=$(combine_disk_info "$DISKS_TABLE_JSON" "$LSBLK")
    
    # Map disk locations
    log_message "INFO" "Mapping physical locations..."
    COMBINED_DISK_COMPLETE=$(map_disk_locations "$COMBINED_DISK" "$CONTROLLER")
    
    # Display the results
    if [ "$JSON_OUTPUT" = true ]; then
        # Output as JSON
        echo "$COMBINED_DISK_COMPLETE" | jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {
            device: .[0],
            name: .[1],
            slot: .[2],
            controller: .[3],
            enclosure: .[4],
            drive: .[5],
            serial: .[6],
            model: .[7],
            manufacturer: .[8],
            wwn: .[9],
            enclosure_name: .[10],
            physical_slot: .[11],
            logical_disk: .[12],
            location: .[13]
        })'
    else
        # Display as formatted table
        echo "$COMBINED_DISK_COMPLETE" | column -t -s $'\t'
    fi
    
    # Display ZFS pool information if requested
    if [ "$SHOW_ZPOOL" = true ]; then
        log_message "INFO" "Displaying ZFS pool information..."
        display_zpool_info "$COMBINED_DISK_COMPLETE"
    fi
}

# Run the main function with all arguments
main "$@"
