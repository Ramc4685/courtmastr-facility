#!/bin/sh
# Runs once, when the data volume is first initialised. Roles per docs/architecture/overview.md 3.4.
# btree_gist, citext and pg_trgm ship with the image and are trusted, so the baseline migration creates them.
set -eu
psql -v ON_ERROR_STOP=1 -U postgres <<EOSQL
CREATE ROLE fh_owner      LOGIN PASSWORD '${FH_DB_OWNER_PASSWORD}'    NOSUPERUSER NOBYPASSRLS;
CREATE ROLE fh_app        LOGIN PASSWORD '${FH_DB_APP_PASSWORD}'      NOSUPERUSER NOBYPASSRLS;
CREATE ROLE fh_platform   LOGIN PASSWORD '${FH_DB_PLATFORM_PASSWORD}' NOSUPERUSER BYPASSRLS;
CREATE ROLE fh_due_reader NOLOGIN BYPASSRLS;
CREATE DATABASE facilityhub      OWNER fh_owner;
CREATE DATABASE facilityhub_test OWNER fh_owner;
EOSQL
