"""FRIA (Fundamental Rights Impact Assessment) service.

Handles draft creation with auto-populated fields, user-editable field
merging, and approval workflow. PDF rendering delegated to
compliance.fria_html_template.
"""

import copy
import uuid
from datetime import date, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.fria_template import FRIA_TEMPLATE
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import (
    AISystem,
    AISystemSupplier,
    FRIADocument,
    Org,
    Policy,
)

log = structlog.get_logger()


async def generate_fria(
    db: AsyncSession,
    org_id: uuid.UUID,
    system_id: uuid.UUID,
    generated_by: str | None = None,
) -> FRIADocument:
    """Create a new FRIA draft pre-filled with auto-populated data."""
    # Load the system
    result = await db.execute(
        select(AISystem).where(AISystem.id == system_id, AISystem.org_id == org_id)
    )
    system = result.scalar_one_or_none()
    if system is None:
        raise NotFoundError("AISystem", str(system_id))

    # Determine next version
    version_result = await db.execute(
        select(func.coalesce(func.max(FRIADocument.version), 0)).where(
            FRIADocument.system_id == system_id
        )
    )
    next_version = version_result.scalar_one() + 1

    # Build content from template with auto-populated fields
    content = await _build_content(db, org_id, system)

    doc = FRIADocument(
        org_id=org_id,
        system_id=system_id,
        version=next_version,
        status="draft",
        content=content,
        generated_by=generated_by,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # Update system FRIA status
    system.fria_status = "draft"
    await db.flush()

    log.info(
        "fria.generated",
        fria_id=str(doc.id),
        system_id=str(system_id),
        version=next_version,
    )
    return doc


async def get_fria(
    db: AsyncSession, org_id: uuid.UUID, fria_id: uuid.UUID
) -> FRIADocument:
    result = await db.execute(
        select(FRIADocument).where(
            FRIADocument.id == fria_id, FRIADocument.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise NotFoundError("FRIADocument", str(fria_id))
    return doc


async def list_frias(
    db: AsyncSession,
    org_id: uuid.UUID,
    system_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[FRIADocument]:
    query = (
        select(FRIADocument)
        .where(FRIADocument.org_id == org_id)
        .order_by(FRIADocument.generated_at.desc())
    )
    if system_id:
        query = query.where(FRIADocument.system_id == system_id)
    if status:
        query = query.where(FRIADocument.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_fria(
    db: AsyncSession,
    org_id: uuid.UUID,
    fria_id: uuid.UUID,
    content_updates: dict,
) -> FRIADocument:
    """Merge user-provided fields into a draft FRIA."""
    doc = await get_fria(db, org_id, fria_id)
    if doc.status != "draft":
        raise ConflictError("Only draft FRIAs can be edited")

    # Deep merge: user fields override template defaults per section
    merged = copy.deepcopy(doc.content)
    for section_id, fields in content_updates.items():
        if section_id in merged.get("sections", {}):
            merged["sections"][section_id].update(fields)
        else:
            merged.setdefault("sections", {})[section_id] = fields

    doc.content = merged
    await db.flush()
    await db.refresh(doc)
    log.info("fria.updated", fria_id=str(fria_id))
    return doc


async def approve_fria(
    db: AsyncSession,
    org_id: uuid.UUID,
    fria_id: uuid.UUID,
    approved_by: str,
    approver_title: str | None = None,
) -> FRIADocument:
    """Approve a draft FRIA: snapshot content, render PDF, set review date."""
    doc = await get_fria(db, org_id, fria_id)
    if doc.status != "draft":
        raise ConflictError("Only draft FRIAs can be approved")

    doc.status = "approved"
    doc.approved_by = approved_by
    doc.approver_title = approver_title
    from datetime import datetime, timezone

    doc.approved_at = datetime.now(timezone.utc)
    doc.next_review_date = date.today() + timedelta(days=365)

    # Render PDF
    try:
        from app.compliance.fria_html_template import render_fria_pdf

        doc.pdf_bytes = render_fria_pdf(doc)
    except Exception:
        log.warning("fria.pdf_render_failed", fria_id=str(fria_id), exc_info=True)
        # Don't block approval on PDF failure

    # Archive any previously approved version for this system
    prev_result = await db.execute(
        select(FRIADocument).where(
            FRIADocument.system_id == doc.system_id,
            FRIADocument.status == "approved",
            FRIADocument.id != doc.id,
        )
    )
    for prev in prev_result.scalars().all():
        prev.status = "archived"

    # Update system FRIA status
    system_result = await db.execute(
        select(AISystem).where(AISystem.id == doc.system_id)
    )
    system = system_result.scalar_one_or_none()
    if system:
        system.fria_status = "approved"

    await db.flush()
    await db.refresh(doc)
    log.info(
        "fria.approved",
        fria_id=str(fria_id),
        approved_by=approved_by,
        next_review=str(doc.next_review_date),
    )
    return doc


async def _build_content(
    db: AsyncSession, org_id: uuid.UUID, system: AISystem
) -> dict:
    """Walk the FRIA template and populate auto-filled sections."""
    template = copy.deepcopy(FRIA_TEMPLATE)
    sections: dict[str, dict] = {}

    for section_def in template["sections"]:
        section_id = section_def["id"]
        section_data: dict = {"title": section_def["title"]}

        if section_def.get("auto_populated"):
            section_data["fields"] = await _populate_section(
                db, org_id, system, section_def
            )
        else:
            # Initialize empty user-fill fields
            section_data["fields"] = {
                f["key"]: None for f in section_def["fields"]
            }
            section_data["field_definitions"] = section_def["fields"]

        sections[section_id] = section_data

    return {"template_version": template["version"], "sections": sections}


async def _populate_section(
    db: AsyncSession,
    org_id: uuid.UUID,
    system: AISystem,
    section_def: dict,
) -> dict:
    """Auto-populate a section's fields from DB data."""
    fields: dict = {}

    for field_def in section_def["fields"]:
        key = field_def["key"]
        source = field_def.get("source", "")

        if source.startswith("ai_systems."):
            attr = source.split(".", 1)[1]
            val = getattr(system, attr, None)
            fields[key] = str(val) if val is not None else None

        elif source == "ai_system_suppliers":
            suppliers = await db.execute(
                select(AISystemSupplier).where(
                    AISystemSupplier.system_id == system.id
                )
            )
            fields[key] = [
                {
                    "supplier_name": s.supplier_name,
                    "model_id": s.model_id,
                    "jurisdiction": s.jurisdiction,
                }
                for s in suppliers.scalars().all()
            ]

        elif source == "org.policies":
            policies = await db.execute(
                select(Policy).where(
                    Policy.org_id == org_id, Policy.is_active.is_(True)
                )
            )
            fields[key] = [
                {"name": p.name, "description": p.description}
                for p in policies.scalars().all()
            ]

        elif source.startswith("org."):
            # Load org and read attribute
            from app.db.models import Org

            org_result = await db.execute(
                select(Org).where(Org.id == org_id)
            )
            org = org_result.scalar_one_or_none()
            if org:
                attr = source.split(".", 1)[1]
                if "." in attr:
                    # Nested: org.detector_config.custom_rules
                    parts = attr.split(".")
                    val = getattr(org, parts[0], None)
                    if isinstance(val, dict):
                        val = val.get(parts[1])
                    fields[key] = val
                else:
                    fields[key] = getattr(org, attr, None)

        elif source == "computed":
            fields[key] = await _compute_field(db, org_id, key)

        else:
            fields[key] = None

    return fields


async def _compute_field(
    db: AsyncSession, org_id: uuid.UUID, key: str
) -> str | dict | None:
    """Compute derived fields for auto-populated sections."""
    if key == "human_oversight_rbac":
        return "RBAC enabled with viewer/admin/owner roles"
    elif key == "audit_log_retention":
        return "Audit log maintained with tamper-evident hash chain"
    elif key == "incident_workflow":
        return "Automated incident detection with severity-based escalation"
    return None
