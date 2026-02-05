"""
Structured extraction schema for power / site readiness docs.
Keep this file data-only (no DB/LLM imports).
"""

ALLOWED_KEYS: dict[str, dict] = {
    # Identity / linkage
    "doc_title": {"type": "string"},
    "doc_type": {"type": "string"},
    "project_name": {"type": "string"},
    "site_name": {"type": "string"},
    "utility_name": {"type": "string"},
    "developer_name": {"type": "string"},
    "owner_name": {"type": "string"},

    # Location / parcel
    "site_address": {"type": "string"},
    "city": {"type": "string"},
    "state": {"type": "string"},
    "zip_code": {"type": "string"},
    "county": {"type": "string"},
    "apn_parcel_id": {"type": "string"},
    "parcel_count": {"type": "number"},
    "latitude": {"type": "number", "unit": "deg"},
    "longitude": {"type": "number", "unit": "deg"},
    "site_area": {"type": "number", "unit": "ac"},
    "buildable_area": {"type": "number", "unit": "ac"},

    # Zoning / permitting
    "zoning_designation": {"type": "string"},
    "zoning_allows_energy_storage": {"type": "bool"},
    "conditional_use_permit_required": {"type": "bool"},
    "permitting_authority": {"type": "string"},
    "fire_marshal_required": {"type": "bool"},
    "environmental_review_required": {"type": "bool"},
    "setback_requirement": {"type": "number", "unit": "ft"},
    "flood_zone": {"type": "string"},
    "wetlands_present": {"type": "bool"},
    "hazmat_risk_present": {"type": "bool"},
    "noise_limit": {"type": "number", "unit": "dBA"},

    # Electrical service (existing)
    "service_voltage": {"type": "number", "unit": "kV"},
    "service_phase": {"type": "string"},
    "service_three_phase_available": {"type": "bool"},
    "service_capacity_existing": {"type": "number", "unit": "kW"},
    "service_capacity_upgrade_possible": {"type": "bool"},
    "meter_present": {"type": "bool"},
    "service_drop_type": {"type": "string"},
    "main_switchgear_present": {"type": "bool"},
    "switchgear_rating": {"type": "number", "unit": "A"},
    "breaker_rating": {"type": "number", "unit": "A"},
    "power_quality_issues_reported": {"type": "bool"},

    # Transformer / substation / feeder
    "transformer_present": {"type": "bool"},
    "transformer_count": {"type": "number"},
    "transformer_kva": {"type": "number", "unit": "kVA"},
    "transformer_primary_voltage": {"type": "number", "unit": "kV"},
    "transformer_secondary_voltage": {"type": "number", "unit": "V"},
    "substation_name": {"type": "string"},
    "substation_distance": {"type": "number", "unit": "mi"},
    "feeder_id": {"type": "string"},
    "circuit_id": {"type": "string"},
    "interconnection_point": {"type": "string"},
    "interconnect_voltage": {"type": "number", "unit": "kV"},
    "available_capacity": {"type": "number", "unit": "MW"},
    "thermal_limit_binding": {"type": "bool"},
    "voltage_limit_binding": {"type": "bool"},
    "protection_upgrade_required": {"type": "bool"},

    # Interconnection process / queue
    "interconnection_request_id": {"type": "string"},
    "queue_position": {"type": "string"},
    "study_stage": {"type": "string"},
    "study_date": {"type": "string"},
    "estimated_upgrade_cost": {"type": "number", "unit": "USD"},
    "upgrade_cost_range_low": {"type": "number", "unit": "USD"},
    "upgrade_cost_range_high": {"type": "number", "unit": "USD"},
    "estimated_timeline_months": {"type": "number", "unit": "mo"},
    "utility_construction_required": {"type": "bool"},
    "network_upgrade_required": {"type": "bool"},
    "distribution_upgrade_required": {"type": "bool"},

    # Load / usage
    "annual_energy_kwh": {"type": "number", "unit": "kWh"},
    "monthly_energy_kwh": {"type": "number", "unit": "kWh"},
    "peak_demand_kw": {"type": "number", "unit": "kW"},
    "average_demand_kw": {"type": "number", "unit": "kW"},
    "load_factor": {"type": "number"},
    "rate_tariff": {"type": "string"},

    # BESS / generator / equipment
    "bess_present": {"type": "bool"},
    "bess_power_mw": {"type": "number", "unit": "MW"},
    "bess_energy_mwh": {"type": "number", "unit": "MWh"},
    "inverter_count": {"type": "number"},
    "inverter_rating_kw": {"type": "number", "unit": "kW"},
    "pcs_present": {"type": "bool"},
    "generator_present": {"type": "bool"},
    "generator_count": {"type": "number"},
    "generator_power_kw": {"type": "number", "unit": "kW"},
    "fuel_type": {"type": "string"},

    # Constructability
    "site_access_road_present": {"type": "bool"},
    "truck_access_possible": {"type": "bool"},
    "crane_access_possible": {"type": "bool"},
    "fence_present": {"type": "bool"},
    "site_secured": {"type": "bool"},
    "grading_required": {"type": "bool"},
    "slope_percent": {"type": "number", "unit": "%"},

    # Notes
    "summary": {"type": "string"},
    "red_flags": {"type": "string"},
    "next_steps": {"type": "string"},
}
