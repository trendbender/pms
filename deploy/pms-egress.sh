#!/usr/bin/env bash
set -uo pipefail
SUBNET=$(docker network inspect pms_default -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null)
[ -z "$SUBNET" ] && { echo "pms_default not found, skip"; exit 0; }
# purge prior pms-egress rules
while iptables -L DOCKER-USER -n --line-numbers 2>/dev/null | grep -q 'pms-egress'; do
  n=$(iptables -L DOCKER-USER -n --line-numbers | awk '/pms-egress/{print $1; exit}')
  iptables -D DOCKER-USER "$n" 2>/dev/null || break
done
C=(-m comment --comment pms-egress)
# insert reverse so final order: ESTABLISHED, private RETURNs, DROP
iptables -I DOCKER-USER 1 -s "$SUBNET" -j DROP "${C[@]}"
iptables -I DOCKER-USER 1 -s "$SUBNET" -d 127.0.0.0/8    -j RETURN "${C[@]}"
iptables -I DOCKER-USER 1 -s "$SUBNET" -d 192.168.0.0/16 -j RETURN "${C[@]}"
iptables -I DOCKER-USER 1 -s "$SUBNET" -d 10.0.0.0/8     -j RETURN "${C[@]}"
iptables -I DOCKER-USER 1 -s "$SUBNET" -d 172.16.0.0/12  -j RETURN "${C[@]}"
iptables -I DOCKER-USER 1 -s "$SUBNET" -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN "${C[@]}"
echo "pms-egress applied for $SUBNET"
