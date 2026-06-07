"""Topology API: group monitors into hosts and services based on tag conventions.

Merges data from:
- monitor_registry: provides tags, name, url, type (polled from Uptime Kuma API)
- monitor_status: provides latest heartbeat status (from webhooks)

Monitors without any heartbeat yet are shown with status=2 (pending).
"""
from app.db import get_pool
from .models import (
    STATUS_LABEL,
    TopologyHost,
    TopologyResponse,
    TopologyService,
    TopologySummary,
)


def _host_key(name: str) -> str:
    """Derive a host key from a monitor name.

    Lowercase, replace spaces and underscores with hyphens.
    """
    return name.lower().replace(" ", "-").replace("_", "-")


async def get_topology() -> TopologyResponse:
    """Build the topology view by merging monitor_registry with monitor_status.

    Host monitors are identified by having a "host" tag in the registry.
    Service monitors belong to a host when any of their tags matches the
    host's key (case-insensitive).

    Unmatched non-host monitors become orphans.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Fetch registry (has tags)
        registry_rows = await conn.fetch(
            "SELECT monitor_id, monitor_name, monitor_url, monitor_type, tags FROM monitor_registry WHERE active = true"
        )

        # Fetch latest heartbeat per monitor (has status)
        heartbeat_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (monitor_id)
                monitor_id, status, msg
            FROM monitor_status
            ORDER BY monitor_id, received_at DESC
            """
        )

    # Build monitor_id -> heartbeat mapping
    heartbeat_map: dict[str, dict] = {str(r["monitor_id"]): dict(r) for r in heartbeat_rows}

    # Build monitor list with merged data
    monitors: list[dict] = []
    for r in registry_rows:
        d = dict(r)
        mid = str(d["monitor_id"])
        hb = heartbeat_map.get(mid)
        d["tags"] = list(d["tags"]) if d["tags"] else []
        d["status"] = hb["status"] if hb else 2  # 2 = pending
        d["msg"] = hb["msg"] if hb else None
        monitors.append(d)

    # Partition into hosts and non-hosts
    hosts: list[dict] = []
    non_hosts: list[dict] = []
    for m in monitors:
        if "host" in m["tags"]:
            hosts.append(m)
        else:
            non_hosts.append(m)

    # Build host_key -> host row mapping
    host_map: dict[str, dict] = {}
    for h in hosts:
        key = _host_key(h["monitor_name"])
        host_map[key] = h

    # Assign services to hosts
    result_hosts: list[TopologyHost] = []
    matched_ids: set[str] = set()

    for h in hosts:
        key = _host_key(h["monitor_name"])
        matched_ids.add(h["monitor_id"])

        services: list[TopologyService] = []
        for r in non_hosts:
            if r["monitor_id"] in matched_ids:
                continue
            r_tags_lower = [t.lower() for t in r["tags"]]
            if key in r_tags_lower:
                services.append(
                    TopologyService(
                        monitor_id=r["monitor_id"],
                        name=r["monitor_name"],
                        url=r["monitor_url"],
                        status=r["status"],
                        status_label=STATUS_LABEL.get(r["status"], "UNKNOWN"),
                        msg=r["msg"],
                        tags=r["tags"],
                    )
                )
                matched_ids.add(r["monitor_id"])

        up_count = sum(1 for s in services if s.status == 1)
        result_hosts.append(
            TopologyHost(
                name=h["monitor_name"],
                host_key=key,
                monitor_id=h["monitor_id"],
                status=h["status"],
                status_label=STATUS_LABEL.get(h["status"], "UNKNOWN"),
                msg=h["msg"],
                total_services=len(services),
                up_count=up_count,
                services=services,
            )
        )

    # Orphans: all non-host rows not matched to any host
    orphans: list[TopologyService] = []
    for r in non_hosts:
        if r["monitor_id"] not in matched_ids:
            orphans.append(
                TopologyService(
                    monitor_id=r["monitor_id"],
                    name=r["monitor_name"],
                    url=r["monitor_url"],
                    status=r["status"],
                    status_label=STATUS_LABEL.get(r["status"], "UNKNOWN"),
                    msg=r["msg"],
                    tags=r["tags"],
                )
            )

    summary = TopologySummary(
        total_hosts=len(result_hosts),
        hosts_up=sum(1 for h in result_hosts if h.status == 1),
        total_services=sum(h.total_services for h in result_hosts),
        services_up=sum(h.up_count for h in result_hosts),
        orphans=len(orphans),
    )

    return TopologyResponse(hosts=result_hosts, orphans=orphans, summary=summary)
