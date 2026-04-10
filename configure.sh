#!/bin/bash

# Ensure the DEBIAN_FRONTEND environment variable is set for apt-get calls
APT_GET="env DEBIAN_FRONTEND=noninteractive $(command -v apt-get)"

check_version(){  
  UBUNTU_VERSION=$(lsb_release -r)
  case "$UBUNTU_VERSION" in
    *"24.04"*)
      echo "Ubuntu: $UBUNTU_VERSION, good!"
      ;;
    *)
      echo "You are not on a supported Ubuntu version (detected: $UBUNTU_VERSION)"
      echo "It might be possible to run ODM on a newer version of Ubuntu, however, you cannot rely on this script."
      exit 1
      ;;
  esac
}

if [[ $2 =~ ^[0-9]+$ ]] ; then
    processes=$2
else
    processes=$(nproc)
fi

ensure_prereqs() {
    export DEBIAN_FRONTEND=noninteractive

    if ! command -v sudo &> /dev/null; then
        echo "Installing sudo"
        apt-get update
        apt-get install -y --no-install-recommends sudo
    else
        sudo apt-get update
    fi

    if ! command -v lsb_release &> /dev/null; then
        echo "Installing lsb_release"
        sudo apt-get install -y --no-install-recommends lsb-release
    fi

    if ! command -v pkg-config &> /dev/null; then
        echo "Installing pkg-config"
        sudo apt-get install -y --no-install-recommends pkg-config
    fi

    echo "Installing tzdata"
    sudo apt-get install -y tzdata

    # UBUNTU_VERSION=$(lsb_release -r)
    # if [[ "$UBUNTU_VERSION" == *"24.04"* ]]; then
    #     echo "Enabling PPA for Ubuntu GIS"
    #     sudo apt-get install -y --no-install-recommends software-properties-common
    #     sudo add-apt-repository ppa:ubuntugis/ppa
    #     sudo apt-get update
    # fi

    echo "Installing Python PIP"
    sudo apt-get install -y --no-install-recommends \
        python3-pip \
        python3-setuptools
    sudo pip3 install -U pip
}

installruntimedeps() {
    echo "Installing runtime dependencies"
    ensure_prereqs
    check_version

    for i in {1..20}; do
        sudo apt-get install -y --no-install-recommends \
            gdal-bin \
            libgdal34t64 \
            libgeotiff5 \
            libjsoncpp25 \
            libspqr4 \
            libssl3t64 \
            libusb-1.0-0 \
            proj-data \
            procps \
            python3 \
            python3-gdal \
            python3-pkg-resources \
            python3-requests \
            python3-setuptools \
            libavcodec60 \
            libavformat60 \
            libflann1.9 \
            libgtk2.0-0 \
            libjpeg-turbo8 \
            libopenjpip7 \
            liblapack3 \
            libpng16-16 \
            libproj25 \
            libswscale7 \
            libtbb12 \
            libtiff6 \
            libwebpdemux2 \
            libxext6 \
            libamd3 \
            libcamd3 \
            libccolamd3 \
            libcholmod5 \
            libcolamd3 \
            libcxsparse4 \
            libgoogle-glog0v6t64 \
            libsuitesparseconfig7 \
            libboost-program-options1.83.0 \
            libboost-iostreams1.83.0 \
            libboost-serialization1.83.0 \
            libboost-system1.83.0 \
            libgoogle-perftools4t64
        break
        echo "Attempt $i failed, sleeping..."
        sleep 30
    done
}

installbuilddeps(){
    echo "Installing build dependencies"

    for i in {1..20}; do
        sudo apt-get install -y --no-install-recommends \
            build-essential \
            cmake \
            gdal-bin \
            gfortran \
            git \
            libgdal-dev \
            libgeotiff-dev \
            libjsoncpp-dev \
            libssl-dev \
            libusb-1.0-0-dev \
            ninja-build \
            pkg-config \
            python3-dev \
            python3-gdal \
            python3-pip \
            python3-setuptools \
            python3-wheel \
            rsync \
            swig3.0 \
            libavcodec-dev \
            libavformat-dev \
            libeigen3-dev \
            libflann-dev \
            libgtk2.0-dev \
            libjpeg-dev \
            liblapack-dev \
            libopenjpip7 \
            libpng-dev \
            libproj-dev \
            libswscale-dev \
            libtbb-dev \
            libtiff-dev \
            libxext-dev \
            proj-bin \
            libgoogle-glog-dev \
            libsuitesparse-dev \
            libcgal-dev \
            libboost-program-options-dev \
            libboost-iostreams-dev \
            libboost-serialization-dev \
            libboost-system-dev \
            libgoogle-perftools-dev
        break
        echo "Attempt $i failed, sleeping..."
        sleep 30
    done
}

installreqs() {
    cd /code
    
    ## Set up library paths
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$RUNPATH/SuperBuild/install/lib

	## Before installing
    echo "Updating"
    ensure_prereqs
    check_version
    
    ensure_prereqs
    check_version
    installbuilddeps
    
    set -e

    # edt requires numpy to build
    pip install --ignore-installed numpy==2.3.2 --break-system-packages
    pip install --ignore-installed -r requirements.txt --break-system-packages

    set +e
}

install() {
    installreqs

    if [ ! -z "$PORTABLE_INSTALL" ]; then
        echo "Replacing g++ and gcc with our scripts for portability..."
        if [ ! -e /usr/bin/gcc_real ]; then
            sudo mv -v /usr/bin/gcc /usr/bin/gcc_real
            sudo cp -v ./docker/gcc /usr/bin/gcc
        fi
        if [ ! -e /usr/bin/g++_real ]; then
            sudo mv -v /usr/bin/g++ /usr/bin/g++_real
            sudo cp -v ./docker/g++ /usr/bin/g++
        fi
    fi

    set -eo pipefail
    
    echo "Compiling SuperBuild"
    cd ${RUNPATH}/SuperBuild
    mkdir -p build && cd build
    cmake .. && make -j$(nproc)

    echo "Configuration Finished"
}
 
uninstall() {
    check_version

    echo "Removing SuperBuild and build directories"
    cd ${RUNPATH}/SuperBuild
    rm -rfv build src download install
    cd ../
    rm -rfv build
}

reinstall() {
    check_version

    echo "Reinstalling"
    uninstall
    install
}

clean() {
    rm -rf \
        ${RUNPATH}/SuperBuild/build \
        ${RUNPATH}/SuperBuild/download \
        ${RUNPATH}/SuperBuild/src \
        ${RUNPATH}/SuperBuild/install/bin/opensfm/.git \
        ${RUNPATH}/SuperBuild/install/bin/opensfm/opensfm/src/third_party/pybind11/.git

    # find in /code and delete static libraries and intermediate object files
    find ${RUNPATH} -type f -name "*.a" -delete -or -type f -name "*.o" -delete
}

usage() {
    echo "Usage:"
    echo "bash configure.sh <install|update|uninstall|installreqs|help> [nproc]"
    echo "Commands:"
    echo "  install"
    echo "  installruntimedeps"
    echo "  reinstall"
    echo "  uninstall"
    echo "  installreqs"
    echo "  clean"
    echo "  help"
}

if [[ $1 =~ ^(install|reinstall|uninstall|installreqs|installpython|clean)$ ]]; then
    RUNPATH="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    "$1"
else
    echo "Invalid instructions." >&2
    usage
    exit 1
fi
