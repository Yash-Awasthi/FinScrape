# Ports

The workstation runs more than FinScrape. Another Docker stack (Nexus) owns five ports,
and a `docker compose up` that quietly takes one of them breaks that stack instead of
this one — a failure that looks like "the other project is broken" an hour later.

| Port | Owner | Used for |
|---|---|---|
| **8000** | Nexus | API |
| **5432** | Nexus | Postgres |
| **6379** | Nexus | Redis |
| **3000** | Nexus | UI dev server |
| **4173** | Nexus | preview server |

## What FinScrape publishes

| Port | Service | Override |
|---|---|---|
| **8010** | API (`/api`, `/docs`, `/health`) | `WORLDFIN_API_HOST_PORT` |
| **5433** | Postgres | `WORLDFIN_PG_HOST_PORT` |
| **6380** | Redis | `WORLDFIN_REDIS_HOST_PORT` |
| **8080** | static web build (`web` profile) | edit compose — no variable yet |

Every published port is a `${VAR:-default}` in `docker-compose.yml`, so it can be moved
without editing the file. Moving one onto a Nexus port is the failure this document
exists to prevent.

## The gate

`make ports-check` (a prerequisite of `make up`) parses `docker-compose.yml`, extracts
every published **host** port — short form and `published:` long form — and fails when:

- a port is in the Nexus set above;
- the same host port is published twice;
- **no** ports are found at all, because a compose rewrite that changes syntax must
  fail loudly rather than report a vacuous pass.

```console
$ make ports-check
ports-check: docker-compose.yml publishes no reserved port (4 checked)
```

`tests/test_ports.py` pins the reserved set to this document, so changing one without
the other fails.
