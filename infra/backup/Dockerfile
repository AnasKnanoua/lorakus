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

# gosu sert au demarrage du serveur PostgreSQL, jamais a la sauvegarde :
# on le retire pour reduire la surface d'attaque (il portait une faille Go connue).
RUN rm -f /usr/local/bin/gosu

COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
COPY --chmod=0755 lorakus-backup.sh /usr/local/bin/lorakus-backup

# Dossier des metriques, partage avec node_exporter (qui ne peut que le lire).
RUN mkdir -p /metrics && chown postgres:postgres /metrics

# Systeme de fichiers en lecture seule : seuls /tmp (en memoire) et /metrics sont inscriptibles.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    BACKUP_METRICS_DIR=/metrics

USER postgres
ENTRYPOINT ["/usr/local/bin/lorakus-backup"]
CMD ["backup"]
