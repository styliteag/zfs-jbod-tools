# Storage Topology - Ausgabeformate

## Kompakte Ausgabe (Standard)

Standardmäßig zeigt das Tool nur die wichtigsten Spalten an:

```bash
./storage_topology.py
```

**Ausgabe:**
```
Device       Serial       Model             Enclosure    Slot  Location
/dev/sda     ABC123       ST4000DM004       Front JBOD   1     Front JBOD;SLOT:1;DISK:1
/dev/sdb     ABC124       ST4000DM004       Front JBOD   2     Front JBOD;SLOT:2;DISK:2
/dev/sdc     ABC125       ST4000DM004       Front JBOD   3     Front JBOD;SLOT:3;DISK:3
```

**Spalten:**
- **Device**: Gerätename (z.B. /dev/sda)
- **Serial**: Seriennummer (eindeutige Identifikation)
- **Model**: Festplattenmodell
- **Enclosure**: Name des Gehäuses
- **Slot**: Physischer Slot
- **Location**: Vollständige Positionsangabe

## Ausführliche Ausgabe (Verbose)

Für detaillierte Informationen verwenden Sie die `-v` Option:

```bash
./storage_topology.py -v
```

**Ausgabe:**
```
Device    Name           Slot  Ctrl  Enc  Drive  Serial  Model  Manufacturer  WWN  Enclosure  PhysSlot  LogDisk  Location
/dev/sda  /c0/e160/s0    160:0  0    160   0     ABC123  ST...  SEAGATE       ...  Front JBOD 1         1        Front JBOD;SLOT:1;DISK:1
```

**Zusätzliche Spalten:**
- **Name**: Controller-interner Name
- **Ctrl**: Controller-ID
- **Enc**: Enclosure-ID (Controller-intern)
- **Drive**: Drive/Slot auf Controller-Ebene
- **Manufacturer**: Hersteller
- **WWN**: World Wide Name
- **PhysSlot**: Physischer Slot (identisch mit Slot in kompakter Ansicht)
- **LogDisk**: Logische Disk-Nummer

## JSON-Ausgabe

Für maschinelle Verarbeitung:

```bash
./storage_topology.py -j
```

**Ausgabe:**
```json
[
  {
    "dev_name": "/dev/sda",
    "serial": "ABC123",
    "model": "ST4000DM004",
    "enclosure_name": "Front JBOD",
    "physical_slot": 1,
    "location": "Front JBOD;SLOT:1;DISK:1",
    ...
  }
]
```

## ZFS Pool Informationen

Zeigt physische Positionen für Disks in ZFS-Pools an:

```bash
./storage_topology.py -z
```

## TrueNAS Query

Zeigt Disk-Informationen aus TrueNAS mit Pool-Zuordnung:

```bash
# Einzelne Disk
./storage_topology.py --query sda

# Alle Disks
./storage_topology.py --query all

# Mit Pool-Filter
./storage_topology.py --query all --pool tank

# Nur Disks in Pools
./storage_topology.py --query all --pool-disks-only
```

## Zusammenfassung

| Befehl | Ausgabe | Verwendung |
|--------|---------|------------|
| `./storage_topology.py` | Kompakt (6 Spalten) | Tägliche Nutzung, schneller Überblick |
| `./storage_topology.py -v` | Ausführlich (14 Spalten) | Debugging, detaillierte Analyse |
| `./storage_topology.py -j` | JSON | Skripte, Automatisierung |
| `./storage_topology.py -z` | Mit ZFS-Info | Pool-Management |
| `./storage_topology.py --query` | TrueNAS-Abfrage | System-Administration |

## Tipps

### Breite Terminals
Für die ausführliche Ausgabe wird ein breites Terminal empfohlen (>200 Zeichen).

### Spaltenbreite
Die kompakte Ausgabe passt in ein Standard-Terminal (80-120 Zeichen).

### Sortierung
Disks werden automatisch nach Enclosure-Name und physischem Slot sortiert.
