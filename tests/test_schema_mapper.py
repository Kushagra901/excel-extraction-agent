from src.agents.schema_mapper import SchemaMapperAgent


def test_exact_match_headers():
    mapper = SchemaMapperAgent()
    result = mapper.map_headers(["Email", "Phone", "Date"])
    assert result["Email"].canonical_field == "email"
    assert result["Email"].method == "exact"
    assert result["Phone"].canonical_field == "phone"
    assert result["Date"].canonical_field == "date"


def test_fuzzy_match_messy_headers():
    mapper = SchemaMapperAgent(threshold=0.6)
    result = mapper.map_headers(["Cust Name", "E-Mail Addr", "Total ($)"])
    assert result["Cust Name"].canonical_field == "full_name"
    assert result["E-Mail Addr"].canonical_field == "email"
    assert result["Total ($)"].canonical_field == "amount"


def test_bare_client_maps_to_full_name_not_id():
    """Regression test: 'Client' was previously mis-mapped to 'id' because
    'client id' scored higher than 'client name' under naive ratio matching.
    Direct synonym now guarantees the correct exact match."""
    mapper = SchemaMapperAgent()
    result = mapper.map_headers(["Client"])
    assert result["Client"].canonical_field == "full_name"


def test_unmappable_header_stays_unmapped():
    mapper = SchemaMapperAgent(threshold=0.8)
    result = mapper.map_headers(["xyz_random_column_123"])
    assert result["xyz_random_column_123"].canonical_field is None
    assert result["xyz_random_column_123"].method == "unmapped"


def test_blank_header_is_unmapped_not_crash():
    mapper = SchemaMapperAgent()
    result = mapper.map_headers([""])
    assert result[""].canonical_field is None
