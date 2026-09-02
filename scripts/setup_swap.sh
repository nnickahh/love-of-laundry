#!/bin/bash
# =============================================================================
#  Raspberry Pi 5 — Virtual Memory (Swap + ZRAM) Setup for Image Processing
# =============================================================================
#  Compatible with Raspberry Pi OS 12 (Debian Bookworm) & older versions.
#  Configures 2GB swap space + ZRAM compressed swap to prevent OOM crashes.
# =============================================================================

set -e

echo "=============================================="
echo "  Raspberry Pi 5 Virtual Memory Setup"
echo "=============================================="

# ── 1. Configure Disk Swap (2 GB) ───────────────────────────────────────────
echo ""
echo "[1/4] Configuring disk swap (2 GB)..."

if command -v dphys-swapfile >/dev/null 2>&1; then
    echo "   Configuring via dphys-swapfile..."
    sudo dphys-swapfile swapoff 2>/dev/null || true
    sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile 2>/dev/null || {
        echo "CONF_SWAPSIZE=2048" | sudo tee -a /etc/dphys-swapfile
    }
    sudo sed -i 's/^CONF_MAXSWAP=.*/CONF_MAXSWAP=4096/' /etc/dphys-swapfile 2>/dev/null || {
        echo "CONF_MAXSWAP=4096" | sudo tee -a /etc/dphys-swapfile
    }
    sudo dphys-swapfile setup
    sudo dphys-swapfile swapon
else
    echo "   Configuring standard Debian 12 / Bookworm /swapfile..."
    sudo swapoff -a 2>/dev/null || true
    if [ ! -f /swapfile ] || [ "$(stat -c%s /swapfile 2>/dev/null || echo 0)" -lt 2147483648 ]; then
        sudo rm -f /swapfile
        sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
    fi
    sudo swapon /swapfile 2>/dev/null || true
    if ! grep -q "/swapfile" /etc/fstab; then
        echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
    fi
fi

echo "   ✓ Disk swap configured: 2 GB"

# ── 2. Setup ZRAM (Compressed In-Memory Swap) ────────────────────────────────
echo ""
echo "[2/4] Configuring ZRAM compressed swap..."

# Install zram-tools if not already installed
if ! dpkg -l | grep -q zram-tools; then
    sudo apt-get update -y && sudo apt-get install -y zram-tools
fi

# Configure ZRAM: use 50% of physical RAM with zstd compression
sudo tee /etc/default/zramswap > /dev/null << 'EOF'
# ZRAM Configuration for Raspberry Pi 5
# Compressed RAM swap — faster than SD card swap, reduces memory pressure

# Use 50% of physical RAM for compressed swap
PERCENTAGE=50

# Use zstd compression (best ratio on ARM64)
ALGO=zstd

# Higher priority than disk swap (ZRAM is faster)
PRIORITY=100
EOF

# Restart zramswap service
sudo systemctl enable zramswap 2>/dev/null || true
sudo systemctl restart zramswap 2>/dev/null || true

echo "   ✓ ZRAM enabled (50% of RAM, zstd compression)"

# ── 3. Kernel Memory Tuning for Real-Time Image Processing ───────────────────
echo ""
echo "[3/4] Tuning kernel VM parameters for image processing..."

sudo tee /etc/sysctl.d/99-laundry-vision.conf > /dev/null << 'EOF'
# Laundry Vision — Kernel VM tuning for real-time image processing
#
# vm.swappiness: How aggressively the kernel swaps out memory pages.
#   - 10 = only swap when absolutely necessary (keeps ONNX model in RAM).
vm.swappiness = 10

# vm.vfs_cache_pressure: Controls tendency to reclaim inode/dentry caches.
vm.vfs_cache_pressure = 50

# vm.dirty_ratio: Max % of RAM for dirty (unwritten) pages before sync.
vm.dirty_ratio = 10

# vm.dirty_background_ratio: Start background writeback at this % of RAM.
vm.dirty_background_ratio = 5

# vm.min_free_kbytes: Reserve this much RAM for critical kernel allocations.
vm.min_free_kbytes = 65536
EOF

# Apply immediately
sudo sysctl --system > /dev/null 2>&1 || true

echo "   ✓ Kernel VM parameters optimized"

# ── 4. GPU Memory Split (Minimize GPU reservation, maximize CPU RAM) ──────────
echo ""
echo "[4/4] Optimizing GPU memory split..."

CONFIG_FILE="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

if [ -f "$CONFIG_FILE" ]; then
    if grep -q "^gpu_mem=" "$CONFIG_FILE"; then
        sudo sed -i 's/^gpu_mem=.*/gpu_mem=16/' "$CONFIG_FILE"
    else
        echo "" | sudo tee -a "$CONFIG_FILE"
        echo "# Minimize GPU memory — maximize RAM for YOLO inference" | sudo tee -a "$CONFIG_FILE"
        echo "gpu_mem=16" | sudo tee -a "$CONFIG_FILE"
    fi
    echo "   ✓ GPU memory set to 16 MB (maximizes RAM for inference)"
else
    echo "   ⚠ Could not find config.txt, skipping GPU memory split"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  ✓ Virtual Memory Setup Complete!"
echo "=============================================="
echo ""
echo "  Current swap status:"
free -h | grep -i swap || true
echo ""
echo "  Swap devices:"
cat /proc/swaps 2>/dev/null || true
echo ""
echo "  Key settings applied:"
echo "    • Disk swap:       2 GB"
echo "    • ZRAM swap:       Active (compressed in-RAM)"
echo "    • vm.swappiness:   10 (keeps model in RAM)"
echo "    • GPU memory:      16 MB"
echo ""
echo "  ⚡ Please reboot now to apply all settings:"
echo "     sudo reboot"
echo ""
