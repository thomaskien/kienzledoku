#!/usr/bin/env bash
set -euo pipefail

# install-kienzlefon-ai-host-ubuntu-v1.2.sh
# Ubuntu 24.04 LTS x86_64 + NVIDIA
#
# Design:
# - NVIDIA-Treiber aus Ubuntu
# - CUDA-Toolkit aus dem offiziellen NVIDIA-CUDA-Repository
# - NVIDIA-CUDA-Repository auf APT-Prioritaet 400, damit Ubuntu-Treiber
#   mit Prioritaet 500 nicht ersetzt werden
# - gezielt CUDA Toolkit 13.0, NICHT das unversionierte Meta-Paket cuda-toolkit

if [[ "${EUID}" -eq 0 ]]; then
    echo "Bitte als normaler Benutzer starten; sudo wird bei Bedarf verwendet."
    exit 1
fi

source /etc/os-release

if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
    echo "FEHLER: Vorgesehen fuer Ubuntu 24.04 LTS."
    echo "Erkannt: ${PRETTY_NAME:-unbekannt}"
    exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "FEHLER: Erwartet x86_64, erkannt: $(uname -m)"
    exit 1
fi

sudo -v

CUDA_PIN="/etc/apt/preferences.d/cuda-repository-pin-600"

lower_cuda_repo_priority() {
    if [[ -f "${CUDA_PIN}" ]]; then
        sudo sed -i             -e '/Pin: release l=NVIDIA CUDA/{n;s/Pin-Priority: 600/Pin-Priority: 400/;}'             "${CUDA_PIN}"
    fi
}

# Falls CUDA-Repo aus einem frueheren Lauf schon vorhanden ist:
# Prioritaet sofort senken, bevor APT Pakete auswaehlt.
lower_cuda_repo_priority

echo "=== 1/6 Paketlisten + Basiswerkzeuge ==="
sudo apt-get update

sudo apt-get install -y     "linux-headers-$(uname -r)"     linux-firmware     amd64-microcode     ubuntu-drivers-common     build-essential     cmake     ninja-build     git     curl     wget     pkg-config     ca-certificates     gnupg     libssl-dev     libcurl4-openssl-dev     ffmpeg     python3     python3-venv     python3-pip     openssh-server     ethtool     lm-sensors     nvtop     stress-ng     pciutils     usbutils     smartmontools

echo "=== 2/6 SSH ==="
sudo systemctl enable --now ssh

if command -v ufw >/dev/null 2>&1 &&
   sudo ufw status 2>/dev/null | grep -q '^Status: active'; then
    sudo ufw allow OpenSSH
fi

echo "=== 3/6 Ubuntu-NVIDIA-Treiber ==="
DRIVER_WAS_INSTALLED=0

if nvidia-smi >/dev/null 2>&1; then
    echo "Funktionierender NVIDIA-Treiber bereits vorhanden:"
    nvidia-smi --query-gpu=name,driver_version,memory.total,power.limit         --format=csv,noheader
else
    echo "Installiere den von Ubuntu empfohlenen NVIDIA-Treiber ..."
    sudo ubuntu-drivers install
    DRIVER_WAS_INSTALLED=1
fi

echo "=== 4/6 Offizielles NVIDIA-CUDA-Repository ==="

if ! dpkg-query -W -f='${Status}\n' cuda-keyring 2>/dev/null         | grep -q 'install ok installed'; then
    TMP_KEYRING="/tmp/cuda-keyring_1.1-1_all.deb"
    wget -q       https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb       -O "${TMP_KEYRING}"
    sudo dpkg -i "${TMP_KEYRING}"
    rm -f "${TMP_KEYRING}"
fi

lower_cuda_repo_priority

if [[ ! -f "${CUDA_PIN}" ]]; then
    sudo tee /etc/apt/preferences.d/kienzlefon-cuda-repository-pin >/dev/null <<'EOF'
Package: *
Pin: release l=NVIDIA CUDA
Pin-Priority: 400
EOF
fi

sudo apt-get update

echo "=== 5/6 CUDA Toolkit 13.0 ==="
sudo apt-get install -y cuda-toolkit-13-0

sudo tee /etc/profile.d/kienzlefon-cuda.sh >/dev/null <<'EOF'
export PATH=/usr/local/cuda-13.0/bin${PATH:+:${PATH}}
export LD_LIBRARY_PATH=/usr/local/cuda-13.0/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
EOF
sudo chmod 0644 /etc/profile.d/kienzlefon-cuda.sh

export PATH="/usr/local/cuda-13.0/bin${PATH:+:${PATH}}"
export LD_LIBRARY_PATH="/usr/local/cuda-13.0/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "=== 6/6 Kontrolle ==="

echo "--- SSH ---"
systemctl is-enabled ssh
systemctl is-active ssh

echo "--- NVIDIA ---"
if nvidia-smi >/dev/null 2>&1; then
    nvidia-smi
else
    echo "Treiber installiert, aber vor Neustart noch nicht aktiv."
fi

echo "--- CUDA ---"
nvcc --version

echo "--- APT-Prioritaet NVIDIA CUDA Repository ---"
grep -A2 -B1 -F 'Pin: release l=NVIDIA CUDA'     /etc/apt/preferences.d/* 2>/dev/null || true

echo "--- libnvidia-gl Kandidat ---"
apt-cache policy libnvidia-gl-580 2>/dev/null | sed -n '1,12p' || true

echo
echo "FERTIG."
echo "Vorhandenes CUDA 13.3 wird absichtlich NICHT automatisch entfernt."
echo "Das bereinigen wir separat, damit laufende AI-Dienste nicht gestoert werden."

if [[ "${DRIVER_WAS_INSTALLED}" -eq 1 ]]; then
    echo "NVIDIA-Treiber wurde neu installiert -> bitte neu starten: sudo reboot"
fi
