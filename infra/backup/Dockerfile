# syntax=docker/dockerfile:1
# Image de sauvegarde : pg_dump (meme version que la base), age et rclone.
# Base = l'image PostgreSQL deja epinglee du projet : pg_dump est garanti compatible.

ARG PG_IMAGE=pgvector/pgvector:pg18@sha256:c29f30688a9ad961691bdf0ec1650717cc132a5814619d80f80463d6e4c42e47
ARG RCLONE_IMAGE=rclone/rclone:1.75.2@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5

FROM ${RCLONE_IMAGE} AS rclone

FROM ${PG_IMAGE}

RUN apt-get update \
 && apt-get install -y --no-install-recommends age ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
COPY --chmod=0755 lorakus-backup.sh /usr/local/bin/lorakus-backup

# Systeme de fichiers en lecture seule : seul /tmp (en memoire) est inscriptible.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

USER postgres
ENTRYPOINT ["/usr/local/bin/lorakus-backup"]
CMD ["backup"]
