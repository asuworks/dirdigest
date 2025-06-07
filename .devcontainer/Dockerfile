# =========================================================================
# BUILDER STAGE: Install build tools, ASDF, and all the language versions
# =========================================================================
FROM ubuntu:22.04 AS builder

# 1. Install build-time dependencies and create the 'coder' user
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates \
    git unzip curl wget \
    build-essential\
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncursesw5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libxml2-dev \
    libxmlsec1-dev \
    llvm \
    make \
    tk-dev \
    wget \
    xz-utils \
    zlib1g-dev \
    fish bc

# Clean up APT cache
RUN rm -rf /var/lib/apt/lists/*

# Create the coder user with a home directory and add to sudo group
RUN useradd -m -s /bin/bash -G sudo coder && \
    # Give the sudo group passwordless sudo privileges
    echo "%sudo ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers


# ---- 1. install asdf ----
ARG ASDF_VERSION=v0.18.0
ARG ASDF_ARCH=linux-amd64
ENV ASDF_DIR="/home/coder/.asdf"

RUN mkdir -p ${ASDF_DIR}/bin && \
    chown coder:coder ${ASDF_DIR} &&\
    chown coder:coder ${ASDF_DIR}/bin

RUN curl -fsSL https://github.com/asdf-vm/asdf/releases/download/${ASDF_VERSION}/asdf-${ASDF_VERSION}-${ASDF_ARCH}.tar.gz \
    -o /tmp/asdf.tar.gz \
    && tar -xzf /tmp/asdf.tar.gz -C ${ASDF_DIR}/bin \
    && rm /tmp/asdf.tar.gz

RUN chmod +x ${ASDF_DIR}/bin/asdf

# 2. Switch to the coder user for user-specific installations
USER coder
WORKDIR /home/coder
RUN ls -la /home/coder

COPY --chown=coder:coder config.fish /home/coder/.config/fish/config.fish

ENV PATH="${ASDF_DIR}/bin:${PATH}"
ENV PATH="${ASDF_DIR}/shims:${PATH}"

RUN ls -la /home/coder
RUN ls -la /home/coder/.asdf

RUN asdf plugin add python && \
    asdf plugin add nodejs && \
    asdf plugin add uv https://github.com/asdf-community/asdf-uv.git && \
    asdf plugin add zellij https://github.com/chessmango/asdf-zellij.git

# 4. Install language versions with ASDF and reshim
# This is the longest step. It compiles/downloads Python, Node, etc.
RUN asdf install python 3.12.7
RUN asdf set --home python 3.12.7

RUN asdf install nodejs lts
RUN asdf set --home nodejs lts

RUN asdf install uv latest
RUN asdf set --home uv latest

RUN asdf install zellij latest
RUN asdf set --home zellij latest

RUN asdf reshim

# =========================================================================
# FINAL STAGE: Create the clean, small runtime image
# =========================================================================
FROM ubuntu:22.04

# 1. Install only RUNTIME dependencies
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates \
    git unzip curl wget \
    build-essential\
    # libffi-dev libssl-dev zlib1g-dev \
    # libbz2-dev libreadline-dev libsqlite3-dev llvm libncurses5-dev \
    # libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
    # liblzma-dev python3-pip python3-minimal python3-six python3-dev \
    fish bc

# Clean up APT cache
RUN rm -rf /var/lib/apt/lists/*

# Create the coder user with a home directory and add to sudo group
RUN useradd -m -s /bin/bash -G sudo coder && \
    # Give the sudo group passwordless sudo privileges
    echo "%sudo ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# 2. Copy the ASDF installation and user's home directory from the builder stage
COPY --from=builder --chown=coder:coder /home/coder/.config/fish/ /home/coder/.config/fish/
COPY --from=builder --chown=coder:coder /home/coder/.asdf /home/coder/.asdf
COPY --from=builder --chown=coder:coder /home/coder/.tool-versions /home/coder/.tool-versions

# 3. Copy the local fish config into the image
# COPY --chown=coder:coder config.fish /home/coder/.config/fish/config.fish

# 4. Set environment for the 'coder' user
USER coder
WORKDIR /home/coder
ENV ASDF_DIR="/home/coder/.asdf"
# Add ASDF shims to the front of the PATH
ENV PATH="${ASDF_DIR}/shims:${ASDF_DIR}/bin:${PATH}"

RUN asdf reshim

# 6. Set the default command to start a login fish shell
# The -l flag makes it a login shell, which will properly source profile scripts
SHELL ["/usr/bin/fish", "-l", "-c"]
CMD ["fish"]
