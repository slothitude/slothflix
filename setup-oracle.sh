#!/bin/bash
# SlothFlix setup for Oracle Cloud free tier (1GB RAM)
# Run once on the host: sudo bash setup-oracle.sh

set -e

echo "=== Adding 2GB swap ==="
if [ -f /swapfile ]; then
    echo "Swap already exists, skipping."
else
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "Swap added."
fi

echo "=== Tuning swappiness ==="
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

echo "=== Opening firewall ports ==="
for port in 8180 8890 9191; do
    iptables -I INPUT -p tcp --dport $port -j ACCEPT 2>/dev/null || true
done
# Persist iptables
if command -v netfilter-persistent &>/dev/null; then
    netfilter-persistent save
elif command -v iptables-save &>/dev/null; then
    iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
fi

echo "=== Done ==="
free -h
