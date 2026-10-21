# The 1.7.1 Blockheads server image (Majic Jungle's free Linux server, patched onto Ubuntu 22.04), pinned.
FROM theblockheads/server@sha256:cdd0d5fce9779729f5b4e0019cb8ab5c77646a22376022d630f0baf9671f3e0c

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip tini \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /portal/requirements.txt
RUN pip3 install --no-cache-dir -r /portal/requirements.txt

# The server keeps worlds in ~/GNUstep/.../saves, which the base image links to /saves; point that into /data.
RUN rm -rf /saves && ln -s /data/worlds /saves

COPY portal /portal/portal
COPY static /portal/static

WORKDIR /portal
ENV PORTAL_DATA=/data PORTAL_PORT=8080 PYTHONUNBUFFERED=1
VOLUME ["/data"]
# tini forwards docker stop's SIGTERM to the portal, which then /stops every server before exiting.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec python3 -m uvicorn portal.app:app --host 0.0.0.0 --port ${PORTAL_PORT} --timeout-graceful-shutdown 45"]
