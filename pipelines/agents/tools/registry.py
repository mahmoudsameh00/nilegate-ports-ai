"""The Stage 1 tools in one list (Agents plan §5a): what a graph node or the supervisor binds, and what the RBAC
matrix of `Tools_check.py` iterates over. Each entry: the LangChain tool (the model sees its args schema only) and
the plain function `f(user, **args)` behind it."""
from pipelines.agents.tools import (audit, documents, eta, external, finance, fleet, products, routes, tariff, vessels,
                                    voyages, watch, weather)

STAGE1 = {
    "finance_kpi": (finance.finance_kpi_tool, finance.finance_kpi),
    "invoice_audit": (audit.invoice_audit_tool, audit.invoice_audit),
    "compute_toll": (tariff.compute_toll_tool, tariff.compute_toll),
    "search_documents": (documents.search_documents_tool, documents.search_documents),
    "suez_transits": (external.suez_transits_tool, external.suez_transits),
    "web_search": (external.web_search_tool, external.web_search),
}
STAGE1_TOOLS = [t for t, _ in STAGE1.values()]

# The Stage 2 (Operations Desk) tools, Agents plan §6a; filled one step at a time (S2 sea_route, S5 vessel_params,
# S6 voyage_status, S7 marine_weather). The Stage 2 graphs bind these plus the Stage 1 tools they reuse.
STAGE2 = {
    "sea_route": (routes.sea_route_tool, routes.sea_route),
    "vessel_params": (vessels.vessel_params_tool, vessels.vessel_params),
    "voyage_status": (voyages.voyage_status_tool, voyages.voyage_status),
    "marine_weather": (weather.marine_weather_tool, weather.marine_weather),
}
STAGE2_TOOLS = [t for t, _ in STAGE2.values()]

# The product tools of the supervisor (Agents plan Phase 12, §6d S2): the voyage watch's ETA rule, its saved runs and
# the customer bridge; `route_advice` (the ADR-057 graph as a tool, P12-2) is built per agent with its roles by
# `products.make_route_advice_tool`, so its entry here is the plain function `f(user, roles, **args)`.
PRODUCTS = {
    "voyage_eta": (eta.voyage_eta_tool, eta.voyage_eta),
    "watch_alerts": (watch.watch_alerts_tool, watch.watch_alerts),
    "fleet_customers": (fleet.fleet_customers_tool, fleet.fleet_customers),
}
ROUTE_ADVICE = products.run_route_advice


def supervisor_tools(roles, saver=None, pool=None) -> list:
    """Every tool the supervisor may bind (S3's code router picks a subset per question): Stage 1 + Stage 2 + the
    products + `route_advice` bound to `roles`; one name each."""
    tools = (STAGE1_TOOLS + STAGE2_TOOLS + [t for t, _ in PRODUCTS.values()]
             + [products.make_route_advice_tool(roles, saver, pool)])
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), names
    return tools
