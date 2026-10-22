# Blockheads Server Portal: the portal plus Majic Jungle's free 1.7.1 Linux server, set up here from the original
# archive (archive.org, BHSv171) so the build depends only on Ubuntu and that archive.
#
# The server is an Objective-C (GNUstep) program built against older libraries; Ubuntu 22.04 packages the
# GNUstep base 1.28 it runs on, and patchelf points the binary at the 22.04 library versions. The result is
# checked against the exact binary the portal was tested with.
FROM ubuntu:22.04@sha256:0a9887931b0e38af2e3487ed39e29436b0535c4f3f52e57745baaf79d1898956

ARG SERVER_URL=https://archive.org/download/BHSv171/blockheads_server171.tar.gz
ARG SERVER_ARCHIVE_SHA256=166e09fafcfbcf94947faeb849db804003050d3544118b3a3e1058d6763c9148
ARG SERVER_PATCHED_SHA256=dc20e600a3c9ef2bf4e641d03506352ba9a1f9b399f8d8101e80bbdb63f9d717

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates wget libgnustep-base1.28 libdispatch0 patchelf python3 python3-pip tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN wget -q -O server.tar.gz "$SERVER_URL" \
 && echo "$SERVER_ARCHIVE_SHA256  server.tar.gz" | sha256sum -c - \
 && tar xzf server.tar.gz && rm server.tar.gz \
 && chmod 755 blockheads_server171 \
 && patchelf --replace-needed libgnustep-base.so.1.24 libgnustep-base.so.1.28 blockheads_server171 \
 && patchelf --replace-needed libobjc.so.4.6 libobjc.so.4 blockheads_server171 \
 && patchelf --replace-needed libgnutls.so.26 libgnutls.so.30 blockheads_server171 \
 && patchelf --replace-needed libgcrypt.so.11 libgcrypt.so.20 blockheads_server171 \
 && patchelf --replace-needed libffi.so.6 libffi.so.8 blockheads_server171 \
 && patchelf --replace-needed libicui18n.so.48 libicui18n.so.70 blockheads_server171 \
 && patchelf --replace-needed libicuuc.so.48 libicuuc.so.70 blockheads_server171 \
 && patchelf --replace-needed libicudata.so.48 libicudata.so.70 blockheads_server171 \
 && patchelf --replace-needed libdispatch.so libdispatch.so.0 blockheads_server171 \
 && echo "$SERVER_PATCHED_SHA256  blockheads_server171" | sha256sum -c -

# The server keeps worlds in ~/GNUstep/Library/ApplicationSupport/TheBlockheads/saves; that is the portal's
# /data/worlds.
RUN mkdir -p /root/GNUstep/Library/ApplicationSupport/TheBlockheads \
 && ln -s /data/worlds /root/GNUstep/Library/ApplicationSupport/TheBlockheads/saves

COPY requirements.txt /portal/requirements.txt
RUN pip3 install --no-cache-dir -r /portal/requirements.txt

COPY portal /portal/portal
COPY static /portal/static

WORKDIR /portal
ENV PORTAL_DATA=/data PORTAL_PORT=8080 PYTHONUNBUFFERED=1
VOLUME ["/data"]
# tini forwards docker stop's SIGTERM to the portal, which then /stops every server before exiting.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec python3 -m uvicorn portal.app:app --host 0.0.0.0 --port ${PORTAL_PORT} --timeout-graceful-shutdown 45"]
