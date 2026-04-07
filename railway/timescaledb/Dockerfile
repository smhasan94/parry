# TimescaleDB image suitable for Railway deployment.
#
# Railway's stock Postgres template does not include the TimescaleDB extension,
# which Parry's agent_events hypertable depends on. This image wraps the
# upstream timescale/timescaledb image so Railway can build and run it as a
# standard service.
#
# Required Railway env vars (set in the service settings):
#   POSTGRES_USER       — defaults to parry
#   POSTGRES_PASSWORD   — REQUIRED
#   POSTGRES_DB         — defaults to parry
#
# Railway will automatically attach a persistent volume mounted at
# /var/lib/postgresql/data when you add a Volume to this service.

FROM timescale/timescaledb:latest-pg16

# Railway exposes PORT but Postgres always listens on 5432.
# Other services on the same Railway project reach this one via its private
# network address (e.g. timescaledb.railway.internal:5432).
EXPOSE 5432
