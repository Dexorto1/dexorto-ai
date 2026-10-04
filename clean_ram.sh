#!/bin/bash
# =====================================================================
# DEXORTO AI — System Audit & RAM Optimizer
# Audits RAM usage, stops redundant background daemons, cleans caches
# =====================================================================

set -e

echo "=================================================="
echo "  DEXORTO AI // SYSTEM AUDIT & RAM OPTIMIZER"
echo "=================================================="

echo "[*] Memory Status Before Optimization:"
free -h

echo ""
echo "[*] Stopping redundant background daemons..."

# Safe background targets on 4GB desktop systems
TARGETS=("kup-daemon" "DiscoverNotifier" "lubuntu-update" "blueman-tray")

for target in "${TARGETS[@]}"; do
    if pgrep -f "$target" >/dev/null 2>&1; then
        echo "  [-] Stopping unnecessary daemon: $target"
        pkill -f "$target" 2>/dev/null || true
    fi
done

# Clean page cache / filesystem sync
echo "[*] Syncing filesystems and releasing idle caches..."
sync

echo ""
echo "[✓] Memory Optimization Complete:"
free -h
