"""The Stage 1 tools in one list (Agents plan §5a): what a graph node or the supervisor binds, and what the RBAC
matrix of `Tools_check.py` iterates over. Each entry: the LangChain tool (the model sees its args schema only) and
the plain function `f(user, **args)` behind it."""
from pipelines.agents.tools import audit, documents, external, finance, tariff

STAGE1 = {
    "finance_kpi": (finance.finance_kpi_tool, finance.finance_kpi),
    "invoice_audit": (audit.invoice_audit_tool, audit.invoice_audit),
    "compute_toll": (tariff.compute_toll_tool, tariff.compute_toll),
    "search_documents": (documents.search_documents_tool, documents.search_documents),
    "suez_transits": (external.suez_transits_tool, external.suez_transits),
    "web_search": (external.web_search_tool, external.web_search),
}
STAGE1_TOOLS = [t for t, _ in STAGE1.values()]
