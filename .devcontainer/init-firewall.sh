#!/bin/bash
# Adapted from anthropics/claude-code@v2.1.318:.devcontainer/init-firewall.sh and the iptables pattern
# in trailofbits/claude-code-devcontainer@062e9e77:README.md. Both are allowlists. The owner chose
# open web, so this drops only private ranges: the host, the LAN and the tailnet.
set -euo pipefail

iptables -N SEXTANT_EGRESS 2>/dev/null || iptables -F SEXTANT_EGRESS
iptables -C OUTPUT -j SEXTANT_EGRESS 2>/dev/null || iptables -I OUTPUT 1 -j SEXTANT_EGRESS
iptables -A SEXTANT_EGRESS -o lo -j RETURN
for cidr in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 169.254.0.0/16 172.16.0.0/12 \
  192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4; do
  iptables -A SEXTANT_EGRESS -d "$cidr" -j REJECT --reject-with icmp-admin-prohibited
done

# runArgs switches IPv6 off. Stop if it is on, because the rules above are IPv4 only.
[[ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6)" == 1 ]]
