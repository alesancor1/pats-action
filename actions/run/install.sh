#!/usr/bin/env bash
# installs the pats snap from $PATS_CHANNEL and connects it to the engines the
# config's sandboxes use. the snap is strictly confined: it reaches each engine
# only through its plug, which needs connecting by hand.
# - docker: always connected (the runner has it).
# - lxd: only when a sandbox (agent or step) has `driver: lxd`, as
#   `pats list sandboxes` resolves it. runs from the dir holding pats.yaml.
set -euo pipefail

: "${PATS_CHANNEL:?}"

sudo snap install pats --channel="$PATS_CHANNEL"
sudo snap connect pats:docker
echo /snap/bin >> "$GITHUB_PATH"
/snap/bin/pats --version

# a config pats can't load lists nothing; `pats init` reports the real error.
drivers="$(/snap/bin/pats list sandboxes 2>/dev/null | awk 'NR > 1 { print $3 }' | sort -u || true)"
echo "sandbox drivers: ${drivers:-none}"
if ! grep -qx lxd <<< "$drivers"; then
  exit 0
fi

# lxd, as canonical/setup-lxd does it: socket for the adm group (the runner
# user is in it), default storage and bridge.
if snap list lxd > /dev/null 2>&1; then
  sudo snap refresh lxd
else
  sudo snap install lxd
fi
sudo snap set lxd daemon.group=adm
sudo lxd waitready
sudo lxd init --auto

# docker's FORWARD policy drops traffic on bridges it wasn't told about: let
# pats' per-sandbox bridges (patsbr*) and its shared uplink (patsup) past.
for br in 'patsbr+' patsup; do
  sudo iptables -I DOCKER-USER -i "$br" -j ACCEPT
  sudo iptables -I DOCKER-USER -o "$br" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
done
sudo snap connect pats:lxd lxd:lxd
