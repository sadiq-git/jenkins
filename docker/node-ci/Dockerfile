FROM node:20-bookworm-slim
RUN apt-get update -y \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git ca-certificates python3 make g++ curl jq \
 && rm -rf /var/lib/apt/lists/*
