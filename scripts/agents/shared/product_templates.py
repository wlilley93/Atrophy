"""Structured intelligence product templates.

Each template defines the required structure for a product type.
Agents reference these when generating briefs to ensure consistent format.
The Meridian platform uses product_type to render each brief with appropriate styling.
"""

TEMPLATES = {
    "SITREP": {
        "name": "Situation Report",
        "description": "Point-in-time situation assessment",
        "sections": [
            {"name": "situation", "required": True, "description": "Current state of affairs"},
            {"name": "assessment", "required": True, "description": "Analyst interpretation and judgment"},
            {"name": "outlook", "required": True, "description": "Expected trajectory (24-72 hours)"},
            {"name": "recommendations", "required": False, "description": "Suggested actions or watch items"},
        ],
        "used_by": ["three_hour_update", "daily_battlefield"],
    },
    "INTSUM": {
        "name": "Intelligence Summary",
        "description": "Multi-source intelligence synthesis with confidence levels",
        "sections": [
            {"name": "key_judgments", "required": True, "description": "Top 3-5 judgments with confidence (HIGH/MODERATE/LOW)"},
            {"name": "collection_summary", "required": True, "description": "What sources contributed and gaps"},
            {"name": "detailed_analysis", "required": True, "description": "Full analysis organized by topic"},
            {"name": "information_gaps", "required": False, "description": "What we don't know and need to find out"},
        ],
        "used_by": ["weekly_digest", "weekly_conflicts"],
    },
    "FLASH": {
        "name": "Flash Report",
        "description": "Urgent time-sensitive intelligence",
        "sections": [
            {"name": "event", "required": True, "description": "What happened (who, what, where, when)"},
            {"name": "significance", "required": True, "description": "Why this matters"},
            {"name": "implications", "required": True, "description": "Immediate consequences and second-order effects"},
            {"name": "confidence", "required": True, "description": "Source reliability and information confidence"},
        ],
        "used_by": ["flash_report"],
    },
    "WARNING": {
        "name": "Warning Intelligence",
        "description": "Threat assessment with likelihood and impact",
        "sections": [
            {"name": "threat", "required": True, "description": "Nature of the threat"},
            {"name": "indicators", "required": True, "description": "Observable indicators supporting the warning"},
            {"name": "likelihood", "required": True, "description": "Assessment: LIKELY/POSSIBLE/UNLIKELY with reasoning"},
            {"name": "impact", "required": True, "description": "Potential impact if threat materializes"},
            {"name": "recommended_action", "required": True, "description": "What should be done"},
        ],
        "used_by": ["geofence_alert"],
    },
    "PROFILE": {
        "name": "Entity Profile",
        "description": "Dossier on a person, organization, or faction",
        "sections": [
            {"name": "identity", "required": True, "description": "Name, aliases, type, affiliation"},
            {"name": "background", "required": True, "description": "History and context"},
            {"name": "capabilities", "required": False, "description": "Known capabilities and resources"},
            {"name": "relationships", "required": True, "description": "Key relationships and alliances"},
            {"name": "recent_activity", "required": False, "description": "Recent notable actions"},
            {"name": "assessment", "required": True, "description": "Analyst assessment of intent and trajectory"},
        ],
        "used_by": ["entity_enrichment", "commission_response"],
    },
    "WEEKLY_DIGEST": {
        "name": "Weekly Digest",
        "description": "Comprehensive weekly six-track assessment",
        "sections": [
            {"name": "executive_summary", "required": True, "description": "Top-line assessment (3-5 sentences)"},
            {"name": "track_assessments", "required": True, "description": "Per-track situation and outlook"},
            {"name": "week_ahead", "required": True, "description": "Key events and watchpoints for next 7 days"},
            {"name": "prediction_log", "required": False, "description": "Forward-looking assessments to track"},
        ],
        "used_by": ["weekly_digest"],
    },
    "SYNTHESIS": {
        "name": "Cross-Domain Synthesis",
        "description": "Convergence report identifying patterns across domains",
        "sections": [
            {"name": "convergence_signals", "required": True, "description": "Cross-domain patterns identified"},
            {"name": "contributing_channels", "required": True, "description": "Which agents/domains contributed signals"},
            {"name": "assessment", "required": True, "description": "What the convergence means"},
            {"name": "confidence", "required": True, "description": "Confidence in the synthesis"},
        ],
        "used_by": ["cross_agent_synthesis"],
    },
    "PERFORMANCE": {
        "name": "Performance Review",
        "description": "Agent performance metrics and calibration",
        "sections": [
            {"name": "summary", "required": True, "description": "Overall performance assessment"},
            {"name": "metrics", "required": True, "description": "Quantitative metrics per agent"},
            {"name": "calibration", "required": False, "description": "Prediction accuracy review"},
            {"name": "recommendations", "required": True, "description": "Recommended changes to agent prompts or allocation"},
        ],
        "used_by": ["process_audit"],
    },
}


def get_template(product_type: str) -> dict | None:
    """Get a product template by type."""
    return TEMPLATES.get(product_type)


def get_template_prompt(product_type: str) -> str:
    """Generate a prompt section instructing an agent to follow the template."""
    template = TEMPLATES.get(product_type)
    if not template:
        return ""

    lines = [f"## Output Format: {template['name']}", ""]
    lines.append(f"{template['description']}")
    lines.append("")
    lines.append("Structure your response with these sections:")
    lines.append("")
    for section in template["sections"]:
        req = "REQUIRED" if section["required"] else "optional"
        lines.append(f"### {section['name'].replace('_', ' ').title()} ({req})")
        lines.append(f"{section['description']}")
        lines.append("")

    return "\n".join(lines)


def list_templates() -> list[dict]:
    """List all available templates with metadata."""
    return [
        {
            "type": key,
            "name": val["name"],
            "description": val["description"],
            "sections": len(val["sections"]),
            "required_sections": sum(1 for s in val["sections"] if s["required"]),
        }
        for key, val in TEMPLATES.items()
    ]
