# =========================================================================
# BUILDER STAGE: Install build tools, ASDF, and all the language versions
# =========================================================================
FROM ubuntu:22.04 AS builder

# 1. Install build-time dependencies and create the 'coder' user
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libxml2-dev \
    libxmlsec1-dev \
    llvm \
    python3 \
    tk-dev \
    unzip \
    xz-utils \
    zlib1g-dev && \
    # Create the coder user with a home directory and add to sudo group
    useradd -m -s /bin/bash -G sudo coder && \
    # Give the sudo group passwordless sudo privileges
    echo "%sudo ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    # Clean up APT cache
    rm -rf /var/lib/apt/lists/*

# 2. Switch to the coder user for user-specific installations
USER coder
WORKDIR /home/coder

# 3. Install ASDF and its plugins as the 'coder' user
ENV ASDF_DIR="/home/coder/.asdf"
ENV ASDF_DATA_DIR="/home/coder/.asdf"
RUN git clone https://github.com/asdf-vm/asdf.git ${ASDF_DIR} --branch v0.14.0 && \
    . ${ASDF_DIR}/asdf.sh && \
    asdf plugin add python && \
    asdf plugin add nodejs && \
    asdf plugin add uv https://github.com/asdf-community/asdf-uv.git && \
    asdf plugin add zellij https://github.com/chessmango/asdf-zellij.git

# 4. Install language versions with ASDF and reshim
# This is the longest step. It compiles/downloads Python, Node, etc.
RUN . ${ASDF_DIR}/asdf.sh && \
    asdf install python 3.12.7 && asdf global python 3.12.7 && \
    asdf install nodejs lts && asdf global nodejs lts && \
    asdf install uv latest && asdf global uv latest && \
    asdf install zellij latest && asdf global zellij latest && \
    asdf reshim

# =========================================================================
# FINAL STAGE: Create the clean, small runtime image
# =========================================================================
FROM ubuntu:22.04

# 1. Install only RUNTIME dependencies
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    acl \
    ca-certificates \
    fish \
    git \
    curl \
    wget \
    # Runtime libs for python etc.
    libssl-dev \
    libffi-dev \
    # Add any other essential runtime packages here
    && \
    # Create the coder user. It's important that UID/GID match if possible,
    # but for a simple case, just recreating it is fine.
    useradd -m -s /usr/bin/fish -G sudo coder && \
    echo "%sudo ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    rm -rf /var/lib/apt/lists/*

# 2. Copy the ASDF installation and user's home directory from the builder stage
COPY --from=builder --chown=coder:coder /home/coder/.asdf /home/coder/.asdf
COPY --from=builder --chown=coder:coder /home/coder/.tool-versions /home/coder/.tool-versions

# 3. Copy the local fish config into the image
COPY --chown=coder:coder config.fish /home/coder/.config/fish/config.fish

# 4. Set environment for the 'coder' user
USER coder
WORKDIR /home/coder
ENV ASDF_DIR="/home/coder/.asdf"
ENV ASDF_DATA_DIR="/home/coder/.asdf"
# Add ASDF shims to the front of the PATH
ENV PATH="${ASDF_DATA_DIR}/shims:${ASDF_DATA_DIR}/bin:${PATH}"

# 5. Set the default command to start a fish shell
CMD ["/usr/bin/fish", "-l"]
