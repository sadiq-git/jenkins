FROM node:20-bookworm-slim
RUN apt-get update -y \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git ca-certificates python3 python3-pip make g++ curl jq \
 && rm -rf /var/lib/apt/lists/*
