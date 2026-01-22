#!/bin/bash

function get_distro_type() {
    if [ -f /etc/os-release ]; then
        # Extract ID from /etc/os-release (e.g., "ubuntu", "centos", etc.)
        . /etc/os-release
        DISTRO_ID=$ID
    else
        echo "Unable to determine Linux distribution type."
        exit 1
    fi
}

get_distro_type

# Call the corresponding script based on the Linux distribution type
case "$DISTRO_ID" in
    centos)
        echo "Detected CentOS. Running centos installation script..."
        ./install_centos.sh
        ;;
    alma)
        echo "Detected AlmaLinux. Running almalinux installation script..."
        ./install_rocky.sh
        ;;
    almalinux)
        echo "Detected AlmaLinux. Running almalinux installation script..."
        ./install_rocky.sh
        ;;
    rocky)
        echo "Detected Rocky Linux. Running rockylinux installation script..."
        ./install_rocky.sh
        ;;
#    ubuntu)
#        echo "Detected Ubuntu. Running ubuntu installation script..."
#        ./install_ubuntu.sh
#        ;;
#    debian)
#        echo "Detected Debian. Running debian installation script..."
#        ./install_debian.sh
#        ;;
#    redhat)
#        echo "Detected Red Hat Enterprise Linux. Running redhat installation script..."
#        # ./redhat_script.sh
#        ;;
    *)
        echo "Distribution $DISTRO_ID is not supported yet. Exiting ..."
        ;;
esac
