#!/bin/bash
sudo apt-get install -y ugrep 2>/dev/null && exit 0
UGREP_VER="7.3.2"
wget -q "https://github.com/Genivia/ugrep/releases/download/v${UGREP_VER}/ugrep_${UGREP_VER}_amd64.deb" -O /tmp/ugrep.deb
sudo dpkg -i /tmp/ugrep.deb && rm /tmp/ugrep.deb
